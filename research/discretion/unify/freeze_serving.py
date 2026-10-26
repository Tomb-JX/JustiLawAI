"""Freeze the binding-service artifact directory (no new labels, no LLM calls).

Amount routes softmax/semantic and softmax/semantic_pair are fitted on the
development batches exactly as in the integration and review evaluation
(same data, features, OOF threshold rule); semantic_pair features come from the
out-of-fold pair-model predictions for training. Already validated artifacts
(frozen chain, age, participant count) are copied unchanged. A manifest records
every file's SHA256 and the code revision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import experiment_pair_integration as integ
from experiment_joint_amount_roles import FIELDS, Variant, pick_threshold
from experiment_pair_relations import load_pairs
from experiment_relation_edges import load_batch
from experiment_selective_binding import event_fold

ROUTES = ("softmax/semantic", "softmax/semantic_pair")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev-batch", type=Path, action="append", required=True)
    for name in ("dev_pair_labels", "dev_pair_oof", "amount_artifact", "age_artifact", "count_artifact", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = ap.parse_args()
    dev = []
    for b in args.dev_batch:
        for it in load_batch(b, b / "ab" / "labels"):
            it["split"] = "train"
            dev.append(it)
    integ.summarize_pairs(integ.read_preds(args.dev_pair_oof),
                          [it for b in args.dev_batch for it in load_pairs(b, args.dev_pair_labels, "dev")])
    models = {}
    for name in ROUTES:
        v = Variant(*name.split("/"))
        oof = {}
        for k in range(5):
            train = [i for i in dev if event_fold(i["event"]) != k]
            held = [i for i in dev if event_fold(i["event"]) == k]
            oof.update(v.predict(held, v.fit(train)))
        model = v.fit(dev)
        models[name] = {"thresholds": {f: pick_threshold(dev, f, oof) for f in FIELDS}, "softmax": model.export()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "amount_routes.json").write_text(json.dumps(models, ensure_ascii=False) + "\n", "utf-8")
    shutil.copy(args.amount_artifact, args.out / "frozen_chain_amounts.json")
    shutil.copy(args.age_artifact, args.out / "frozen_chain_age_count.json")
    shutil.copy(args.count_artifact, args.out / "participant_count.json")
    rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    files = {p.relative_to(args.out).as_posix(): sha(p) for p in sorted(args.out.rglob("*"))
             if p.is_file() and p.name != "MANIFEST.json"}
    manifest = {"service": "justilaw-binding", "version": "binding-v1", "code_revision": rev,
                "training": {"dev_batches": [b.name for b in args.dev_batch], "pair_oof": str(args.dev_pair_oof)},
                "thresholds": {n: m["thresholds"] for n, m in models.items()},
                "policy": "age/count auto; amounts bound only when frozen_chain, softmax/semantic and "
                          "softmax/semantic_pair agree, else unresolved for human review",
                "label_provenance": "model-draft majority + Claude review; not human gold", "files": files}
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"thresholds": manifest["thresholds"], "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
