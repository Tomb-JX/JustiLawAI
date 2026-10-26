"""Does the person–amount pair model improve ownership and fields?

1. Ownership: per amount, the highest holder probability (holds + each_share)
   among target-like vs other persons gives target / other / shared (< 0.5).
   Compared on identical A/B-agreed owner edges with the earlier 3-way owner
   softmax (local + ownership features, event-level 5-fold CV).
2. Fields: the frozen-family 4-way role model (softmax/semantic) vs the same with
   bucketed pair-model holder probabilities. Development uses out-of-fold pair
   predictions (stacking caveat: a training item's feature may come from a model
   that saw the held-out fold); the holdout uses the final pair model only.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import experiment_joint_amount_roles as joint
from evaluate_relation_model_labels import frozen_predictions
from experiment_joint_amount_roles import FIELDS, Softmax, Variant, decide, nested_cv, pick_threshold, summarize
from experiment_ownership import CLASSES as OWNER_CLASSES, owner_examples, owner_fn, owner_metrics
from experiment_pair_relations import load_pairs
from experiment_relation_edges import chain_decisions, load_batch
from experiment_selective_binding import event_fold
from ownership import owner_class

PAIR_PROBS: dict[tuple[str, str], dict] = {}   # (record id, amount id) -> holder summary


def summarize_pairs(pred_rows: list[dict], items: list[dict]) -> None:
    kinds = {(it["id"], p["person_id"]): p["kind"] for it in items for p in it["persons"]}
    agg: dict[tuple[str, str], Counter] = {}
    for r in pred_rows:
        holder = r["probs"]["holds"] + r["probs"]["each_share"]
        side = "target" if owner_class(kinds.get((r["id"], r["p"]), "")) == "target_like" else "other"
        c = agg.setdefault((r["id"], r["q"]), Counter())
        c[side + "_hold"] = max(c[side + "_hold"], holder)
        c[side + "_gives"] = max(c[side + "_gives"], r["probs"]["gives"])
        c[side + "_receives"] = max(c[side + "_receives"], r["probs"]["receives"])
    PAIR_PROBS.update({k: dict(v) for k, v in agg.items()})


def bucket(v: float) -> str:
    return "hi" if v >= 0.8 else "mid" if v >= 0.5 else "low" if v >= 0.2 else "none"


def pair_owner(rid: str, qid: str) -> str:
    s = PAIR_PROBS.get((rid, qid), {})
    t, o = s.get("target_hold", 0.0), s.get("other_hold", 0.0)
    if max(t, o) < 0.5:
        return "shared"
    return "target" if t >= o else "other"


def semantic_pair(q: dict, inp: dict, packet: dict) -> dict[str, float]:
    x = joint.semantic(q, inp, packet)
    s = PAIR_PROBS.get((inp["id"], q["candidate_id"]))
    if s is None:
        x["pair:missing"] = 1.0
        return x
    for key in ("target_hold", "other_hold", "target_gives", "other_gives", "target_receives", "other_receives"):
        x[f"pair:{key}:{bucket(s.get(key, 0.0))}"] = 1.0
    x["pair:owner:" + pair_owner(inp["id"], q["candidate_id"])] = 1.0
    return x


joint.FEATURE_FN["semantic_pair"] = semantic_pair


def ownership_compare(dev: list[dict]) -> dict:
    ex = owner_examples(dev)
    fn = owner_fn("local+owner")
    pairs_softmax = []
    for k in range(5):
        train = [e for e in ex if event_fold(e[0]["event"]) != k]
        held = [e for e in ex if event_fold(e[0]["event"]) == k]
        model = Softmax(OWNER_CLASSES)
        model.fit([(fn(it, q), y) for it, q, y in train])
        for it, q, y in held:
            p = model.predict(fn(it, q))
            pairs_softmax.append((y, max(p, key=p.get)))
    covered = [(it, q, y) for it, q, y in ex if (it["id"], q["candidate_id"]) in PAIR_PROBS]
    return {"examples": len(ex), "covered_by_pair_model": len(covered),
            "owner_softmax_local+owner": owner_metrics(pairs_softmax),
            "pair_model_derived": owner_metrics([(y, pair_owner(it["id"], q["candidate_id"])) for it, q, y in ex])}


def read_preds(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def freeze_and_score(dev: list[dict], test: list[dict], name: str, chain: dict) -> dict:
    v = Variant(*name.split("/"))
    oof = {}
    for k in range(5):
        train = [i for i in dev if event_fold(i["event"]) != k]
        held = [i for i in dev if event_fold(i["event"]) == k]
        oof.update(v.predict(held, v.fit(train)))
    model = v.fit(dev)
    thresholds = {f: pick_threshold(dev, f, oof) for f in FIELDS}
    preds = v.predict(test, model)
    return {"thresholds": thresholds, **{f: summarize(test, f, decide(preds, f, thresholds[f])) for f in FIELDS}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev-batch", type=Path, action="append", required=True)
    ap.add_argument("--dev-pair-labels", type=Path, required=True)
    ap.add_argument("--dev-pair-oof", type=Path, required=True)
    ap.add_argument("--test-batch", type=Path, required=True)
    ap.add_argument("--test-pair-labels", type=Path, required=True)
    ap.add_argument("--test-pair-preds", type=Path, required=True)
    for name in ("amount_artifact", "age_artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--test-arbiter", default="kimi", help="C voter for holdout pair labels (kimi or claude)")
    args = ap.parse_args()
    dev = []
    for b in args.dev_batch:
        for it in load_batch(b, b / "ab" / "labels"):
            it["split"], it["batch"] = "train", b.name
            dev.append(it)
    test = [dict(it, split=joint.HOLDOUT) for it in load_batch(args.test_batch, args.test_batch / "ab" / "labels")]
    # Person proposals for the pair features come from the pair-label files (same recogniser version).
    pair_items = [it for b in args.dev_batch for it in load_pairs(b, args.dev_pair_labels, "dev")]
    test_pair_items = load_pairs(args.test_batch, args.test_pair_labels, "holdout", require_labels=False,
                                arbiter=args.test_arbiter)
    summarize_pairs(read_preds(args.dev_pair_oof), pair_items)
    summarize_pairs(read_preds(args.test_pair_preds), test_pair_items)
    chain = frozen_predictions([i["record"] for i in dev + test], args.amount_artifact, args.age_artifact,
                               args.engine_root)
    report = {"reference": "model-draft majority (not human gold)", "dev_records": len(dev),
              "test_records": len(test), "ownership_dev": ownership_compare(dev),
              "ownership_test": {"pair_model_derived": owner_metrics(
                  [(y, pair_owner(it["id"], q["candidate_id"])) for it, q, y in owner_examples(test)])},
              "fields_dev": {f: {"frozen_chain": summarize(dev, f, chain_decisions(dev, chain, f))} for f in FIELDS}}
    names = ("softmax/semantic", "softmax/semantic_pair")
    for name in names:
        decided, _, _ = nested_cv(dev, Variant(*name.split("/")))
        for f in FIELDS:
            report["fields_dev"][f][name] = summarize(dev, f, decided[f])
    utility = {n: sum(report["fields_dev"][f][n]["all"]["utility"] for f in FIELDS) for n in names}
    report["dev_total_utility"] = utility
    report["adopted_by_dev"] = max(names, key=lambda n: (utility[n], -names.index(n)))
    report["fields_test"] = {"frozen_chain": {f: summarize(test, f, chain_decisions(test, chain, f)) for f in FIELDS},
                             **{n: freeze_and_score(dev, test, n, chain) for n in names}}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    brief = {"ownership_dev": {k: (v if isinstance(v, int) else {m: v[m] for m in ("accuracy", "macro_f1")} |
                                   {"other": v["other"]}) for k, v in report["ownership_dev"].items()},
             "ownership_test": {k: {m: v[m] for m in ("n", "accuracy", "macro_f1")} | {"other": v["other"]}
                                for k, v in report["ownership_test"].items()},
             "dev_total_utility": utility, "adopted_by_dev": report["adopted_by_dev"]}
    print(json.dumps(brief, ensure_ascii=False))


if __name__ == "__main__":
    main()
