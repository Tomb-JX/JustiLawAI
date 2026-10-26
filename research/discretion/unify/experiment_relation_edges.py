"""Fixed-candidate relation models on the 120-event model-majority batch.

Development = train + calibration (80 events): nested event-level CV, inner
folds choose the NIL threshold, outer folds score. Only after `freeze` writes an
artifact may `holdout` read the 40 sealed events, once. References are
model-majority drafts (A/B + blind C), never human gold.

Ablations keep candidates and learner fixed and change one thing:
features (local vs cross-candidate structure), supervision (field vs agreed
edge labels) and extra data (old silver train 140). Age compares deterministic
date derivation with an explicit-stated-age fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

from audit_supply_replay import rows
from evaluate_relation_model_labels import (CHAIN, amount_key, chain_value, frozen_predictions,
                                            int_key, model_value, score, vote)
from experiment_age_count_closure import age_prediction
from experiment_candidate_nil import candidate_examples, candidate_x
from experiment_participant_list import MASKED, candidate_lists
from experiment_relation_suite import count_features, count_paths
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic
from minimal_amount_closure import load_records, scene_features
from supply_packet import build_packet

AMOUNT_FIELDS = ("personal_stake", "onsite_stake_total")
SILVER_FIELD = {"personal_stake": "amounts.personal_stake", "onsite_stake_total": "amounts.onsite_stake_total"}
PROVIDERS, ARBITER = ("bailian", "deepseek"), "kimi"
DEV_SPLITS = {"train", "calibration"}
HOLDOUT = "model_draft_holdout"
GRID = [i / 100 for i in range(5, 96, 5)]
AMOUNT_VARIANTS = ("local/field", "structure/field", "structure/edge", "structure/field+silver")
COUNT_VARIANTS = ("local", "context", "context+silver")


# ---------- references from the frozen model-draft batch ----------

def load_batch(batch: Path, labels: Path) -> list[dict]:
    """Each record carries packet, per-field majority (status, value) and the voters' candidate ids."""
    out = []
    for record in rows(batch / "inputs.jsonl"):
        rid = record["id"]
        packet = build_packet(record["text_full"], record, record_id=rid)
        quantities = {q["candidate_id"]: q for q in packet["quantities"]}
        lists = {l["candidate_id"]: l for l in candidate_lists(packet, record["target"], record["aliases"])}
        drafts = {}
        for name in PROVIDERS + (ARBITER,):
            path = label_path(labels, rid, name)
            if path is not None:
                drafts[name] = json.loads(path.read_text("utf-8"))["annotation"]
        refs = {}
        for field in AMOUNT_FIELDS + ("participant_count", "age"):
            values = {n: model_value(field, d["fields"][field], quantities, lists) for n, d in drafts.items()}
            ab = [values[p] for p in PROVIDERS if p in values]
            if len(ab) == 2 and ab[0] == ab[1]:
                consensus = ab[0]
            elif ARBITER in values and len(values) >= 2:
                # With a missing A/B draft, C stands in: two present votes must agree (strict majority).
                consensus = vote(list(values.values()))
            else:
                consensus = None
            ids = {d["fields"][field].get("candidate_id") for n, d in drafts.items()
                   if consensus and consensus[0] == "selected" and values[n] == consensus}
            refs[field] = {"consensus": consensus, "candidate_ids": ids - {None}}
        out.append({"id": rid, "record": record, "packet": packet, "refs": refs,
                    "edges": agreed_edges(drafts), "event": record["event_cluster_id"],
                    "split": record["split"], "group": record["selection_group"]})
    return out


# The DeepSeek direct API ran out of balance on 2026-10-26; the same family hosted on
# Bailian ("dsb") fills the B slot only where the direct-API draft is missing.
# Bailian (kimi's host) was suspended again the same day; Claude subagent answers fill the
# C slot only where no kimi vote exists (holdout pair labels).
B_FALLBACK = {"deepseek": "dsb", "kimi": "claude"}


