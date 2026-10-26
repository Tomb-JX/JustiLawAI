"""Calibrate LLM review answers against a Claude reference, field by field (aggregates only).

Keys come from review4.key_of, so "amount:<v>", "count:<n>", "age:<n>", "absent" and
"uncertain" compare exactly as in every other review4 score. Reported per model and for
the A/B-agreed subset: how often the key equals the reference, split by what the reference
says (value / absent / uncertain), and how much of the data the agreed subset covers.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from review4 import FIELDS, _task, final_keys, key_of, wilson_low


def reference(root: Path) -> dict[str, dict[str, str]]:
    path = root / "FINAL-REFERENCE.json"
    if path.exists():
        return {rid: {f: key_of(f, a[f], _task(root, rid)) for f in FIELDS}
                for rid, a in json.loads(path.read_text("utf-8")).items()}
    return {rid: {f: v["key"] for f, v in fs.items()} for rid, fs in final_keys(root).items()}


def _kind(key: str) -> str:
    return key if key in ("absent", "uncertain") else "value"


def score(root: Path, labels: Path, names: tuple[str, str]) -> dict:
    ref = reference(root)
    c = Counter()
    for rid, gold in ref.items():
        keys = {}
        for name in names:
            path = labels / f"{rid}-{name}.json"
            if path.exists():
                ans = json.loads(path.read_text("utf-8"))["answer"]
                keys[name] = {f: key_of(f, ans[f], _task(root, rid)) for f in FIELDS if f in gold}
        if len(keys) < len(names):
            c["records_incomplete"] += 1
            continue
        c["records"] += 1
        for f in FIELDS:
            if f not in gold:
                continue  # a reference may cover only some fields (H3 amounts)
            g = _kind(gold[f])
            for name in names:
                c[f"{f}:{name}:ref_{g}"] += 1
                c[f"{f}:{name}:ref_{g}:match"] += keys[name][f] == gold[f]
            a, b = (keys[n][f] for n in names)
            if a == b:
                c[f"{f}:agreed:ref_{g}"] += 1
                c[f"{f}:agreed:ref_{g}:match"] += a == gold[f]
                if a not in ("absent", "uncertain"):
                    c[f"{f}:agreed_value"] += 1
                    c[f"{f}:agreed_value:match"] += a == gold[f]
            else:
                c[f"{f}:disagree:ref_{g}"] += 1
    out = {"records": c["records"], "records_incomplete": c["records_incomplete"], "fields": {}}
    for f in FIELDS:
        block = {}
        for who in (*names, "agreed"):
            n = sum(c[f"{f}:{who}:ref_{g}"] for g in ("value", "absent", "uncertain"))
            k = sum(c[f"{f}:{who}:ref_{g}:match"] for g in ("value", "absent", "uncertain"))
            block[who] = {"n": n, "match": k, "rate": round(k / n, 3) if n else None,
                          **{f"ref_{g}": f"{c[f'{f}:{who}:ref_{g}:match']}/{c[f'{f}:{who}:ref_{g}']}"
                             for g in ("value", "absent", "uncertain")}}
        n, k = c[f"{f}:agreed_value"], c[f"{f}:agreed_value:match"]
        block["agreed_value_precision"] = {"n": n, "match": k, "rate": round(k / n, 3) if n else None,
                                           "wilson_low95": round(wilson_low(k, n), 3) if n else None}
        block["agreement_rate"] = round(block["agreed"]["n"] / c["records"], 3) if c["records"] else None
        block["disagree_by_ref"] = {g: c[f"{f}:disagree:ref_{g}"] for g in ("value", "absent", "uncertain")}
        out["fields"][f] = block
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="review4 directory holding tasks and the reference")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = score(args.root, args.labels, tuple(args.providers.split(",")))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
