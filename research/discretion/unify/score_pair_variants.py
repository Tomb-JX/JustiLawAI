"""Score pair-model variants: dev OOF, and holdout against final labels in two scopes.

`ab_agreed` uses only pairs where A and B agree (high-confidence reference);
`with_c` adds strict-majority pairs decided with the C vote (kimi, else Claude).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiment_pair_relations import CLASSES, load_pairs, metrics


def preds(path: Path) -> dict:
    return {(r["id"], r["q"], r["p"]): r["pred"] for r in
            (json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--variants", default="base,topic,topic_subj")
    ap.add_argument("--test-batch", type=Path, required=True)
    ap.add_argument("--test-labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    scopes = {"ab_agreed": load_pairs(args.test_batch, args.test_labels, "holdout", arbiter="__none__"),
              "with_c": load_pairs(args.test_batch, args.test_labels, "holdout", arbiter="kimi")}
    report = {}
    for v in args.variants.split(","):
        d = args.models / f"v2-{v}"
        oof = [json.loads(l) for l in (d / "oof.jsonl").read_text("utf-8").splitlines() if l.strip()]
        out = {"dev_oof": metrics([(r["label"], r["pred"]) for r in oof if r["label"] in CLASSES])}
        hp = preds(d / "holdout.jsonl")
        for scope, items in scopes.items():
            pairs = [(lab, hp[(it["id"], q, p)]) for it in items for (q, p), lab in it["pairs"].items()
                     if lab in CLASSES and (it["id"], q, p) in hp]
            out["H3_" + scope] = metrics(pairs)
        report[v] = out
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for v, o in report.items():
        print(v, {k: {m: o[k][m] for m in ("n", "accuracy", "macro_f1", "holder_edge")} for k in o})


if __name__ == "__main__":
    main()
