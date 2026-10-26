"""Do kimi and Claude agree as the blind C voter on A/B-disagreeing pairs?

For every (record, amount, person) where A and B differ and both C voters have a
label: kimi == Claude rate, and which of A/B each one sides with. A high rate
means switching the C voter does not move the reference.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_relation_edges import label_path


def relations(path: Path) -> dict:
    d = json.loads(path.read_text("utf-8"))["annotation"]
    return {(a["candidate_id"], l["person_id"]): l["relation"] for a in d["amounts"] for l in a["links"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", nargs=2, action="append", required=True, metavar=("BATCHES", "LABELS"),
                    help="comma-separated batch dirs and their pair-label dir")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = {}
    for batches, labels in args.set:
        labels = Path(labels)
        c = Counter()
        for batch in batches.split(","):
            for r in rows(Path(batch) / "inputs.jsonl"):
                paths = {n: label_path(labels, r["id"], n) for n in ("bailian", "deepseek")}
                kimi, claude = labels / f"{r['id']}-kimi.json", labels / f"{r['id']}-claude.json"
                if None in paths.values() or not kimi.exists() or not claude.exists():
                    continue
                a, b = (relations(p) for p in paths.values())
                k, cl = relations(kimi), relations(claude)
                c["records"] += 1
                for key in a:
                    if a[key] == b.get(key) or key not in k or key not in cl:
                        continue
                    c["ab_disagree_pairs"] += 1
                    c["kimi_eq_claude"] += k[key] == cl[key]
                    c["kimi_sides_A" if k[key] == a[key] else "kimi_sides_B" if k[key] == b[key] else "kimi_third"] += 1
                    c["claude_sides_A" if cl[key] == a[key] else "claude_sides_B" if cl[key] == b[key] else "claude_third"] += 1
                    # Would the majority reference differ depending on which C voter is used?
                    c["same_majority"] += (k[key] in (a[key], b[key])) == (cl[key] in (a[key], b[key])) and (
                        k[key] == cl[key] or k[key] not in (a[key], b[key]))
        n = max(1, c["ab_disagree_pairs"])
        report[labels.parent.name] = {**c, "agreement": round(c["kimi_eq_claude"] / n, 3),
                                      "same_majority_rate": round(c["same_majority"] / n, 3)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
