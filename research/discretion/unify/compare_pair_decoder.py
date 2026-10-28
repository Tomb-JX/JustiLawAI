"""Zero-cost falsification of the pair decoder for personal stake (aggregates only).

Thresholds are picked on dev by utility, then applied once to H3. Systems: frozen rule,
pair decoder, rule-then-decoder, binding-v1 (reference). Utility = correct − 3 × (wrong +
decisions on records whose reference is uncertain). Criteria: CRITERIA-pair-decoder.md.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import pair_decoder as pd
import personal_attribution as pa
from evaluate_relation_model_labels import amount_key
from review4 import _pred_key, wilson_low
from score_personal_attribution import reference
from supply_packet import build_packet

FILL = (0.5, 0.6, 0.7, 0.8, 0.9)
ABSENT = (0.05, 0.1, 0.2, 0.3, 0.4)
PENALTY = 3


def tally(pred: dict, gold: dict) -> dict:
    c = Counter()
    for rid, g in gold.items():
        p = pred.get(rid)
        if g == "uncertain":
            c["uncertain_decided" if p else "uncertain_to_person"] += 1
        elif p is None:
            c["to_person_value" if g != "absent" else "to_person_absent"] += 1
        elif p == g:
            c["correct_absent" if g == "absent" else "correct_value"] += 1
        else:
            c["wrong_on_absent" if g == "absent" else "wrong_value"] += 1
    ok = c["correct_value"] + c["correct_absent"]
    bad = c["wrong_value"] + c["wrong_on_absent"] + c["uncertain_decided"]
    n = ok + bad
    return {**dict(sorted(c.items())), "correct": ok, "errors": bad,
            "precision": round(ok / n, 3) if n else None, "wilson_low95": round(wilson_low(ok, n), 3) if n else None,
            "utility": ok - PENALTY * bad}


def systems(inputs: Path, v1_run: Path, items: list[dict], tf: float, ta: float) -> dict[str, dict]:
    v1 = {}
    for line in v1_run.read_text("utf-8").splitlines():
        r = json.loads(line)
        b = next(b for b in r["bindings"] if b["field"] == "amounts.personal_stake")
        v1[r["id"]] = _pred_key("personal_stake", b)
    rules = {}
    for line in inputs.read_text("utf-8").splitlines():
        rec = json.loads(line)
        d = pa.decide(build_packet(rec["text_full"], rec, record_id=rec["id"], layout_wraps=True), rec)
        rules[rec["id"]] = amount_key(d["value"]) if d["status"] == "bound" else None
    dec = {it["id"]: pd.decide(it, tf, ta) for it in items}
    return {"v1": v1, "rules": rules, "decoder": dec,
            "rules_then_decoder": {rid: rules.get(rid) or dec.get(rid) for rid in dec}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--set", nargs=4, action="append", required=True, metavar=("NAME", "INPUTS", "V1_RUN", "REF_ROOT"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    sets = {}
    for name, inputs, v1_run, ref_root in args.set:
        records = [json.loads(l) for l in Path(inputs).read_text("utf-8").splitlines() if l.strip()]
        sets[name] = (Path(inputs), Path(v1_run), pd.score_records(records, args.model_dir), reference(Path(ref_root)))
    _i, _v, dev_items, dev_gold = sets["dev"]
    grid = {}
    for tf in FILL:
        for ta in ABSENT:
            if ta <= tf:
                grid[(tf, ta)] = tally({it["id"]: pd.decide(it, tf, ta) for it in dev_items}, dev_gold)["utility"]
    tf, ta = max(grid, key=lambda k: (grid[k], k[0], -k[1]))
    report = {"chosen_on_dev": {"tau_fill": tf, "tau_absent": ta, "dev_utility": grid[(tf, ta)]},
              "grid_dev_utility": {f"{a}/{b}": u for (a, b), u in grid.items()}}
    for name, (inputs, v1_run, items, gold) in sets.items():
        preds = systems(inputs, v1_run, items, tf, ta)
        report[name] = {"records": len(gold), "reference": dict(Counter(
            "value" if g.startswith(("amount", "missing")) else g for g in gold.values())),
            **{s: tally(p, gold) for s, p in preds.items()}}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
