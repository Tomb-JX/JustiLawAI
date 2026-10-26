"""Joint amount-role decision vs two independent field scorers.

Every resolved amount is one node with a role in {personal, onsite, both, other}.
Roles come from the model-majority field references: a node selected for both
fields is `both`; same-value rivals of a selected value stay unlabeled.

Variants share candidates, features and folds and differ in one respect:
  independent   two binary logistic scorers (personal / onsite), each argmax + NIL
  softmax       one 4-way softmax per node, each field argmax + NIL, no competition
  softmax_joint same softmax; a node claimed by both fields keeps only its most
                probable role unless `both` is that role, the other field takes its
                next-best node (soft competition, no hard exclusivity)
Feature ablation: local (existing candidate features) vs local + quantity semantics
(cap/per-unit/gain/total/seized/carried/loss/transfer cues) + numeric part-whole
relations among the record's amounts.

Development = all of batch 1 + batch 2 train/calibration, nested event CV.
`holdout` reads batch-2 model_draft_holdout once, after `freeze`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

from evaluate_relation_model_labels import amount_key, frozen_predictions, score
from experiment_candidate_nil import candidate_x
from experiment_relation_edges import (GRID, amounts_of, chain_decisions, f1, field_rows,
                                       load_batch, utility)
from experiment_selective_binding import event_fold
from experiment_silver_supervised_pipeline import SparseLogistic
from ownership import owner_features, person_mentions

ROLES = ("personal", "onsite", "both", "other")
FIELD_ROLES = {"personal_stake": ("personal", "both"), "onsite_stake_total": ("onsite", "both")}
FIELDS = tuple(FIELD_ROLES)
HOLDOUT = "model_draft_holdout"
DECODERS = ("independent", "softmax", "softmax_joint")
FEATURES = ("local", "semantic")
CUES = {
    "cap": ("超过", "不超过", "没有超过", "以上", "以下", "封顶", "最高", "最多", "不足"),
    "per_unit": ("每局", "单局", "每人", "每次", "每把", "一番", "底注", "为底", "自摸", "每注"),
    "gain": ("获利", "渔利", "抽头", "头子", "台费", "提成", "好处费", "盈利", "抽水"),
    "total": ("共计", "累计", "总计", "合计", "总额", "流水", "现场赌资", "共"),
    "seized": ("查获", "缴获", "收缴", "扣押", "查扣"),
    "carried": ("持有", "携带", "随身", "身上", "其中"),
    "loss_win": ("输掉", "输了", "赢了", "输", "赢"),
    "transfer": ("转账", "充值", "提现", "购买", "下注", "押注"),
}


# ---------- features ----------

def context(q: dict, packet: dict, left: int = 14, right: int = 10) -> tuple[str, str]:
    view = next(v for v in packet["visible_spans"] if v["span_id"] == q["source_span_id"])
    a, b = q["start"] - view["start"], q["end"] - view["start"]
    return view["quote"][max(0, a - left):a], view["quote"][b:b + right]


def semantic(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    x = candidate_x(q, inp, packet)
    left, right = context(q, packet)
    for name, cues in CUES.items():
        if any(c in left for c in cues):
            x["cueL:" + name] = 1.0
        if any(c in right for c in cues):
            x["cueR:" + name] = 1.0
    x["approx:" + str(q["engine_projection"].get("max") not in (None, q["engine_projection"]["min"]))] = 1.0
    pool = amounts_of(packet)
    value = float(q["engine_projection"]["min"])
    vals = [float(a["engine_projection"]["min"]) for a in pool if a["candidate_id"] != q["candidate_id"]][:8]
    x["n_amounts:" + str(min(len(pool), 4))] = 1.0
    if vals:
        x["is_max"] = float(value > max(vals))
        x["is_sum_of_others"] = float(any(abs(sum(c) - value) < 0.5 for k in (2, 3) for c in combinations(vals, k)))
        x["is_part_of_sum"] = float(any(abs(sum(c) + value - t) < 0.5 for t in vals for k in (1, 2)
                                        for c in combinations([v for v in vals if v != t], k)))
        x["same_value_elsewhere"] = float(value in vals)
    return x


_MENTIONS: dict[tuple, list] = {}


def mentions_for(packet: dict, inp: dict) -> list[dict]:
    key = (packet["source"]["text_sha256"], inp["target"], tuple(inp.get("aliases") or ()))
    if key not in _MENTIONS:
        _MENTIONS[key] = person_mentions(packet, inp)
    return _MENTIONS[key]


def semantic_owner(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    x = semantic(q, inp, packet)
    x.update({"own:" + k: v for k, v in owner_features(q, packet, mentions_for(packet, inp)).items()})
    return x


FEATURE_FN = {"local": candidate_x, "semantic": semantic, "semantic_owner": semantic_owner}


# ---------- labels ----------

def node_roles(it: dict) -> dict[str, str | None]:
    refs = {f: it["refs"][f] for f in FIELDS}
    if any(r["consensus"] is None or r["consensus"][0] not in {"selected", "absent"} for r in refs.values()):
        return {}
    out = {}
    for q in amounts_of(it["packet"]):
        cid, key = q["candidate_id"], amount_key(q["engine_projection"])
        hit = {f: cid in refs[f]["candidate_ids"] for f in FIELDS}
        rival = any(refs[f]["consensus"][0] == "selected" and not hit[f] and key == refs[f]["consensus"][1]
                    for f in FIELDS)
        if rival:
            out[cid] = None
        elif hit["personal_stake"] and hit["onsite_stake_total"]:
            out[cid] = "both"
        else:
            out[cid] = "personal" if hit["personal_stake"] else "onsite" if hit["onsite_stake_total"] else "other"
    return out


# ---------- learners ----------

class Softmax:
    """Class-balanced multinomial logistic regression (dense numpy over a training vocabulary)."""

    def __init__(self, classes: tuple[str, ...] = ROLES) -> None:
        self.classes = tuple(classes)
        self.vocab: dict[str, int] = {}
        self.W = None
        self.b = None

    def matrix(self, xs: list[dict]):
        X = np.zeros((len(xs), len(self.vocab)), dtype=np.float64)
        for i, x in enumerate(xs):
            for key, value in x.items():
                j = self.vocab.get(key)
                if j is not None:
                    X[i, j] = value
        return X

    def fit(self, examples: list[tuple[dict, str]], *, epochs: int = 220, learning_rate: float = 0.7,
            l2: float = 0.003) -> None:
        self.vocab = {k: i for i, k in enumerate(sorted({k for x, _ in examples for k in x}))}
        X = self.matrix([x for x, _ in examples])
        y = np.array([self.classes.index(r) for _, r in examples])
        Y = np.eye(len(self.classes))[y]
        counts = Y.sum(axis=0)
        # Class-balanced loss, like the binary learners' positive repetition.
        w = (len(y) / (len(self.classes) * np.maximum(counts, 1)))[y] * (counts[y] > 0)
        norm = w.sum()
        self.W = np.zeros((X.shape[1], len(self.classes)))
        self.b = np.log((counts + 0.5) / (len(y) + 2))
        for _ in range(epochs):
            P = self._probs(X)
            G = (P - Y) * w[:, None]
            self.W -= learning_rate * (X.T @ G / norm + l2 * self.W)
            self.b -= learning_rate * G.sum(axis=0) / norm

    def _probs(self, X):
        Z = np.clip(X @ self.W + self.b, -30, 30)
        Z -= Z.max(axis=1, keepdims=True)
        E = np.exp(Z)
        return E / E.sum(axis=1, keepdims=True)

    def predict(self, x: dict) -> dict[str, float]:
        p = self._probs(self.matrix([x]))[0]
        return dict(zip(self.classes, p.tolist()))

    def export(self) -> dict:
        return {"classes": list(self.classes), "vocab": list(self.vocab), "W": self.W.tolist(), "b": self.b.tolist()}

    @classmethod
    def load(cls, spec: dict) -> "Softmax":
        m = cls(tuple(spec.get("classes") or ROLES))
        m.vocab = {k: i for i, k in enumerate(spec["vocab"])}
        m.W, m.b = np.array(spec["W"]), np.array(spec["b"])
        return m

def balanced_binary(examples: list[tuple[dict, bool]]) -> SparseLogistic:
    pos = [x for x, y in examples if y]
    neg = [x for x, y in examples if not y]
    if not pos or not neg:
        raise ValueError("training_class_missing")
    model = SparseLogistic()
    model.fit(examples + [(x, True) for _ in range(max(1, round(len(neg) / len(pos))) - 1) for x in pos])
    return model


class Variant:
    def __init__(self, decoder: str, features: str):
        self.decoder, self.features = decoder, features
        self.fn = FEATURE_FN[features]

    @property
    def name(self) -> str:
        return f"{self.decoder}/{self.features}"

    def examples(self, items: list[dict]) -> list[tuple[dict, str]]:
        out = []
        for it in items:
            roles = node_roles(it)
            for q in amounts_of(it["packet"]):
                role = roles.get(q["candidate_id"])
                if role is not None:
                    out.append((self.fn(q, it["record"], it["packet"]), role))
        return out

    def fit(self, items: list[dict]):
        ex = self.examples(items)
        if self.decoder == "independent":
            return {f: balanced_binary([(x, y in FIELD_ROLES[f]) for x, y in ex]) for f in FIELDS}
        model = Softmax()
        model.fit(ex)
        return model

    def node_scores(self, it: dict, model) -> list[tuple[dict, dict[str, float]]]:
        """Per node: field scores, and role probabilities (softmax only)."""
        out = []
        for q in amounts_of(it["packet"]):
            x = self.fn(q, it["record"], it["packet"])
            if self.decoder == "independent":
                out.append((q, {f: model[f].predict(x) for f in FIELDS}, None))
            else:
                p = model.predict(x)
                out.append((q, {f: sum(p[r] for r in FIELD_ROLES[f]) for f in FIELDS}, p))
        return out

    def predict(self, items: list[dict], model) -> dict[str, dict[str, tuple[float, str | None, str | None]]]:
        """rid -> field -> (score, value_key, candidate_id) before the NIL threshold."""
        out = {}
        for it in items:
            nodes = self.node_scores(it, model)
            pick = {}
            for f in FIELDS:
                ranked = sorted(nodes, key=lambda n: (-n[1][f], n[0]["start"]))
                pick[f] = ranked
            chosen = {f: pick[f][0] if pick[f] else None for f in FIELDS}
            if (self.decoder == "softmax_joint" and len(nodes) > 1 and chosen["personal_stake"] is not None
                    and chosen["personal_stake"][0]["candidate_id"] == chosen["onsite_stake_total"][0]["candidate_id"]):
                probs = chosen["personal_stake"][2]
                role = max(("personal", "onsite", "both"), key=lambda r: probs[r])
                if role != "both":
                    loser = "onsite_stake_total" if role == "personal" else "personal_stake"
                    chosen[loser] = pick[loser][1]
            out[it["id"]] = {f: ((n[1][f], amount_key(n[0]["engine_projection"]), n[0]["candidate_id"])
                                 if n else (0.0, None, None)) for f, n in chosen.items()}
        return out


# ---------- protocol ----------

def decide(preds: dict, field: str, threshold: float) -> dict:
    return {rid: (p[field][1] if p[field][0] >= threshold else None) for rid, p in preds.items()}


def pick_threshold(items: list[dict], field: str, preds: dict) -> float:
    def key(t):
        m = score(field_rows(items, field, decide(preds, field, t)))
        return (utility(m), f1(m), t)
    return max(GRID, key=key)


def summarize(items: list[dict], field: str, decided: dict) -> dict:
    out = {"all": score(field_rows(items, field, decided))}
    out["all"]["f1"] = round(f1(out["all"]), 3)
    out["all"]["utility"] = utility(out["all"])
    for g in ("challenge", "random"):
        out[g] = score(field_rows([i for i in items if i["group"] == g], field, decided))
    # Joint error of interest: the same amount output for both fields when the reference says otherwise.
    return out


def double_claims(items: list[dict], preds: dict, thresholds: dict) -> Counter:
    c = Counter()
    for it in items:
        p = preds[it["id"]]
        picks = {f: p[f][2] for f in FIELDS if p[f][0] >= thresholds[f]}
        if len(picks) == 2 and picks["personal_stake"] == picks["onsite_stake_total"]:
            roles = node_roles(it)
            c["same_node_both_fields"] += 1
            c["of_which_reference_both"] += roles.get(picks["personal_stake"]) == "both"
    return c


def nested_cv(dev: list[dict], variant: Variant) -> tuple[dict, dict, Counter]:
    decided = {f: {} for f in FIELDS}
    thresholds = {f: [] for f in FIELDS}
    claims = Counter()
    for k in range(5):
        train = [i for i in dev if event_fold(i["event"]) != k]
        held = [i for i in dev if event_fold(i["event"]) == k]
        inner = {}
        for j in range(5):
            fit_part = [i for i in train if event_fold(i["event"] + "#inner") != j]
            part = [i for i in train if event_fold(i["event"] + "#inner") == j]
            if part:
                inner.update(variant.predict(part, variant.fit(fit_part)))
        t = {f: pick_threshold(train, f, inner) for f in FIELDS}
        out = variant.predict(held, variant.fit(train))
        for f in FIELDS:
            thresholds[f].append(t[f])
            decided[f].update(decide(out, f, t[f]))
        claims.update(double_claims(held, out, t))
    return decided, thresholds, claims


def load_items(batches: list[Path]) -> list[dict]:
    items = []
    for i, batch in enumerate(batches):
        for it in load_batch(batch, batch / "ab" / "labels"):
            # Earlier batches' holdouts are spent; only the last batch keeps a sealed holdout.
            if i < len(batches) - 1:
                it["split"] = "train"
            it["batch"] = batch.name
            items.append(it)
    if len({it["event"] for it in items}) != len(items):
        raise ValueError("event_id_collision_across_batches")
    return items


def develop(items: list[dict], chain: dict) -> dict:
    dev = [i for i in items if i["split"] != HOLDOUT]
    report = {"scope": "nested_event_cv", "holdout_read": False, "dev_records": len(dev),
              "reference": "model_draft_majority_not_human_gold",
              "role_label_counts": dict(Counter(r for it in dev for r in node_roles(it).values())),
              "fields": {f: {"frozen_chain": summarize(dev, f, chain_decisions(dev, chain, f))} for f in FIELDS},
              "double_claims": {}, "thresholds": {}}
    for features in FEATURES:
        for decoder in DECODERS:
            v = Variant(decoder, features)
            decided, thresholds, claims = nested_cv(dev, v)
            for f in FIELDS:
                report["fields"][f][v.name] = summarize(dev, f, decided[f])
            report["double_claims"][v.name] = dict(claims)
            report["thresholds"][v.name] = thresholds
    return report


def choose(report: dict) -> dict:
    """Per field, highest utility; the frozen chain is first so ties keep it."""
    out = {}
    for f, variants in report["fields"].items():
        order = list(variants)
        out[f] = max(order, key=lambda n: (variants[n]["all"]["utility"], -order.index(n)))
    return out


def freeze(items: list[dict], report: dict, batch_hashes: dict) -> dict:
    dev = [i for i in items if i["split"] != HOLDOUT]
    choice = choose(report)
    artifact = {"version": "joint-amount-roles-1", "batch_inputs_sha256": batch_hashes, "chosen": choice,
                "selection_rule": "utility = tp - 2*(wrong_value + output_on_absent); frozen chain first",
                "holdout_read_before_freeze": False, "models": {}}
    for name in sorted({c for c in choice.values() if c != "frozen_chain"}):
        v = Variant(*name.split("/"))
        oof = {}
        for k in range(5):
            train = [i for i in dev if event_fold(i["event"]) != k]
            held = [i for i in dev if event_fold(i["event"]) == k]
            oof.update(v.predict(held, v.fit(train)))
        model = v.fit(dev)
        artifact["models"][name] = {
            "thresholds": {f: pick_threshold(dev, f, oof) for f in FIELDS},
            "weights": ({f: {"w": dict(m.weights), "b": m.bias} for f, m in model.items()}
                        if v.decoder == "independent" else
                        model.export())}
    return artifact


def restore(name: str, spec: dict):
    v = Variant(*name.split("/"))
    if v.decoder == "independent":
        model = {}
        for f, d in spec["weights"].items():
            m = SparseLogistic()
            m.weights.update(d["w"])
            m.bias = d["b"]
            model[f] = m
        return v, model
    return v, Softmax.load(spec["weights"])


def holdout(items: list[dict], artifact: dict, chain: dict) -> dict:
    test = [i for i in items if i["split"] == HOLDOUT]
    report = {"scope": "frozen_holdout_once", "records": len(test), "chosen": artifact["chosen"],
              "reference": "model_draft_majority_not_human_gold",
              "fields": {f: {"frozen_chain": summarize(test, f, chain_decisions(test, chain, f))} for f in FIELDS},
              "double_claims": {}}
    for name, spec in artifact["models"].items():
        v, model = restore(name, spec)
        preds = v.predict(test, model)
        for f in FIELDS:
            report["fields"][f][name] = summarize(test, f, decide(preds, f, spec["thresholds"][f]))
        report["double_claims"][name] = dict(double_claims(test, preds, spec["thresholds"]))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("develop", "freeze", "holdout"))
    ap.add_argument("--batch", type=Path, action="append", required=True, help="oldest first; last keeps holdout")
    for name in ("amount_artifact", "age_artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--artifact", type=Path)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    items = load_items(args.batch)
    hashes = {b.name: hashlib.sha256((b / "inputs.jsonl").read_bytes()).hexdigest() for b in args.batch}
    chain = frozen_predictions([i["record"] for i in items], args.amount_artifact, args.age_artifact,
                               args.engine_root)
    if args.stage == "develop":
        result = develop(items, chain)
    elif args.stage == "freeze":
        result = freeze(items, json.loads(args.artifact.read_text("utf-8")), hashes)
    else:
        artifact = json.loads(args.artifact.read_text("utf-8"))
        if artifact["batch_inputs_sha256"] != hashes:
            raise ValueError("frozen_batch_hash_mismatch")
        result = holdout(items, artifact, chain)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    brief = result.get("chosen") or {}
    print(json.dumps({"chosen": brief, "fields": {f: {n: {k: v["all"].get(k, 0) for k in
                                                          ("tp", "wrong_value", "output_on_absent",
                                                           "abstain_on_positive", "utility")}
                                                      for n, v in vs.items()}
                                                  for f, vs in result.get("fields", {}).items()},
                      "double_claims": result.get("double_claims")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
