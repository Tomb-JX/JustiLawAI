"""Score a binding-service run on counterfactual variants against edit-determined expectations.

same_as_base : the variant binding (status and value) equals the binder's own output on the
               unedited record; any change is instability.
value        : the variant must bind the relabelled value; "followed" = bound to it, "stale" =
               still bound to the old value, "other" = some other value, "to_person" = unresolved.
not_value    : after the evidence clause is removed the removed value must not be bound
               ("violated"); another bound value is reported apart as "other_value".
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows

FIELD = {"amounts.personal_stake": "personal_stake", "amounts.onsite_stake_total": "onsite_stake_total",
         "persons.participant_count": "participant_count", "person.age": "age"}


def outputs(path: Path) -> dict[str, dict[str, tuple]]:
    return {r["id"]: {FIELD[b["field"]]: (b["binding_status"], b.get("value")) for b in r["bindings"]}
            for r in rows(path)}


def score(expect: Path, base: Path, variants: Path) -> dict:
    b, v = outputs(base), outputs(variants)
    report: dict = defaultdict(lambda: defaultdict(Counter))
    examples: dict = defaultdict(list)
    for e in rows(expect):
        if e["variant_id"] not in v or e["base_id"] not in b:
            report[e["kind"]]["_missing"]["records"] += 1
            continue
        for field, exp in e["expect"].items():
            got, ref = v[e["variant_id"]][field], b[e["base_id"]][field]
            if exp["type"] == "same_as_base":
                if got == ref:
                    outcome = "same"
                elif ref[0] == "bound" and got[0] == "bound":
                    outcome = "changed_value"
                else:
                    outcome = "changed_status"
            elif exp["type"] == "value":
                outcome = ("to_person" if got[0] != "bound" else "followed" if got[1] == exp["value"]
                           else "stale" if got[1] == e.get("from") else "other")
            else:
                outcome = ("violated" if got[0] == "bound" and got[1] == exp["value"]
                           else "other_value" if got[0] == "bound" else "not_bound")
            report[e["kind"]][field][outcome] += 1
            if outcome in {"changed_value", "stale", "other", "violated", "other_value"} and len(
                    examples[(e["kind"], field, outcome)]) < 5:
                examples[(e["kind"], field, outcome)].append(
                    {"variant": e["variant_id"], "base": ref, "got": got, "expected": exp})
    return {"kinds": {k: {f: dict(c) for f, c in fields.items()} for k, fields in report.items()},
            "examples": {"|".join(k): x for k, x in examples.items()}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("expect", "base", "variants", "out"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    report = score(args.expect, args.base, args.variants)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for kind, fields in report["kinds"].items():
        print(kind)
        for f, c in fields.items():
            print("  ", f, c)


if __name__ == "__main__":
    main()
