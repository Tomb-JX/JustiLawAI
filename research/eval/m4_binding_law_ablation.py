"""Train-only, fixed-fold M4 ablation of reviewed binding and M2 rule signals.

The reference is model-produced/adjudicated, not human gold.  All facts used by
the feature builder are checked against the frozen input facts_text.  Provincial
rules are observational features, never hard constraints in this experiment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold
from scipy.stats import binomtest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "justilaw-api"))
from app.discretion.norm_layer import Facts, assess  # noqa: E402
from app.discretion.norm_store import load  # noqa: E402
from app.discretion.schema import AmountRange  # noqa: E402
from m4_type_algorithm_cv import LABELS, label, read  # noqa: E402
from outcome_constraint_calibration import resolve_regions  # noqa: E402

ROOT = Path("D:/02_Dev/Data/justilaw-research")
REFS = [
    ("review-p3p7dev-20261027/FINAL-REFERENCE.json", "review-p3p7dev-20261027/tasks"),
    ("review-persons-h3-20261027/FINAL-REFERENCE-H3.json", "review-amounts-h3/tasks"),
]
INPUTS = ["p3p7-dev-20261027/inputs.jsonl", "h3-inputs-20261027/inputs.jsonl"]
FIELDS = ("personal_stake", "onsite_stake_total")
STATES = ("selected", "absent", "uncertain", "missing_candidate", "unannotated", "rejected")
TIER_LABELS = ("罚款", "拘留", "拘留并处罚款")
BEHAVIOR = re.compile(r"参与赌博|进行赌博|实施赌博|赌博活动|以.{0,14}(?:方式|形式)赌博|聚赌|参赌")
PROVIDER = re.compile(r"为赌博提供条件|开设赌场|组织赌博|容留他人赌博|提供赌博场所")
METHODS = ((re.compile(r"网络赌博|网上赌博|互联网赌博"), "网络赌博"),
           (re.compile(r"赌博机"), "赌博机"),
           (re.compile(r"六合彩"), "六合彩"),
           (re.compile(r"私彩"), "私彩"))
DATE = re.compile(r"(?P<y>20\d{2})[年./-](?P<m>\d{1,2})[月./-](?P<d>\d{1,2})日?")


def load_jsonl(path: Path) -> dict:
    return {row["id"]: row for row in read(path)}


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    m = DATE.search(s)
    if not m:
        return None
    try:
        return date(int(m["y"]), int(m["m"]), int(m["d"]))
    except ValueError:
        return None


def unwrap(x: dict) -> dict:
    return x.get("answer", x)


def prepare_reference(rows: list[dict]) -> tuple[dict, Counter]:
    by_id = {r["id"]: r for r in rows}
    refs = {}
    audit = Counter()
    for (ref_file, task_dir), input_file in zip(REFS, INPUTS):
        raw = json.loads((ROOT / "relation_annotation" / ref_file).read_text(encoding="utf-8"))
        inputs = load_jsonl(ROOT / "relation_annotation" / input_file)
        task_root = ROOT / "relation_annotation" / task_dir
        for rid, record in raw.items():
            if rid not in by_id:
                audit["not_in_frozen_train"] += 1
                continue
            if rid in refs:
                audit["duplicate_reference_id"] += 1
                continue
            if rid not in inputs or inputs[rid].get("facts_text") != by_id[rid]["input"]["facts_text"]:
                audit["facts_text_mismatch"] += 1
                continue
            facts = by_id[rid]["input"]["facts_text"]
            task = json.loads((task_root / f"{rid}.json").read_text(encoding="utf-8"))
            cands = {x["candidate_id"]: x for x in task.get("amount_candidates", [])}
            out = {"source": ref_file, "date": None, "count": None, "amounts": {}}
            for field in FIELDS:
                a = unwrap(record.get(field, {}))
                status = a.get("status", "uncertain")
                val = None
                if status == "selected":
                    cand = cands.get(a.get("candidate_id"))
                    if cand and cand.get("raw") and cand["raw"] in facts:
                        norm = cand.get("normalized") or {}
                        lo, hi = norm.get("min"), norm.get("max")
                        if isinstance(lo, (int, float)) and lo >= 0 and (hi is None or isinstance(hi, (int, float)) and hi >= lo):
                            val = (float(lo), None if hi is None else float(hi))
                    if val is None:
                        audit[f"{field}_invalid_evidence"] += 1
                        status = "rejected"
                out["amounts"][field] = {"status": status, "range": val}
                audit[f"{field}_{status}"] += 1
            c = unwrap(record.get("participant_count", {}))
            if c.get("status") == "value" and isinstance(c.get("value"), int) and c["value"] > 0:
                evidence = c.get("evidence") or ""
                if evidence and evidence in facts:
                    out["count"] = c["value"]
                    audit["count_valid"] += 1
                else:
                    audit["count_invalid_evidence"] += 1
            a = unwrap(record.get("age", {}))
            out["date"] = parse_date(a.get("behavior_date"))
            if out["date"]:
                visible_dates = {parse_date(m.group(0)) for m in DATE.finditer(facts)}
                if out["date"] in visible_dates:
                    audit["behavior_date_exact"] += 1
                else:
                    out["date"] = None
                    audit["behavior_date_rejected_no_fact_evidence"] += 1
            refs[rid] = out
            audit["matched_reference"] += 1
    return refs, audit


def binding_features(row: dict, ref: dict | None) -> list[float]:
    out = [1.0 if ref else 0.0]
    for field in FIELDS:
        x = (ref or {}).get("amounts", {}).get(field, {"status": "unannotated", "range": None})
        status = x["status"]
        out += [float(status == s) for s in STATES]
        rng = x["range"]
        if rng:
            lo, hi = rng
            out += [math.log1p(lo) / 10, math.log1p(hi) / 10 if hi is not None else 0,
                    float(hi is None), float(lo < 500), float(lo >= 500), float(lo >= 1000),
                    float(lo >= 2000), float(lo >= 5000)]
        else:
            out += [0.0] * 8
    count = (ref or {}).get("count")
    out += [float(count is not None), min(count or 0, 20) / 10]
    return out


def rule_features(row: dict, ref: dict | None, region: str | None, lib) -> tuple[list[float], dict]:
    """Unknown facts stay unknown; M2 gives suggestions, not automatic labels."""
    features = [0.0] * 14
    diag = {"status": "unavailable", "reason": "missing_reference"}
    if not ref:
        return features, diag
    if not region:
        return features, {"status": "unavailable", "reason": "region_unavailable_or_out_of_scope"}
    facts = row["input"]["facts_text"]
    behavior = "参与赌博" if BEHAVIOR.search(facts) and not PROVIDER.search(facts) else None
    if behavior is None:
        return features, {"status": "unavailable", "reason": "behavior_ambiguous"}
    behavior_date = ref["date"]
    decision_date = parse_date(row["event_id"])
    if behavior_date is None or decision_date is None or behavior_date > decision_date:
        return features, {"status": "unavailable", "reason": "date_unavailable"}
    provincial = lib.provinces[{"江苏": "320000", "河北": "130000"}[region]]
    document = (provincial.get("documents") or [{}])[0]
    effective_from = parse_date(str(document.get("effective_from") or ""))
    effective_to = parse_date(str(document.get("effective_to") or ""))
    if effective_from and behavior_date < effective_from or effective_to and decision_date > effective_to:
        return features, {"status": "unavailable", "reason": "provincial_rule_out_of_time"}
    method = next((name for pattern, name in METHODS if pattern.search(facts)), None)
    def amount(field):
        rng = ref["amounts"][field]["range"]
        return AmountRange(min=rng[0], max=rng[1]) if rng else None
    f = Facts(behavior_date=behavior_date, decision_date=decision_date,
              region={"江苏": "320000", "河北": "130000"}[region],
              behavior_type=behavior, method=method,
              personal_stake=amount("personal_stake"),
              onsite_stake_total=amount("onsite_stake_total"),
              participant_count=ref["count"])
    try:
        result = assess(f, lib)
    except ValueError as exc:
        return features, {"status": "unavailable", "reason": f"M2:{exc}"}
    band = result.stake_threshold
    if band.get("applicability") != "applicable":
        return features, {"status": "unavailable", "reason": band.get("status")}
    # Provincial penalty wording reflects the pre-2026 law.  2026 cases remain
    # descriptive M2 outputs, but no provincial tier feature is injected.
    if decision_date >= date(2026, 1, 1) or not band.get("verified"):
        return features, {"status": "unavailable", "reason": "provincial_alignment_or_verification"}
    penalties = band.get("band_penalty", [])
    allowed = set()
    for text in penalties:
        allowed.add("拘留并处罚款" if "拘留" in text and "罚款" in text else "拘留" if "拘留" in text else "罚款")
    names = band.get("bands", [])
    below = 0 in band["observed_band_indices"]
    if below and region == "江苏":
        allowed.add("不予处罚")  # 江苏指导意见第六条（四）；跨档时保留此候选
    features = [1.0, float(region == "江苏"), float(region == "河北"), float(method is not None),
                float(below), float(len(allowed) == 1), float(len(allowed) > 1),
                *[float(k in allowed) for k in TIER_LABELS],
                float(any("第一档" in x or "情节较轻" in x for x in names)),
                float(any("第二档" in x or "一般情节" in x for x in names)),
                float(any("第三档" in x or "情节较重" in x for x in names)),
                float(bool(result.needs_review) or bool(band.get("notes")))]
    assert len(features) == 14
    return features, {"status": "applicable", "region": region, "allowed": sorted(allowed),
                      "below": below, "band": names, "law": result.law_id,
                      "unknown_conditions": band["unknown_conditions"],
                      "observed_band_indices": band["observed_band_indices"],
                      "review_note": bool(result.needs_review) or bool(band.get("notes"))}


def scores(y, pred, indices, weights):
    if not len(indices):
        return None
    return {"n": int(len(indices)), "accuracy": float(accuracy_score(y[indices], pred[indices])),
            "event_weighted_accuracy": float(accuracy_score(y[indices], pred[indices], sample_weight=weights[indices])),
            "macro_f1_core4": float(f1_score(y[indices], pred[indices], labels=LABELS, average="macro", zero_division=0))}


def cluster_permutation(y, a, b, groups, seed: int, unit: str, repeats: int = 1000) -> dict:
    """Paired randomization of full-sample Macro-F1 with entire groups swapped."""
    group_ids = {g: i for i, g in enumerate(dict.fromkeys(groups))}
    row_group = np.array([group_ids[g] for g in groups])
    observed = float(f1_score(y, b, labels=LABELS, average="macro", zero_division=0)
                     - f1_score(y, a, labels=LABELS, average="macro", zero_division=0))
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(repeats):
        swap = rng.integers(0, 2, len(group_ids), dtype=np.int8)[row_group].astype(bool)
        pa = np.where(swap, b, a)
        pb = np.where(swap, a, b)
        diff = f1_score(y, pb, labels=LABELS, average="macro", zero_division=0) - f1_score(
            y, pa, labels=LABELS, average="macro", zero_division=0)
        extreme += abs(diff) >= abs(observed) - 1e-12
    return {"delta_macro_f1": observed, "two_sided_p": (extreme + 1) / (repeats + 1),
            "repeats": repeats, "unit": unit}


def run_axis(rows, x_binding, x_rule, ref_mask, law_mask, axis):
    texts = [r["input"]["facts_text"] for r in rows]
    y = np.array([label(r) for r in rows])
    events = [r["event_id"] for r in rows]
    groups = events if axis == "event" else [e.split("|")[0] for e in events]
    sizes = Counter(events)
    weights = np.array([1 / sizes[e] for e in events])
    arms = ("text", "text_binding", "text_binding_law")
    pred = {arm: np.empty(len(rows), dtype=object) for arm in arms}
    folds = []
    for fold, (tr, va) in enumerate(GroupKFold(n_splits=3).split(texts, y, groups), 1):
        assert not set(np.array(groups)[tr]) & set(np.array(groups)[va])
        vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                              min_df=2, max_features=100_000)
        xt = vec.fit_transform(texts[i] for i in tr)
        xv = vec.transform(texts[i] for i in va)
        matrices = {
            "text": (xt, xv),
            "text_binding": (hstack((xt, csr_matrix(x_binding[tr])), format="csr"),
                             hstack((xv, csr_matrix(x_binding[va])), format="csr")),
            "text_binding_law": (hstack((xt, csr_matrix(x_binding[tr]), csr_matrix(x_rule[tr])), format="csr"),
                                 hstack((xv, csr_matrix(x_binding[va]), csr_matrix(x_rule[va])), format="csr")),
        }
        for arm, (a, b) in matrices.items():
            model = LogisticRegression(C=3.0, max_iter=1000, class_weight="balanced", random_state=20261027)
            model.fit(a, y[tr], sample_weight=weights[tr])
            pred[arm][va] = model.predict(b)
        folds.append({"fold": fold, "train": len(tr), "valid": len(va),
                      "reference_valid": int(ref_mask[va].sum()), "law_valid": int(law_mask[va].sum())})
    subsets = {"all": np.arange(len(rows)), "reference_covered": np.flatnonzero(ref_mask),
               "law_applicable": np.flatnonzero(law_mask),
               "unannotated": np.flatnonzero(~ref_mask)}
    result = {"folds": folds, "arms": {arm: {subset: scores(y, p, idx, weights) for subset, idx in subsets.items()}
                                       for arm, p in pred.items()}, "paired": {}}
    for a, b in (("text", "text_binding"), ("text_binding", "text_binding_law"), ("text", "text_binding_law")):
        result["paired"][f"{a}_vs_{b}"] = {
            subset: {"a_only_correct": int(((pred[a][idx] == y[idx]) & (pred[b][idx] != y[idx])).sum()),
                     "b_only_correct": int(((pred[b][idx] == y[idx]) & (pred[a][idx] != y[idx])).sum()),
                     "mcnemar_exact_p": float(binomtest(
                         int(((pred[a][idx] == y[idx]) & (pred[b][idx] != y[idx])).sum()),
                         int(((pred[a][idx] == y[idx]) != (pred[b][idx] == y[idx])).sum()),
                         0.5).pvalue) if int(((pred[a][idx] == y[idx]) != (pred[b][idx] == y[idx])).sum()) else 1.0}
            for subset, idx in subsets.items()}
    result["full_macro_permutation"] = {
        f"{a}_vs_{b}": cluster_permutation(y, pred[a], pred[b], groups, 20261027 + i, axis)
        for i, (a, b) in enumerate((("text", "text_binding"),
                                    ("text_binding", "text_binding_law"),
                                    ("text", "text_binding_law")))}
    return result, pred


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", type=Path, default=ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    rows = read(args.package / "train.jsonl")
    refs, audit = prepare_reference(rows)
    regions = resolve_regions(rows, ROOT / "lake/catalog/lake.db")
    lib = load()
    xb, xr, diagnostics = [], [], {}
    for row in rows:
        rid = row["id"]
        ref = refs.get(rid)
        xb.append(binding_features(row, ref))
        lf, d = rule_features(row, ref, regions.get(rid), lib)
        xr.append(lf)
        diagnostics[rid] = d
    xb, xr = np.array(xb), np.array(xr)
    ref_mask = np.array([r["id"] in refs for r in rows])
    law_mask = np.array([diagnostics[r["id"]]["status"] == "applicable" for r in rows])
    report = {"package": str(args.package), "scope": "frozen_train_only; test40_never_opened",
              "reference_tier": "model_reviewed_not_human_gold", "m2_mode": "feature_only_no_hard_mask",
              "audit": dict(audit), "rule_status": dict(Counter(d["reason"] if d["status"] != "applicable" else "applicable"
                                                          for d in diagnostics.values())),
              "regional_applicable": dict(Counter(d.get("region") for d in diagnostics.values() if d["status"] == "applicable")),
              "axes": {}}
    truth = np.array([label(r) for r in rows])
    gate_indices = {
        mode: np.array([i for i, r in enumerate(rows)
                        if diagnostics[r["id"]]["status"] == "applicable"
                        and len(diagnostics[r["id"]]["allowed"]) == 1
                        and not diagnostics[r["id"]]["below"]
                        and (mode == "advisory" or not diagnostics[r["id"]]["review_note"])], dtype=int)
        for mode in ("strict", "advisory")}
    report["candidate_gate_diagnostic"] = {
        "definition": "single provincial suggested type, excluding below-first-band; observational only, no deployment",
        "strict_excludes_review_notes": True,
        "eligible_n": {k: int(len(v)) for k, v in gate_indices.items()}, "axes": {}}
    for axis in ("event", "agency"):
        report["axes"][axis], predictions = run_axis(rows, xb, xr, ref_mask, law_mask, axis)
        gate = {}
        for mode, indices in gate_indices.items():
            gate[mode] = {}
            for arm in ("text", "text_binding"):
                before = predictions[arm][indices]
                after = np.array([diagnostics[rows[i]["id"]]["allowed"][0] for i in indices])
                gate[mode][arm] = {"overrides": int((before != after).sum()),
                                   "before_correct": int((before == truth[indices]).sum()),
                                   "after_correct": int((after == truth[indices]).sum()),
                                   "helped": int(((after == truth[indices]) & (before != truth[indices])).sum()),
                                   "hurt": int(((after != truth[indices]) & (before == truth[indices])).sum())}
        report["candidate_gate_diagnostic"]["axes"][axis] = gate
    # A provincial suggestion is evaluated against history, not treated as a legal verdict.
    applicable = [r for r in rows if diagnostics[r["id"]]["status"] == "applicable"]
    report["rule_historical_alignment"] = {
        "n": len(applicable),
        "historical_type_in_band": sum(label(r) in diagnostics[r["id"]]["allowed"] for r in applicable),
        "below_first_band": sum(diagnostics[r["id"]]["below"] for r in applicable),
        "note": "Band is an advisory old-law provincial standard. Missing mitigating facts and incomplete field coverage can explain disagreement."}
    report["rule_disagreements"] = [
        {"id": r["id"], "event_id": r["event_id"], "historical_type": label(r),
         "rule": diagnostics[r["id"]], "binding": refs[r["id"]]["amounts"]}
        for r in applicable if label(r) not in diagnostics[r["id"]]["allowed"]]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit": report["audit"], "rule_status": report["rule_status"],
                      "axes": {k: {a: {s: x["macro_f1_core4"] if x else None for s, x in v.items()}
                                   for a, v in block["arms"].items()} for k, block in report["axes"].items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
