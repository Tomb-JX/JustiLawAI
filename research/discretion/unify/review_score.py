"""Merge two blind review passes, emit an adjudication sheet, score methods on the result.

`merge`  : both passes agree on a field -> final; otherwise the field goes to
           ADJUDICATE.json with both answers and evidence (a person decides it
           in ADJUDICATED.json, same shape as one review answer per field).
`score`  : final answers vs each method and the model-vote reference, per field,
           split into the disagreement stratum and the random all-agree stratum.
Reviews are Claude reviews (two independent passes + adjudication), not human gold.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluate_relation_model_labels import amount_key

FIELDS = ("personal_stake", "onsite_stake_total")
STATUS = {"selected", "absent", "missing_candidate", "uncertain"}


def key_of(ans: dict, task: dict) -> str:
    """Comparable value: amount key for a selected candidate, else the status (missing keeps its raw)."""
    if ans["status"] == "selected":
        cand = next(c for c in task["amount_candidates"] if c["candidate_id"] == ans["candidate_id"])
        return amount_key(cand["normalized"])
    if ans["status"] == "missing_candidate":
        return "missing:" + (ans.get("raw") or "").strip()
    return ans["status"]


def load_answer(path: Path, task: dict) -> dict:
    a = json.loads(path.read_text("utf-8"))
    ids = {c["candidate_id"] for c in task["amount_candidates"]}
    for f in FIELDS:
        if a[f]["status"] not in STATUS or (a[f]["status"] == "selected" and a[f]["candidate_id"] not in ids):
            raise ValueError(f"invalid:{f}")
    return a


def merge(root: Path) -> None:
    final, sheet, problems = {}, {}, []
    for tpath in sorted((root / "tasks").glob("*.json")):
        rid = tpath.stem
        task = json.loads(tpath.read_text("utf-8"))
        try:
            p1, p2 = (load_answer(root / p / f"{rid}.json", task) for p in ("pass1", "pass2"))
        except Exception as exc:  # noqa: BLE001 - every problem is listed
            problems.append((rid, f"{type(exc).__name__}: {exc}"))
            continue
        final[rid] = {}
        for f in FIELDS:
            k1, k2 = key_of(p1[f], task), key_of(p2[f], task)
            if k1 == k2:
                final[rid][f] = {"key": k1, "source": "agreed", "answer": p1[f]}
            else:
                sheet.setdefault(rid, {"target": task["target"]})[f] = {"pass1": p1[f] | {"key": k1},
                                                                         "pass2": p2[f] | {"key": k2},
                                                                         "notes": [p1.get("notes"), p2.get("notes")]}
    (root / "AGREED.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), "utf-8")
    (root / "ADJUDICATE.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=1), "utf-8")
    n = sum(len(v) - 1 for v in sheet.values())
    print(json.dumps({"records": len(final), "fields_agreed": sum(len(v) for v in final.values()),
                      "fields_to_adjudicate": n, "problems": problems[:5], "n_problems": len(problems)},
                     ensure_ascii=False))


def score(root: Path, out: Path) -> None:
    final = json.loads((root / "AGREED.json").read_text("utf-8"))
    adjudicated = json.loads((root / "ADJUDICATED.json").read_text("utf-8")) if (root / "ADJUDICATED.json").exists() else {}
    key = json.loads((root / "PRIVATE-key.json").read_text("utf-8"))
    for rid, fields in adjudicated.items():
        task = json.loads((root / "tasks" / f"{rid}.json").read_text("utf-8"))
        for f, ans in fields.items():
            final.setdefault(rid, {})[f] = {"key": key_of(ans, task), "source": "adjudicated", "answer": ans}
    methods = list(next(iter(key["rows"].values()))["methods"])
    report = {"reviewed_records": len(final), "sources": dict(Counter(v["source"] for r in final.values()
                                                                       for v in r.values())),
              "gold_status": {f: dict(Counter(final[r][f]["key"].split(":")[0] for r in final if f in final[r]))
                              for f in FIELDS}, "strata": {}}
    for stratum in ("all", "disagree", "random_agree"):
        rids = [r for r in final if stratum == "all" or key["selection"][r] == stratum]
        block = {}
        for f in FIELDS:
            for name in methods + ["model_vote"]:
                c = Counter()
                for r in rids:
                    if f not in final[r]:
                        continue
                    gold = final[r][f]["key"]
                    row = key["rows"][r]
                    if name != "model_vote":
                        pred = row["methods"][name][f]
                    else:
                        vote = row["model_vote"][f]
                        pred = ("unresolved" if vote is None or vote[0] == "uncertain"
                                else vote[1] if vote[0] == "selected" else None)
                    if gold == "uncertain":
                        c["gold_uncertain"] += 1
                    elif pred == "unresolved":
                        c["reference_unresolved"] += 1
                    elif gold.startswith("amount:"):
                        c["tp" if pred == gold else "abstain_on_positive" if pred is None else "wrong_value"] += 1
                    elif gold.startswith("missing:"):
                        c["unreachable_abstain" if pred is None else "wrong_value"] += 1
                    else:
                        c["tn" if pred is None else "output_on_absent"] += 1
                c["utility"] = c["tp"] - 2 * (c["wrong_value"] + c["output_on_absent"])
                outputs = c["tp"] + c["wrong_value"] + c["output_on_absent"]
                c["precision"] = round(c["tp"] / outputs, 3) if outputs else None
                block.setdefault(f, {})[name] = dict(c)
        report["strata"][stratum] = {"records": len(rids), **block}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["sources"]), json.dumps(report["gold_status"], ensure_ascii=False))
    for f in FIELDS:
        for name, c in report["strata"]["all"][f].items():
            print(f, name, {k: c.get(k, 0) for k in ("tp", "wrong_value", "output_on_absent", "abstain_on_positive",
                                                     "unreachable_abstain", "utility", "precision")})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("merge", "score"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    merge(args.root) if args.stage == "merge" else score(args.root, args.out)


if __name__ == "__main__":
    main()
