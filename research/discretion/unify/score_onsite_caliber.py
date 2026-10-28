"""Score the onsite_caliber rule against a review reference (aggregates only).

The reference is either FINAL-REFERENCE.json (dev pool format: raw answers) or the
AGREED/ADJUDICATED pair read by review4.final_keys. The rule is scored as a stand-alone
onsite decision: bound value, absent, or unresolved (to a person).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from onsite_caliber import classify, decide
from review4 import _task, amount_key, final_keys, key_of, wilson_low
from supply_packet import build_packet

FIELD = "onsite_stake_total"


def reference(root: Path) -> dict[str, str]:
    path = root / "FINAL-REFERENCE.json"
    if path.exists():
        return {rid: key_of(FIELD, a[FIELD], _task(root, rid)) for rid, a in json.loads(path.read_text("utf-8")).items()}
    return {rid: f[FIELD]["key"] for rid, f in final_keys(root).items() if FIELD in f}


def score(root: Path, inputs: Path) -> dict:
    ref = reference(root)
    c = Counter()
    for line in inputs.read_text("utf-8").splitlines():
        r = json.loads(line)
        if r["id"] not in ref:
            continue
        gold = ref[r["id"]]
        d = decide(classify(build_packet(r["text_full"], r, record_id=r["id"], layout_wraps=True), r))
        if gold == "uncertain":
            c[f"ref_uncertain:{d['status']}"] += 1
            continue
        if d["status"] == "bound":
            k = "correct" if amount_key(d["candidate"]["value"]) == gold else (
                "output_on_absent" if gold == "absent" else "wrong_value")
        elif d["status"] == "absent":
            k = "absent_correct" if gold == "absent" else "silent_miss"
        else:
            k = "to_person_ref_" + ("absent" if gold == "absent" else "value")
        c[k] += 1
        c[f"{k}:{d['reason']}"] += 1
    out = dict(sorted(c.items()))
    bound = c["correct"] + c["wrong_value"] + c["output_on_absent"]
    absent = c["absent_correct"] + c["silent_miss"]
    out["bound_precision"] = round(c["correct"] / bound, 3) if bound else None
    out["bound_wilson_low95"] = round(wilson_low(c["correct"], bound), 3) if bound else None
    out["absent_precision"] = round(c["absent_correct"] / absent, 3) if absent else None
    out["absent_wilson_low95"] = round(wilson_low(c["absent_correct"], absent), 3) if absent else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="review directory holding the reference")
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = score(args.root, args.inputs)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
