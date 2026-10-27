"""Read-only audit of where M4 legal facts disappear along the existing chain.

This is a provenance/coverage diagnostic, not a gold-standard extraction score.
Reads frozen train only; never reads test40 or outcome text as model input.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from m4_binding_law_ablation import ROOT, INPUTS, METHODS, parse_date, prepare_reference, read, resolve_regions
from app.discretion.norm_layer import Facts, assess
from app.discretion.norm_store import load
from app.discretion.schema import GamblingElements
from key_field_presence import MARKERS

SILVER = ROOT / "parsed2/m4-pilot-203-silver-20261020/records.jsonl"
TRAIN = ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl"
SERVICE = ROOT / "relation_annotation/p3p7-dev-20261027/v1-run.jsonl"
MARKER_GROUPS = {
    "method": r"麻将|扑克|牌九|炸金花|斗地主|骰子|彩票|网络赌博|网上赌博|赌博机|打牌|六合彩|私彩",
    "birth_or_age": r"出生|生于|周岁|年龄",
    "prior": r"曾因|曾被|前科|再次|一年内",
    "province_name": r"江苏省|河北省|浙江省|广东省|安徽省|山东省|辽宁省|黑龙江省|北京市|上海市",
}
KEYS = tuple(MARKERS)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jlines(path: Path) -> list[dict]:
    return read(path)


def signal_location(quote: str, facts: str, meta: str) -> str:
    if quote in facts:
        return "facts"
    if quote in meta:
        return "meta_only"
    return "outside_allowed_or_mismatch"


def audit_silver(train: dict[str, dict]) -> tuple[dict, list[dict]]:
    field_stats = defaultdict(Counter)
    all_stats = Counter()
    cases = []
    for rec in jlines(SILVER):
        rid = rec["id"]
        if rid not in train:
            all_stats["silver_not_in_v5_train"] += 1
            continue
        facts = train[rid]["input"]["facts_text"]
        if facts != rec["input"].get("facts_text"):
            all_stats["silver_fact_mismatch"] += 1
            continue
        all_stats["silver_exact_match"] += 1
        meta = rec["input"].get("meta_text") or ""
        out = {"id": rid, "source": "silver_36", "fields": {}, "method": {}}
        for group, fields in rec.get("reference_elements", {}).items():
            if not isinstance(fields, dict):
                continue
            for name, item in fields.items():
                path = f"{group}.{name}"
                if not isinstance(item, dict):
                    continue
                status = item.get("status")
                value = item.get("value")
                field_stats[path][f"status:{status}"] += 1
                if status != "未提及":
                    field_stats[path]["non_absent"] += 1
                    if value is not None:
                        field_stats[path]["value_present"] += 1
                    evidence = item.get("evidence") or []
                    if not evidence:
                        field_stats[path]["no_evidence"] += 1
                    locations = [signal_location(e.get("quote") or "", facts, meta)
                                 for e in evidence if isinstance(e, dict) and e.get("quote")]
                    if locations:
                        if "facts" in locations:
                            loc = "facts"
                        elif "meta_only" in locations:
                            loc = "meta_only"
                        else:
                            loc = "outside_allowed_or_mismatch"
                        field_stats[path][f"evidence:{loc}"] += 1
                        out["fields"][path] = {"status": status, "evidence_location": loc,
                                               "value_present": value is not None}
                else:
                    field_stats[path]["absent_in_silver"] += 1
        method = (rec.get("reference_elements") or {}).get("conduct", {}).get("method", {})
        adapter = next((value for pattern, value in METHODS if pattern.search(facts)), None)
        out["method"] = {"silver_status": method.get("status"), "silver_value": method.get("value"),
                         "adapter_value": adapter}
        if method.get("status") != "未提及" and method.get("value") is not None:
            all_stats["silver_method_value"] += 1
            if adapter is None:
                all_stats["silver_method_adapter_nil"] += 1
            elif adapter != method["value"]:
                all_stats["silver_method_adapter_disagree"] += 1
        cases.append(out)
    return {"counts": dict(all_stats), "fields": {k: dict(v) for k, v in sorted(field_stats.items())}}, cases


def audit_binding(train: dict[str, dict]) -> tuple[dict, list[dict]]:
    rows = list(train.values())
    refs, ref_audit = prepare_reference(rows)
    inputs = {}
    for f in INPUTS:
        for rec in jlines(ROOT / "relation_annotation" / f):
            if rec["id"] in refs:
                inputs[rec["id"]] = rec
    service = {rec["id"]: rec for rec in jlines(SERVICE)}
    field_stats = defaultdict(Counter)
    marker_stats = defaultdict(Counter)
    cases = []
    service_stats = Counter()
    for rid, ref in refs.items():
        src = inputs[rid]
        facts = src["facts_text"]
        meta = src.get("meta_text") or ""
        full = src.get("text_full") or ""
        out = {"id": rid, "source": "reviewed_binding", "field_states": {}, "markers": {}}
        for field, item in ref["amounts"].items():
            field_stats[field][item["status"]] += 1
            out["field_states"][field] = item["status"]
        field_stats["participant_count"]["value_evidence_passed" if ref["count"] is not None else "other"] += 1
        field_stats["behavior_date"]["exact_fact_evidence" if ref["date"] is not None else "other"] += 1
        for name, pattern in MARKER_GROUPS.items():
            hit = {zone: bool(re.search(pattern, text))
                   for zone, text in (("facts", facts), ("meta", meta), ("full", full))}
            for zone, yes in hit.items():
                marker_stats[name][f"{zone}_hit"] += yes
            if hit["meta"] and not hit["facts"]:
                marker_stats[name]["meta_not_facts"] += 1
            if hit["full"] and not hit["facts"] and not hit["meta"]:
                marker_stats[name]["full_only"] += 1
            out["markers"][name] = hit
        if rid in service:
            service_stats["overlap"] += 1
            answer = next((b for b in service[rid].get("bindings", [])
                           if b.get("field") == "amounts.personal_stake"), None)
            selected = ref["amounts"]["personal_stake"]["status"] == "selected"
            bound = bool(answer and answer.get("binding_status") == "bound")
            service_stats["reference_personal_selected"] += selected
            service_stats["service_personal_bound"] += bound
            service_stats["selected_but_not_bound"] += selected and not bound
            out["personal_service"] = {"selected_in_reference": selected, "bound_by_service": bound}
        cases.append(out)
    return {"reference_matching": dict(ref_audit),
            "field_status": {k: dict(v) for k, v in field_stats.items()},
            "text_markers_not_semantic_truth": {k: dict(v) for k, v in marker_stats.items()},
            "service_comparison": dict(service_stats)}, cases


def audit_silver_m2(train_rows: list[dict]) -> tuple[dict, list[dict]]:
    """Silver elements as a diagnostic upper-bound input, never as gold truth."""
    train = {r["id"]: r for r in train_rows}
    regions = resolve_regions(train_rows, ROOT / "lake/catalog/lake.db")
    lib = load()
    code = {"江苏": "320000", "河北": "130000"}
    counts = Counter()
    cases = []
    for rec in jlines(SILVER):
        rid = rec["id"]
        if rid not in train:
            continue
        counts["silver_in_train"] += 1
        province = regions.get(rid)
        if province is None:
            counts["region_unknown_or_outside_two_provinces"] += 1
            continue
        counts[f"region:{province}"] += 1
        meta = rec.get("metadata") or {}
        doc = (lib.provinces[code[province]].get("documents") or [{}])[0]
        behavior_date = parse_date(str(meta.get("behavior_date") or ""))
        decision_date = parse_date(str(meta.get("decision_date") or ""))
        effective_from = parse_date(str(doc.get("effective_from") or ""))
        effective_to = parse_date(str(doc.get("effective_to") or ""))
        if behavior_date is None or decision_date is None:
            counts["date_unavailable"] += 1
            continue
        if (effective_from and behavior_date < effective_from) or (effective_to and decision_date > effective_to):
            counts["province_rule_out_of_time"] += 1
            continue
        if decision_date >= date(2026, 1, 1):
            counts["new_law_province_alignment_pending"] += 1
            continue
        try:
            elements = GamblingElements.model_validate({
                "meta": {"region": code[province], "behavior_date": meta.get("behavior_date"),
                         "decision_date": meta.get("decision_date")},
                **rec["reference_elements"]})
            facts = Facts.from_elements(elements)
            result = assess(facts, lib)
        except (ValueError, KeyError, TypeError) as exc:
            counts[f"validation_error:{type(exc).__name__}"] += 1
            cases.append({"id": rid, "source": "silver_m2", "province": province,
                          "validation_error": str(exc)[:400]})
            continue
        band = result.stake_threshold
        status = band.get("status", "unknown")
        counts[f"m2_status:{status}"] += 1
        if band.get("bands"):
            counts["m2_nonempty_bands"] += 1
            allowed = set()
            for text in band.get("band_penalty") or []:
                allowed.add("拘留并处罚款" if "拘留" in text and "罚款" in text
                            else "拘留" if "拘留" in text else "罚款")
            if province == "江苏" and "未达起罚标准" in band.get("bands", []):
                allowed.add("不予处罚")
            counts[f"candidate_set_size:{len(allowed)}"] += 1
            historical = train[rid]["target"]["type"]
            counts["historical_type_in_candidate_set"] += historical in allowed
        else:
            allowed = set()
        cases.append({"id": rid, "source": "silver_m2", "province": province,
                      "behavior_type": facts.behavior_type, "method": facts.method,
                      "behavior_date": str(facts.behavior_date), "decision_date": str(facts.decision_date),
                      "personal_stake": facts.personal_stake.model_dump() if facts.personal_stake else None,
                      "onsite_stake_total": facts.onsite_stake_total.model_dump() if facts.onsite_stake_total else None,
                      "participant_count": facts.participant_count,
                      "commission": facts.commission.model_dump() if facts.commission else None,
                      "personal_stake_present": facts.personal_stake is not None,
                      "onsite_stake_present": facts.onsite_stake_total is not None,
                      "participant_count_present": facts.participant_count is not None,
                      "commission_present": facts.commission is not None,
                      "m2_status": status, "bands": band.get("bands"),
                      "candidate_types": sorted(allowed),
                      "historical_type_for_diagnostic_only": train[rid]["target"]["type"],
                      "rule_basis": band.get("basis"),
                      "rule_notes": band.get("notes"),
                      "m2_review_note": bool(result.needs_review) or bool(band.get("notes"))})
    return dict(counts), cases


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    train_rows = jlines(TRAIN)
    train = {r["id"]: r for r in train_rows}
    silver, silver_cases = audit_silver(train)
    binding, binding_cases = audit_binding(train)
    silver_m2, m2_cases = audit_silver_m2(train_rows)
    text = [r["input"]["facts_text"] for r in train_rows]
    marker_rates = {field: {"hits": sum(bool(re.search(pattern, t)) for t in text), "denominator": len(text)}
                    for field, pattern in MARKERS.items()}
    report = {"scope": "frozen_v5_train_only; existing_silver_and_model_review; test40_unread",
              "warning": "Silver/model-adjudicated statuses and keyword markers are not human truth or source completeness estimates.",
              "inputs_sha256": {str(p): sha(p) for p in (TRAIN, SILVER, SERVICE,
                               *(ROOT / "relation_annotation" / f for f in INPUTS))},
              "v5_train": {"records": len(train_rows), "marker_proxy": marker_rates},
              "silver_36": silver, "silver_m2_diagnostic": silver_m2, "reviewed_binding": binding,
              "case_audit": "cases.jsonl"}
    args.out.mkdir(parents=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.out / "cases.jsonl").open("w", encoding="utf-8") as stream:
        for case in silver_cases + binding_cases + m2_cases:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(json.dumps({"silver": silver["counts"], "silver_m2": silver_m2, "binding": binding["reference_matching"],
                      "service": binding["service_comparison"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
