"""Score the personal_attribution rule against a review reference (aggregates only).

Scores the rule alone and, given a service run, "service bound else rule": the routes'
consensus is kept where it bound and the rule only fills what went to a person.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from personal_attribution import decide
from review4 import _pred_key, _task, amount_key, final_keys, key_of, wilson_low
from supply_packet import build_packet

FIELD = "personal_stake"


def reference(root: Path) -> dict[str, str]:
    path = root / "FINAL-REFERENCE.json"
    if path.exists():
        return {rid: key_of(FIELD, a[FIELD], _task(root, rid)) for rid, a in json.loads(path.read_text("utf-8")).items()}
    return {rid: f[FIELD]["key"] for rid, f in final_keys(root).items() if FIELD in f}


def _tally(c: Counter, name: str, gold: str, pred: str | None, reason: str) -> None:
    if gold == "uncertain":
        c[f"{name}:ref_uncertain:{'bound' if pred else 'to_person'}"] += 1
        return
    if pred is None:
        k = "to_person_ref_" + ("absent" if gold == "absent" else "value")
    elif pred == gold:
        k = "correct"
    else:
        k = "output_on_absent" if gold == "absent" else "wrong_value"
    c[f"{name}:{k}"] += 1
    c[f"{name}:{k}:{reason}"] += 1


def _summary(c: Counter, name: str) -> dict:
    ok = c[f"{name}:correct"]
    n = ok + c[f"{name}:wrong_value"] + c[f"{name}:output_on_absent"]
    return {"bound": n, "correct": ok, "precision": round(ok / n, 3) if n else None,
            "wilson_low95": round(wilson_low(ok, n), 3) if n else None,
            "ref_value_total": ok + c[f"{name}:wrong_value"] + c[f"{name}:to_person_ref_value"]}


def score(root: Path, inputs: Path, run: Path | None) -> dict:
    ref = reference(root)
    service = {}
    if run:
        for line in run.read_text("utf-8").splitlines():
            r = json.loads(line)
            b = next(b for b in r["bindings"] if b["field"] == "amounts.personal_stake")
            service[r["id"]] = _pred_key(FIELD, b)
    c = Counter()
    for line in inputs.read_text("utf-8").splitlines():
        r = json.loads(line)
        if r["id"] not in ref:
            continue
        gold = ref[r["id"]]
        d = decide(build_packet(r["text_full"], r, record_id=r["id"], layout_wraps=True), r)
        rule = amount_key(d["value"]) if d["status"] == "bound" else None
        _tally(c, "rule", gold, rule, d["reason"])
        if run and r["id"] in service:
            svc = service[r["id"]]
            _tally(c, "service", gold, svc, "service")
            _tally(c, "service_else_rule", gold, svc or rule, "service" if svc else d["reason"])
            if svc and rule and svc != rule:
                c["disagree_service_vs_rule"] += 1
    out = {name: _summary(c, name) for name in ("rule", "service", "service_else_rule") if c[f"{name}:correct"] or name == "rule"}
    out["detail"] = dict(sorted(c.items()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True, help="review directory holding the reference")
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--run", type=Path, help="binding service output on the same inputs")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = score(args.root, args.inputs, args.run)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "detail"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
