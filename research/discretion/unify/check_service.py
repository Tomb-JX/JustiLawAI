"""Check a binding-service run: parity with the evaluated methods, and gated quality.

Parity: on the reviewed records, every route's proposal must equal the per-record
decision recorded in the review set's private key (same frozen models).
Quality: bound fields vs (a) the double-blind Claude review and (b) the model-vote
field reference; reports coverage (bound share) and precision of bound values.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from experiment_relation_edges import load_batch
from evaluate_relation_model_labels import amount_key
from review_score import key_of

FIELDS = {"amounts.personal_stake": "personal_stake", "amounts.onsite_stake_total": "onsite_stake_total"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--review", type=Path, required=True)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    run = {r["id"]: r for r in (json.loads(l) for l in args.run.read_text("utf-8").splitlines() if l.strip())}
    key = json.loads((args.review / "PRIVATE-key.json").read_text("utf-8"))
    gold = json.loads((args.review / "AGREED.json").read_text("utf-8"))
    for rid, fields in json.loads((args.review / "ADJUDICATED.json").read_text("utf-8")).items():
        task = json.loads((args.review / "tasks" / f"{rid}.json").read_text("utf-8"))
        for f, ans in fields.items():
            gold.setdefault(rid, {})[f] = {"key": key_of(ans, task)}
    refs = {it["id"]: it["refs"] for it in load_batch(args.batch, args.batch / "ab" / "labels")}
    parity = Counter()
    for rid, row in key["rows"].items():
        for b in run[rid]["bindings"]:
            f = FIELDS.get(b["field"])
            if f:
                for route, p in b["proposals"].items():
                    parity["checked"] += 1
                    parity["equal" if p["value"] == row["methods"][route][f] else "differ"] += 1
    report = {"parity_on_reviewed": dict(parity), "fields": {}}
    for path, f in FIELDS.items():
        c = Counter()
        for rid, row in run.items():
            b = next(x for x in row["bindings"] if x["field"] == path)
            c["records"] += 1
            c[b["binding_status"] + ":" + (b["reason"] or "value")] += 1
            if b["binding_status"] != "bound":
                continue
            value_key = amount_key(b["value"])
            ref = refs[rid][f]["consensus"]
            if ref and ref[0] in {"selected", "absent"}:
                c["vote_scored"] += 1
                c["vote_correct"] += ref[0] == "selected" and ref[1] == value_key
            g = gold.get(rid, {}).get(f, {}).get("key")
            if g and g != "uncertain":
                c["review_scored"] += 1
                c["review_correct"] += g == value_key
        c["coverage_bound"] = round(sum(v for k, v in c.items() if k.startswith("bound:")) / c["records"], 3)
        c["precision_vs_vote"] = round(c["vote_correct"] / c["vote_scored"], 3) if c["vote_scored"] else None
        c["precision_vs_review"] = round(c["review_correct"] / c["review_scored"], 3) if c["review_scored"] else None
        report["fields"][path] = dict(c)
    for path in ("persons.participant_count", "person.age"):
        report["fields"][path] = dict(Counter(next(x for x in r["bindings"] if x["field"] == path)["binding_status"]
                                              for r in run.values()))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