def label_path(labels: Path, rid: str, name: str) -> Path | None:
    for candidate in (name, B_FALLBACK.get(name)):
        if candidate and (labels / f"{rid}-{candidate}.json").exists():
            return labels / f"{rid}-{candidate}.json"
    return None


def agreed_edges(drafts: dict) -> dict[str, dict]:
    """Candidate edges on which A and B agree on decision, role set and owner."""
    if not all(p in drafts for p in PROVIDERS):
        return {}
    a, b =({e["candidate_id"]: e for e in drafts[p]["candidate_edges"]} for p in PROVIDERS)
    out = {}
    for cid, x in a.items():
        y = b.get(cid)
        if y and x["decision"] == y["decision"] and (
                x["decision"] != "asserted" or (set(x["roles"]) == set(y["roles"]) and x["owner"] == y["owner"])):
            if x["decision"] != "uncertain":
                out[cid] = x
    return out


def edge_label(edge: dict | None, field: str) -> bool | None:
    if edge is None:
        return None
    if edge["decision"] == "irrelevant":
        return False
    if field == "personal_stake":
        return "personal_stake" in edge["roles"] and edge["owner"] in {"target", "target_and_scene"}
    return "onsite_stake_total" in edge["roles"]


# ---------- features ----------

def amounts_of(packet: dict) -> list[dict]:
    return [q for q in packet["quantities"] if q["type"] == "amount" and q["parse_status"] == "resolved"
            and (q.get("engine_projection") or {}).get("min") is not None]


def other_people(packet: dict, inp: dict) -> int:
    """Distinct non-target person tokens in facts: masked names and closed-list slots (auxiliary only)."""
    names = {inp["target"], *(inp.get("aliases") or ())}
    seen = set()
    for view in packet["visible_spans"]:
        if view["zone"] == "facts":
            seen.update(m.group(0) for m in MASKED.finditer(view["quote"]))
    for l in candidate_lists(packet, inp["target"], inp.get("aliases") or ()):
        seen.update(m["raw"] for m in l["mentions"])
    # Masked tokens of the target (e.g. 韦**) are indistinguishable from same-surname others; keep them out.
    return len({s for s in seen if s not in names and not any(n and (n in s or s in n) for n in names)})


