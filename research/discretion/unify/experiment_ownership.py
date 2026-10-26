"""Amount ownership: edge-level identification and field-level effect.

Part 1 (edges): who an amount belongs to, {target, other, shared}, scored against
A/B-agreed owner edges on the development events with event-level 5-fold CV.
Compared: majority class, the packet's actor hint, a nearest-left-person rule,
and 3-way softmax on local vs local+ownership features.

Part 2 (fields): the frozen 4-way role model (softmax/semantic) vs the same with
ownership features. The adoption decision uses development CV only; both are then
frozen and reported once on H1 (batch 3, model-majority reference) and H2 (the old
203 silver records, an independently produced field-level reference).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from evaluate_relation_model_labels import amount_key, frozen_predictions
from experiment_candidate_nil import candidate_x
from experiment_joint_amount_roles import (FIELDS, HOLDOUT, Softmax, Variant, decide, mentions_for,
                                           nested_cv, pick_threshold, summarize)
from experiment_relation_edges import amounts_of, chain_decisions, load_batch
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import present
from minimal_amount_closure import load_records
from ownership import owner_features

CLASSES = ("target", "other", "shared")
OWNER_MAP = {"target": "target", "target_and_scene": "target", "other": "other", "shared_scene": "shared"}
FIELD_VARIANTS = ("softmax/semantic", "softmax/semantic_owner")


# ---------- part 1: owner edges ----------

def owner_examples(items: list[dict]) -> list[tuple[dict, dict, str]]:
    out = []
    for it in items:
        for q in amounts_of(it["packet"]):
            edge = it["edges"].get(q["candidate_id"])
            if edge and edge["decision"] == "asserted" and edge["owner"] in OWNER_MAP:
                out.append((it, q, OWNER_MAP[edge["owner"]]))
    return out


def owner_fn(name: str):
    def make(it: dict, q: dict) -> dict[str, float]:
        inp, packet = it["record"], it["packet"]
        x = dict(candidate_x(q, inp, packet)) if name != "owner_only" else {}
        if name != "local":
            x.update({"own:" + k: v for k, v in owner_features(q, packet, mentions_for(packet, inp)).items()})
        return x
    return make


def nearest_rule(it: dict, q: dict) -> str:
    x = owner_features(q, it["packet"], mentions_for(it["packet"], it["record"]))
    kind = next(k.split(":", 1)[1] for k in x if k.startswith("nearest_left_clause:"))
    return {"target_like": "target", "other": "other", "role_other": "other"}.get(kind, "shared")


def actor_rule(q: dict, fallback: str) -> str:
    return {"target": "target", "other": "other"}.get(q.get("actor_status"), fallback)


def owner_metrics(pairs: list[tuple[str, str]]) -> dict:
    c = Counter(pairs)
    out = {"n": len(pairs), "accuracy": round(sum(v for (y, p), v in c.items() if y == p) / max(1, len(pairs)), 3)}
    f1s = []
    for k in CLASSES:
        tp = c[(k, k)]
        pred = sum(v for (y, p), v in c.items() if p == k)
        gold = sum(v for (y, p), v in c.items() if y == k)
        prec, rec = (tp / pred if pred else 0.0), (tp / gold if gold else 0.0)
        f = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f)
        out[k] = {"gold": gold, "pred": pred, "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f, 3)}
    out["macro_f1"] = round(sum(f1s) / len(f1s), 3)
    out["confusion"] = {f"{y}->{p}": v for (y, p), v in sorted(c.items())}
    return out


def part_owner(dev: list[dict]) -> dict:
    ex = owner_examples(dev)
    labels = Counter(y for _, _, y in ex)
    majority = labels.most_common(1)[0][0]
    report = {"examples": len(ex), "label_counts": dict(labels), "methods": {}}
    report["methods"]["majority"] = owner_metrics([(y, majority) for _, _, y in ex])
    resolved = [(y, q) for _, q, y in ex if q.get("actor_status") in {"target", "other"}]
    report["methods"]["packet_actor_hint"] = {
        **owner_metrics([(y, actor_rule(q, majority)) for _, q, y in ex]),
        "resolved_by_hint": len(resolved),
        "accuracy_on_resolved": round(sum(y == actor_rule(q, "") for y, q in resolved) / max(1, len(resolved)), 3)}
    report["methods"]["nearest_left_rule"] = owner_metrics([(y, nearest_rule(it, q)) for it, q, y in ex])
    for name in ("local", "owner_only", "local+owner"):
        fn = owner_fn(name)
        pairs = []
        for k in range(5):
            train = [e for e in ex if event_fold(e[0]["event"]) != k]
            held = [e for e in ex if event_fold(e[0]["event"]) == k]
            model = Softmax(CLASSES)
            model.fit([(fn(it, q), y) for it, q, y in train])
            for it, q, y in held:
                p = model.predict(fn(it, q))
                pairs.append((y, max(p, key=p.get)))
        report["methods"]["softmax/" + name] = owner_metrics(pairs)
    return report


# ---------- part 2: fields ----------

def silver_items(teacher: Path, originals: Path, silver: Path) -> list[dict]:
    out = []
    for rid, inp, packet, ref in load_records(teacher, originals, silver, {"train", "valid", "test"}):
        refs = {}
        for f in FIELDS:
            item = ref["reference_elements"]["amounts"][f]
            refs[f] = {"consensus": ("selected", amount_key(item["value"])) if present(item) else ("absent", None),
                       "candidate_ids": set()}
        multi = len(amounts_of(packet)) >= 2
        out.append({"id": rid, "record": inp, "packet": packet, "refs": refs, "edges": {},
                    "event": ref["metadata"].get("event_id") or rid, "split": ref["metadata"]["split"],
                    "group": "challenge" if multi else "random"})
    return out


def freeze_variant(dev: list[dict], name: str) -> tuple[Variant, object, dict]:
    v = Variant(*name.split("/"))
    oof = {}
    for k in range(5):
        train = [i for i in dev if event_fold(i["event"]) != k]
        held = [i for i in dev if event_fold(i["event"]) == k]
        oof.update(v.predict(held, v.fit(train)))
    return v, v.fit(dev), {f: pick_threshold(dev, f, oof) for f in FIELDS}


def evaluate_frozen(items: list[dict], frozen: dict, chain: dict) -> dict:
    out = {}
    for f in FIELDS:
        out[f] = {"frozen_chain": summarize(items, f, chain_decisions(items, chain, f))}
        for name, (v, model, thresholds) in frozen.items():
            out[f][name] = summarize(items, f, decide(v.predict(items, model), f, thresholds[f]))
    return out


def part_fields(dev: list[dict], h1: list[dict], h2: list[dict], chain: dict) -> dict:
    report = {"dev": {f: {"frozen_chain": summarize(dev, f, chain_decisions(dev, chain, f))} for f in FIELDS}}
    for name in FIELD_VARIANTS:
        decided, thresholds, _ = nested_cv(dev, Variant(*name.split("/")))
        for f in FIELDS:
            report["dev"][f][name] = summarize(dev, f, decided[f])
    dev_utility = {n: sum(report["dev"][f][n]["all"]["utility"] for f in FIELDS) for n in FIELD_VARIANTS}
    # Fixed before any holdout is scored: owner features are adopted only if they win on development.
    report["adopted_by_dev"] = max(FIELD_VARIANTS, key=lambda n: (dev_utility[n], -FIELD_VARIANTS.index(n)))
    report["dev_total_utility"] = dev_utility
    frozen = {n: freeze_variant(dev, n) for n in FIELD_VARIANTS}
    report["thresholds"] = {n: t for n, (_, _, t) in frozen.items()}
    report["H1_batch3"] = evaluate_frozen(h1, frozen, chain) if h1 else None
    report["H2_silver_all"] = evaluate_frozen(h2, frozen, chain)
    report["H2_silver_test40"] = evaluate_frozen([i for i in h2 if i["split"] == "test"], frozen, chain)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("part", choices=("owner", "fields"))
    ap.add_argument("--batch", type=Path, action="append", required=True, help="development batches, oldest first")
    ap.add_argument("--h1", type=Path)
    for name in ("teacher", "originals", "silver", "amount_artifact", "age_artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    # Every development batch is fully development here: their holdouts were spent in earlier rounds.
    dev = []
    for batch in args.batch:
        for it in load_batch(batch, batch / "ab" / "labels"):
            it["split"], it["batch"] = "train", batch.name
            dev.append(it)
    if args.part == "owner":
        result = {"scope": "event_5fold_cv_on_development", "dev_records": len(dev),
                  "reference": "A/B-agreed owner edges (model drafts, not human gold)", **part_owner(dev)}
    else:
        h1 = []
        if args.h1:
            h1 = [dict(it, split=HOLDOUT) for it in load_batch(args.h1, args.h1 / "ab" / "labels")]
        h2 = silver_items(args.teacher, args.originals, args.silver)
        chain = frozen_predictions([i["record"] for i in dev + h1], args.amount_artifact,
                                   args.age_artifact, args.engine_root)
        chain.update(silver_chain(h2, args))
        result = {"scope": "dev_cv_then_frozen_holdouts", "dev_records": len(dev), "h1_records": len(h1),
                  "h2_records": len(h2), "reference": {"dev/H1": "model_draft_majority", "H2": "L5 silver"},
                  **part_fields(dev, h1, h2, chain)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in result.items() if k in ("methods", "adopted_by_dev", "dev_total_utility")},
                     ensure_ascii=False)[:6000])


def silver_chain(h2: list[dict], args) -> dict:
    origins = {r["id"]: r["text_full"] for r in rows(args.originals)}
    records = [dict(i["record"], text_full=origins[i["id"]]) for i in h2]
    return frozen_predictions(records, args.amount_artifact, args.age_artifact, args.engine_root)


if __name__ == "__main__":
    main()
