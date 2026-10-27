"""Apply the labeling-function library to a record set and report LF quality (aggregates only).

For each set: votes-<name>.jsonl, one row per (record, amount candidate) with every LF's vote.
With --ref (dev only, per plan §1.3) the candidate gold is derived from the record reference by
value key: the referenced value is YES, absent or another value is NO, uncertain or an
unnormalisable missing value is left out. The report gives per LF: votes, coverage, accuracy
(Wilson 95% low), YES precision and conflict rate, and the rule-abstain surface (criteria 4).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import labeling_functions as L
from review4 import wilson_low
from score_onsite_caliber import reference as onsite_reference
from score_personal_attribution import reference as personal_reference

MIN_VOTES, MIN_ACCURACY = 20, 0.60


def gold_of(ref: dict[str, dict[str, str]], row: dict, task: str) -> int | None:
    k = ref.get(task, {}).get(row["id"])
    if k is None or k == "uncertain" or k.startswith("missing:"):
        return None
    return L.YES if k == row["value"] else L.NO


def _acc(pairs: list[tuple[int, int]]) -> dict | None:
    """Accuracy on the rule-abstain candidates (the surface the end model must generalise to)."""
    if not pairs:
        return None
    ok = sum(a == b for a, b in pairs)
    return {"n": len(pairs), "accuracy": round(ok / len(pairs), 3), "wilson_low95": round(wilson_low(ok, len(pairs)), 3)}


def report(rows: list[dict], lfs: list[L.LF], ref: dict | None) -> dict:
    out = {"candidates": len(rows), "records": len({r["id"] for r in rows}), "lfs": {}}
    for task in L.TASKS:
        names = [n for n, t, _g, _f in lfs if t == task]
        rule = [n for n, t, g, _f in lfs if t == task and g == "rule"]
        other = [n for n, t, g, _f in lfs if t == task and g not in ("rule", "llm")]
        blind = [r for r in rows if all(r["votes"][n] == L.ABSTAIN for n in rule)]
        out[f"{task}_rule_abstain"] = {"share": round(len(blind) / len(rows), 3) if rows else None,
                                       "with_structure_or_model_vote": round(
                                           sum(any(r["votes"][n] != L.ABSTAIN for n in other) for r in blind)
                                           / len(blind), 3) if blind else None}
        if ref:
            gold = [gold_of(ref, r, task) for r in rows]
            out[f"{task}_gold"] = dict(Counter("yes" if g == 1 else "no" if g == 0 else "none" for g in gold))
        for n in names:
            v = [r["votes"][n] for r in rows]
            cast = [k for k, x in enumerate(v) if x != L.ABSTAIN]
            conflict = sum(any(rows[k]["votes"][m] not in (L.ABSTAIN, v[k]) for m in names if m != n) for k in cast)
            s = {"task": task, "group": next(g for m, _t, g, _f in lfs if m == n), "votes": len(cast),
                 "yes_votes": sum(v[k] == L.YES for k in cast),
                 "coverage": round(len(cast) / len(rows), 3) if rows else None,
                 "conflict": round(conflict / len(cast), 3) if cast else None}
            if ref:
                scored = [(v[k], gold[k]) for k in cast if gold[k] is not None]
                ok = sum(a == b for a, b in scored)
                yes = [(a, b) for a, b in scored if a == L.YES]
                s.update(scored=len(scored), accuracy=round(ok / len(scored), 3) if scored else None,
                         wilson_low95=round(wilson_low(ok, len(scored)), 3) if scored else None,
                         yes_precision=round(sum(b == L.YES for _a, b in yes) / len(yes), 3) if yes else None,
                         accuracy_rule_abstain=_acc([(v[k], gold[k]) for k in cast if gold[k] is not None
                                                     and all(rows[k]["votes"][m] == L.ABSTAIN for m in rule)]),
                         verdict=("drop" if len(scored) >= MIN_VOTES and ok / len(scored) < MIN_ACCURACY
                                  else "low_support" if len(scored) < MIN_VOTES else "keep"))
            out["lfs"][n] = s
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--v1-run", type=Path)
    ap.add_argument("--llm-labels", type=Path, help="run_review_llm labels/ directory")
    ap.add_argument("--ref", type=Path, help="dev review root with FINAL-REFERENCE (dev only)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    lfs = L.registry()
    recs = L.records(args.inputs, L.load_v1(args.v1_run), L.load_llm(args.llm_labels))
    rows = list(L.vote_rows(recs, lfs))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"votes-{args.name}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    ref = {"personal": personal_reference(args.ref), "onsite": onsite_reference(args.ref)} if args.ref else None
    rep = report(rows, lfs, ref)
    (args.out / f"LF-REPORT-{args.name}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "lfs"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
