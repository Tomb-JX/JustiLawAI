"""Record-level, zero-cost comparison of binding sources on dev and H3 (aggregates only).

Systems: binding-v1 consensus, the frozen rules, two-LLM agreement, majority vote of the
non-LLM LFs, and the Dawid–Skene label model trained on U votes without and with the LLM
group. Candidate probabilities become a record decision at a fixed 0.5: one value above it
fills, none above it is "absent", several values go to a person. Criteria are fixed in
lf-20261028/CRITERIA-compare.md before this runs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import labeling_functions as L
import onsite_caliber as oc
import personal_attribution as pa
from evaluate_relation_model_labels import amount_key
from label_model import DawidSkene, factors, majority, outcomes
from review4 import _pred_key, key_of, task_for, wilson_low
from score_onsite_caliber import reference as onsite_reference
from score_personal_attribution import reference as personal_reference
from supply_packet import build_packet

THRESHOLD = 0.5
PENALTY = 3


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]


def record_decisions(rows: list[dict], probs: list[float]) -> dict[str, str]:
    by = defaultdict(set)
    seen = set()
    for r, p in zip(rows, probs):
        seen.add(r["id"])
        if p >= THRESHOLD:
            by[r["id"]].add(r["value"])
    return {rid: ("absent" if not by[rid] else next(iter(by[rid])) if len(by[rid]) == 1 else None) for rid in seen}


def tally(pred: dict[str, str | None], gold: dict[str, str], ids: set[str]) -> dict:
    c = Counter()
    for rid in ids:
        g, p = gold.get(rid), pred.get(rid)
        if g is None:
            continue
        if g == "uncertain":
            c["ref_uncertain_decided" if p else "ref_uncertain_to_person"] += 1
            continue
        if p is None:
            c["to_person"] += 1
        elif p == g:
            c["correct_absent" if g == "absent" else "correct_value"] += 1
        else:
            c["wrong_on_absent" if g == "absent" else "wrong_value"] += 1
    ok = c["correct_value"] + c["correct_absent"]
    bad = c["wrong_value"] + c["wrong_on_absent"]
    n = ok + bad
    return {**dict(sorted(c.items())), "decided": n, "correct": ok, "wrong": bad,
            "precision": round(ok / n, 3) if n else None, "wilson_low95": round(wilson_low(ok, n), 3) if n else None,
            "utility": ok - PENALTY * bad}


def baselines(inputs: Path, v1_run: Path, llm_dir: Path, ids: set[str]) -> dict[str, dict[str, dict]]:
    v1 = {}
    for line in v1_run.read_text("utf-8").splitlines():
        r = json.loads(line)
        v1[r["id"]] = {b["field"].split(".")[1]: _pred_key(b["field"].split(".")[1], b) for b in r["bindings"]}
    answers = L.load_llm(llm_dir)
    out = {s: {"personal": {}, "onsite": {}} for s in ("v1", "rules", "llm_agreed")}
    for line in inputs.read_text("utf-8").splitlines():
        rec = json.loads(line)
        if rec["id"] not in ids:
            continue
        rid = rec["id"]
        packet = build_packet(rec["text_full"], rec, record_id=rid, layout_wraps=True)
        task = task_for(rec, packet)
        for t, f in L.FIELD.items():
            out["v1"][t][rid] = v1.get(rid, {}).get(f)
            a = answers.get(rid, {})
            keys = {key_of(f, a[p][f], task) for p in ("bailian", "deepseek") if p in a}
            out["llm_agreed"][t][rid] = (next(iter(keys)) if len(keys) == 1 and len(a) == 2
                                         and "uncertain" not in keys else None)
        d = pa.decide(packet, rec)
        out["rules"]["personal"][rid] = amount_key(d["value"]) if d["status"] == "bound" else None
        d = oc.decide(oc.classify(packet, rec))
        out["rules"]["onsite"][rid] = (amount_key(d["candidate"]["value"]) if d["status"] == "bound"
                                       else "absent" if d["status"] == "absent" else None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lf-dir", type=Path, required=True, help="directory with votes-{u,dev,h3}.jsonl")
    ap.add_argument("--u-llm-labels", type=Path, required=True)
    ap.add_argument("--set", nargs=5, action="append", required=True,
                    metavar=("NAME", "INPUTS", "V1_RUN", "LLM_LABELS", "REF_ROOT"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    lfs = L.registry()
    u_rows = load_rows(args.lf_dir / "votes-u.jsonl")
    u_llm = set(L.load_llm(args.u_llm_labels))
    models = {}
    for t in L.TASKS:
        for use_llm in (False, True):
            facs = factors(lfs, t, use_llm)
            plain = [n for n, tt, g, _f in lfs if tt == t and g != "llm"]
            init = [majority(r, plain) for r in u_rows]
            models[(t, use_llm)] = (facs, DawidSkene(facs).fit([outcomes(r, facs, u_llm) for r in u_rows], init))
    report = {"threshold": THRESHOLD, "penalty": PENALTY,
              "label_model_prior_yes": {f"{t}{'+llm' if u else ''}": round(m.prior[1], 3)
                                        for (t, u), (_f, m) in models.items()}}
    for name, inputs, v1_run, llm_dir, ref_root in args.set:
        rows = load_rows(args.lf_dir / f"votes-{name}.jsonl")
        with_cands = {r["id"] for r in rows}
        llm_ids = set(L.load_llm(Path(llm_dir)))
        gold = {"personal": personal_reference(Path(ref_root)), "onsite": onsite_reference(Path(ref_root))}
        base = baselines(Path(inputs), Path(v1_run), Path(llm_dir), with_cands)
        res = {"records_with_candidates": len(with_cands)}
        for t in L.TASKS:
            plain = [n for n, tt, g, _f in lfs if tt == t and g != "llm"]
            preds = {**{s: base[s][t] for s in base},
                     "majority_vote": record_decisions(rows, [1.0 if majority(r, plain) >= THRESHOLD else 0.0
                                                              for r in rows])}
            for use_llm in (False, True):
                facs, m = models[(t, use_llm)]
                preds["label_model" + ("+llm" if use_llm else "")] = record_decisions(
                    rows, m.predict([outcomes(r, facs, llm_ids) for r in rows]))
            res[t] = {s: tally(p, gold[t], with_cands) for s, p in preds.items()}
            res[t]["reference"] = dict(Counter("value" if gold[t].get(i, "").startswith(("amount", "missing")) else
                                               gold[t].get(i, "none") for i in with_cands))
        report[name] = res
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