def structure(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    """Relations between this amount and the other candidates and people of the record."""
    x = scene_features(q, inp, packet, "scene_structure")
    pool = amounts_of(packet)
    value = float(q["engine_projection"]["min"])
    others = [a for a in pool if a["candidate_id"] != q["candidate_id"]]
    vals = [float(a["engine_projection"]["min"]) for a in others]
    x["amounts_in_record:" + ("1" if not others else "2" if len(others) == 1 else "3-4" if len(others) <= 3 else "5+")] = 1.0
    if others:
        x["is_max_amount"] = float(value > max(vals))
        x["is_min_amount"] = float(value < min(vals))
        x["same_value_elsewhere"] = float(value in vals)
        small = vals[:8]
        x["is_sum_of_others"] = float(any(abs(sum(c) - value) < 0.5 for k in (2, 3)
                                          for c in combinations(small, k)))
        x["is_part_of_other_sum"] = float(any(
            abs(sum(c) + value - t) < 0.5 for t in small for k in (1, 2)
            for c in combinations([v for v in small if v != t], k)))
    n_people = other_people(packet, inp)
    counts = [q2["engine_projection"]["min"] for q2 in packet["quantities"] if q2["type"] == "count"
              and q2.get("unit") == "人" and (q2.get("engine_projection") or {}).get("exact")]
    alone = n_people == 0 and not any(c > 1 for c in counts)
    x["other_people:" + ("0" if n_people == 0 else "1" if n_people == 1 else "2-3" if n_people <= 3 else "4+")] = 1.0
    x["target_alone:" + str(alone)] = 1.0
    x["target_alone_x_actor:" + str(alone) + ":" + str(q.get("actor_status") or "unresolved")] = 1.0
    x["target_alone_x_single_amount:" + str(alone) + ":" + str(not others)] = 1.0
    return x


def amount_fn(config: str):
    return candidate_x if config == "local" else structure


def count_fn(config: str):
    def make(path: dict, inp: dict, packet: dict) -> dict[str, float]:
        x = count_features(path, inp, packet, "scene_relation")
        if config == "local":
            return x
        n = other_people(packet, inp)
        x["other_people:" + ("0" if n == 0 else "1-2" if n <= 2 else "3-5" if n <= 5 else "6+")] = 1.0
        x["value_vs_people:" + ("eq+1" if path["value"] == n + 1 else "eq" if path["value"] == n
                                else "gt" if path["value"] > n + 1 else "lt")] = 1.0
        return x
    return make


# ---------- training examples ----------

def amount_examples(items: list[dict], field: str, supervision: str, fn) -> list[tuple]:
    out = []
    for it in items:
        ref = it["refs"][field]
        if ref["consensus"] is None or ref["consensus"][0] not in {"selected", "absent"}:
            continue
        inp, packet = it["record"], it["packet"]
        for q in amounts_of(packet):
            if supervision == "edge":
                y = edge_label(it["edges"].get(q["candidate_id"]), field)
            elif ref["consensus"][0] == "absent":
                y = False
            elif q["candidate_id"] in ref["candidate_ids"]:
                y = True
            else:
                # Same-value rivals stay unlabeled rather than becoming false negatives.
                y = None if amount_key(q["engine_projection"]) == ref["consensus"][1] else False
            if y is not None:
                out.append((fn(q, inp, packet), y))
    return out


def count_examples_new(items: list[dict], fn) -> list[tuple]:
    out = []
    for it in items:
        ref = it["refs"]["participant_count"]
        if ref["consensus"] is None or ref["consensus"][0] not in {"selected", "absent"}:
            continue
        inp, packet = it["record"], it["packet"]
        for path in count_paths(packet, inp["target"], inp["aliases"]):
            if ref["consensus"][0] == "absent":
                y = False
            elif path["id"] in ref["candidate_ids"]:
                y = True
            else:
                y = None if "int:" + str(path["value"]) == ref["consensus"][1] else False
            if y is not None:
                out.append((fn(path, inp, packet), y))
    return out


def fit_balanced(examples: list[tuple]) -> SparseLogistic:
    pos = [x for x, y in examples if y]
    neg = [x for x, y in examples if not y]
    if not pos or not neg:
        raise ValueError("training_class_missing")
    repeats = max(1, round(len(neg) / len(pos)))
    model = SparseLogistic()
    model.fit(examples + [(x, True) for _ in range(repeats - 1) for x in pos])
    return model


# ---------- prediction and scoring ----------

def predict_amount(it: dict, model: SparseLogistic, fn) -> tuple[float, str | None, list[tuple]]:
    inp, packet = it["record"], it["packet"]
    scored = sorted(((model.predict(fn(q, inp, packet)), q) for q in amounts_of(packet)),
                    key=lambda s: (-s[0], s[1]["start"]))
    if not scored:
        return 0.0, None, []
    return scored[0][0], amount_key(scored[0][1]["engine_projection"]), [(s, q["candidate_id"]) for s, q in scored]


def predict_count(it: dict, model: SparseLogistic, fn) -> tuple[float, str | None, list[tuple]]:
    inp, packet = it["record"], it["packet"]
    scored = sorted(((model.predict(fn(p, inp, packet)), p) for p in count_paths(packet, inp["target"], inp["aliases"])),
                    key=lambda s: (-s[0], s[1]["start"], s[1]["id"]))
    if not scored:
        return 0.0, None, []
    return scored[0][0], "int:" + str(scored[0][1]["value"]), [(s, p["id"]) for s, p in scored]


def decide(preds: dict, threshold: float) -> dict:
    return {rid: (v if s >= threshold else None) for rid, (s, v, _) in preds.items()}


def field_rows(items: list[dict], field: str, decided: dict) -> list[dict]:
    return [{"consensus": it["refs"][field]["consensus"], "group": it["group"],
             "chain": decided[it["id"]]} for it in items]


def f1(metric: dict) -> float:
    fp = metric.get("wrong_value", 0) + metric.get("output_on_absent", 0)
    fn = metric.get("wrong_value", 0) + metric.get("abstain_on_positive", 0)
    tp = metric.get("tp", 0)
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def pick_threshold(items: list[dict], field: str, preds: dict) -> float:
    def key(t):
        m = score(field_rows(items, field, decide(preds, t)))
        return (f1(m), -(m.get("wrong_value", 0) + m.get("output_on_absent", 0)), t)
    return max(GRID, key=key)


def edge_metric(items: list[dict], field: str, preds: dict, threshold: float) -> dict:
    """Candidate-level role+owner edge P/R/F1 against A/B-agreed edges (amount fields only)."""
    c = Counter()
    for it in items:
        for s, cid in preds[it["id"]][2]:
            y = edge_label(it["edges"].get(cid), field)
            if y is None:
                c["unlabeled"] += 1
                continue
            p = s >= threshold
            c["tp" if p and y else "fp" if p else "fn" if y else "tn"] += 1
    prec = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
    rec = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    c["precision"] = round(prec, 3) if prec is not None else None
    c["recall"] = round(rec, 3) if rec is not None else None
    c["f1"] = round(2 * prec * rec / (prec + rec), 3) if prec and rec else 0.0
    return dict(c)


def summarize(items: list[dict], field: str, decided: dict) -> dict:
    out = {"all": score(field_rows(items, field, decided))}
    out["all"]["f1"] = round(f1(out["all"]), 3)
    for g in ("challenge", "random"):
        out[g] = score(field_rows([i for i in items if i["group"] == g], field, decided))
    return out


# ---------- variants ----------

class Variant:
    def __init__(self, field: str, name: str, silver: list[tuple]):
        self.field, self.name, self.silver = field, name, silver
        if field == "participant_count":
            self.fn = count_fn("local" if name == "local" else "context")
            self.use_silver = name.endswith("+silver")
        else:
            config, supervision = name.split("/")
            self.fn = amount_fn(config)
            self.supervision = supervision.replace("+silver", "")
            self.use_silver = supervision.endswith("+silver")

    def fit(self, items: list[dict]) -> SparseLogistic:
        if self.field == "participant_count":
            ex = count_examples_new(items, self.fn)
            if self.use_silver:
                ex += [(self.fn(p, inp, packet), y) for p, inp, packet, y in silver_count_paths(self.silver)]
        else:
            ex = amount_examples(items, self.field, self.supervision, self.fn)
            if self.use_silver:
                ex += candidate_examples(self.silver, SILVER_FIELD[self.field], self.fn)[0]
        return fit_balanced(ex)

    def predict(self, items: list[dict], model: SparseLogistic) -> dict:
        pred = predict_count if self.field == "participant_count" else predict_amount
        return {it["id"]: pred(it, model, self.fn) for it in items}


def silver_count_paths(silver: list[tuple]):
    """Old-silver count paths labelled like the existing count experiment (value + evidence locality)."""
    from experiment_age_count_closure import evidence_contains
    from experiment_silver_supervised_pipeline import present
    for _, inp, packet, ref in silver:
        item = ref["reference_elements"]["persons"]["participant_count"]
        for p in count_paths(packet, inp["target"], inp.get("aliases") or ()):
            if not present(item):
                yield p, inp, packet, False
            elif p["value"] == item["value"] and evidence_contains(p, item):
                yield p, inp, packet, True
            elif p["value"] != item["value"]:
                yield p, inp, packet, False


def nested_cv(dev: list[dict], variant: Variant) -> tuple[dict, list[float], Counter]:
    """Outer 5 event folds score; each outer threshold comes from inner OOF on its own training part."""
    decided, thresholds, edges = {}, [], Counter()
    for k in range(5):
        train = [i for i in dev if event_fold(i["event"]) != k]
        held = [i for i in dev if event_fold(i["event"]) == k]
        inner = {}
        for j in range(5):
            fit_part = [i for i in train if event_fold(i["event"] + "#inner") != j]
            inner_held = [i for i in train if event_fold(i["event"] + "#inner") == j]
            if inner_held:
                inner.update(variant.predict(inner_held, variant.fit(fit_part)))
        threshold = pick_threshold(train, variant.field, inner)
        thresholds.append(threshold)
        out = variant.predict(held, variant.fit(train))
        decided.update(decide(out, threshold))
        if variant.field in AMOUNT_FIELDS:
            m = edge_metric(held, variant.field, out, threshold)
            edges.update({key: m.get(key, 0) for key in ("tp", "fp", "fn", "tn", "unlabeled")})
    return decided, thresholds, edges


def age_variants(items: list[dict]) -> dict:
    out = {}
    for name in ("derive_only", "derive+stated_fallback"):
        rows_ = []
        for it in items:
            p = age_prediction(it["packet"])
            value = "int:" + str(p["value"]) if p["status"] == "selected" else None
            if value is None and name != "derive_only" and p.get("birth_candidates", 1) == 0:
                stated = {int_key(q.get("engine_projection")) for q in it["packet"]["quantities"]
                          if q["type"] == "age" and q.get("parse_status") == "resolved"} - {None}
                value = next(iter(stated)) if len(stated) == 1 else None
            ref = it["refs"]["age"]["consensus"]
            conflict = bool(ref and ref[0] == "selected" and value and p["status"] == "selected"
                            and abs(int(value[4:]) - int(ref[1][4:])) == 1)
            rows_.append({"consensus": ref, "chain": value, "group": it["group"], "age_definition_conflict": conflict})
        out[name] = score(rows_)
        out[name]["f1"] = round(f1(out[name]), 3)
    return out


def utility(metric: dict) -> int:
    """A wrong or unwarranted field costs twice an abstention (which goes to human review)."""
    return metric.get("tp", 0) - 2 * (metric.get("wrong_value", 0) + metric.get("output_on_absent", 0))


def chain_decisions(items: list[dict], chain: dict, field: str) -> dict:
    return {it["id"]: chain_value(field, chain[it["id"]][CHAIN[field]]) for it in items}


# ---------- stages ----------

def develop(items: list[dict], silver: list[tuple], chain: dict) -> dict:
    dev = [i for i in items if i["split"] in DEV_SPLITS]
    report = {"scope": "nested_event_cv_on_train+calibration", "holdout_read": False,
              "reference": "model_draft_majority_not_human_gold", "dev_records": len(dev), "fields": {}}
    for field, names in [(f, AMOUNT_VARIANTS) for f in AMOUNT_FIELDS] + [("participant_count", COUNT_VARIANTS)]:
        report["fields"][field] = {"frozen_chain": summarize(dev, field, chain_decisions(dev, chain, field))}
        for name in names:
            variant = Variant(field, name, silver)
            decided, thresholds, edges = nested_cv(dev, variant)
            result = summarize(dev, field, decided)
            result["outer_thresholds"] = thresholds
            result["edges"] = finish_edges(edges) if field in AMOUNT_FIELDS else None
            report["fields"][field][name] = result
    report["fields"]["age"] = age_variants(dev)
    return report


def finish_edges(total: Counter) -> dict:
    p = total["tp"] / (total["tp"] + total["fp"]) if total["tp"] + total["fp"] else None
    r = total["tp"] / (total["tp"] + total["fn"]) if total["tp"] + total["fn"] else None
    return {**total, "precision": round(p, 3) if p is not None else None,
            "recall": round(r, 3) if r is not None else None,
            "f1": round(2 * p * r / (p + r), 3) if p and r else 0.0}


def choose(report: dict, rule: str = "utility") -> dict:
    """Best dev variant per field by utility (or F1), ties to the earlier, simpler entry.

    The frozen chain is listed first, so a learned variant must strictly beat it.
    """
    choice = {}
    for field, variants in report["fields"].items():
        order = list(variants)
        metric = (lambda n: variants[n]) if field == "age" else (lambda n: variants[n]["all"])
        primary = utility if rule == "utility" else (lambda m: m["f1"])
        choice[field] = max(order, key=lambda n: (primary(metric(n)), -order.index(n)))
    return choice


def freeze(items: list[dict], silver: list[tuple], report: dict, batch_hash: str) -> dict:
    dev = [i for i in items if i["split"] in DEV_SPLITS]
    choice = choose(report)
    artifact = {"version": "relation-edges-1", "batch_inputs_sha256": batch_hash,
                "selection_rule": "utility = tp - 2*(wrong_value + output_on_absent); frozen chain first",
                "selection_rule_fixed_after_dev_before_holdout": True,
                "f1_rule_would_choose": choose(report, "f1"),
                "chosen": choice, "holdout_read_before_freeze": False, "fields": {}}
    for field in AMOUNT_FIELDS + ("participant_count",):
        if choice[field] == "frozen_chain":
            artifact["fields"][field] = {"variant": "frozen_chain"}
            continue
        variant = Variant(field, choice[field], silver)
        oof = {}
        for k in range(5):
            train = [i for i in dev if event_fold(i["event"]) != k]
            held = [i for i in dev if event_fold(i["event"]) == k]
            oof.update(variant.predict(held, variant.fit(train)))
        model = variant.fit(dev)
        artifact["fields"][field] = {"variant": choice[field], "threshold": pick_threshold(dev, field, oof),
                                     "weights": dict(model.weights), "bias": model.bias}
    artifact["fields"]["age"] = {"variant": choice["age"]}
    return artifact


def holdout(items: list[dict], silver: list[tuple], artifact: dict, chain: dict) -> dict:
    test = [i for i in items if i["split"] == HOLDOUT]
    report = {"scope": "frozen_holdout_once", "records": len(test),
              "reference": "model_draft_majority_not_human_gold", "chosen": artifact["chosen"], "fields": {}}
    for field in AMOUNT_FIELDS + ("participant_count",):
        spec = artifact["fields"][field]
        baseline = summarize(test, field, chain_decisions(test, chain, field))
        if spec["variant"] == "frozen_chain":
            report["fields"][field] = {"frozen_chain": baseline}
            continue
        variant = Variant(field, spec["variant"], silver)
        model = SparseLogistic()
        model.weights.update(spec["weights"])
        model.bias = spec["bias"]
        preds = variant.predict(test, model)
        result = summarize(test, field, decide(preds, spec["threshold"]))
        result["threshold"] = spec["threshold"]
        if field in AMOUNT_FIELDS:
            result["edges"] = edge_metric(test, field, preds, spec["threshold"])
        result["risk_coverage"] = {str(t): score(field_rows(test, field, decide(preds, t)))
                                   for t in (0.3, 0.5, 0.7, 0.85)}
        report["fields"][field] = {spec["variant"]: result, "frozen_chain": baseline}
    report["fields"]["age"] = age_variants(test)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("develop", "freeze", "holdout"))
    for name in ("batch", "labels", "teacher", "originals", "silver", "out"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--artifact", type=Path)
    for name in ("amount_artifact", "age_artifact", "engine_root"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    items = load_batch(args.batch, args.labels)
    silver = load_records(args.teacher, args.originals, args.silver, {"train"})
    batch_hash = hashlib.sha256((args.batch / "inputs.jsonl").read_bytes()).hexdigest()
    chain = frozen_predictions([i["record"] for i in items], args.amount_artifact, args.age_artifact,
                               args.engine_root)
    if args.stage == "develop":
        result = develop(items, silver, chain)
    elif args.stage == "freeze":
        result = freeze(items, silver, json.loads(args.artifact.read_text("utf-8")), batch_hash)
    else:
        artifact = json.loads(args.artifact.read_text("utf-8"))
        if artifact["batch_inputs_sha256"] != batch_hash:
            raise ValueError("frozen_batch_hash_mismatch")
        result = holdout(items, silver, artifact, chain)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result.get("chosen") or {f: {n: (v["all"] if "all" in v else v) for n, v in vs.items()}
                                              if f != "age" else vs for f, vs in result["fields"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
