"""Make a blind, source-grounded human edge review packet on train/valid.

The private packet contains allowed facts/meta text and no silver values or
system predictions. The committed manifest contains IDs, strata, and hashes.
No generated form is a gold label until independent human review/adjudication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_supply_replay import rows
from supply_packet import build_packet


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def choose(teacher: dict, silver: dict, paired: dict) -> list[tuple[str, str]]:
    disputes = defaultdict(list)
    for row in paired["disagreements"]:
        if row["id"] in teacher and row["id"] in silver:
            disputes[row["field"]].append(row["id"])
    selected = []
    seen_ids, seen_events = set(), set()

    def add(rid: str, stratum: str) -> bool:
        if rid in seen_ids or rid not in teacher or rid not in silver:
            return False
        event = silver[rid]["metadata"].get("event_id") or rid
        if event in seen_events:
            return False
        seen_ids.add(rid)
        seen_events.add(event)
        selected.append((rid, stratum))
        return True

    for field, quota in (("amounts.personal_stake", 4),
                         ("amounts.onsite_stake_total", 4),
                         ("persons.participant_count", 6)):
        added = 0
        for rid in sorted(set(disputes[field]), key=digest):
            if add(rid, "system_disagreement:" + field):
                added += 1
                if added == quota:
                    break
        if added < quota:
            raise ValueError("insufficient_disagreements:" + field)
    age = [rid for rid, ref in silver.items() if type(ref["reference_elements"]["person"]["age"].get("value")) is int]
    added = 0
    for rid in sorted(age, key=digest):
        if add(rid, "age_operand"):
            added += 1
            if added == 4:
                break
    if added < 4:
        raise ValueError("insufficient_age_records")
    # A deterministic control from remaining development events. Its status is
    # hidden from reviewers; challenge sampling cannot estimate population risk.
    controls = sorted(teacher, key=digest)
    added = 0
    for rid in controls:
        if add(rid, "random_control"):
            added += 1
            if added == 6:
                break
    if added < 6:
        raise ValueError("insufficient_control_records")
    return selected


def review_case(inp: dict, text: str) -> dict:
    packet = build_packet(text, inp, record_id=inp["id"])
    quantities = []
    for q in packet["quantities"]:
        if q["type"] not in {"amount", "count", "age", "date"}:
            continue
        quantities.append({"candidate_id": q["candidate_id"], "type": q["type"],
                           "raw": q["raw"], "start": q["start"], "end": q["end"],
                           "source_span_id": q["source_span_id"]})
    return {"id": inp["id"], "source_sha256": inp["source_sha256"],
            "target": inp["target"], "aliases": inp.get("aliases") or [],
            "allowed_views": [{k: v[k] for k in ("id", "type", "start", "end", "text") if k in v}
                              for v in inp["sentence_view"]],
            "candidates": quantities}


def blank_form(case: dict) -> dict:
    return {"id": case["id"], "source_sha256": case["source_sha256"],
            "reviewer_id": None, "review_status": "pending",
            "entities": [], "events": [], "event_membership_edges": [],
            "quantity_edges": [{"candidate_id": q["candidate_id"], "decision": None,
                                "field_role": None, "actor_ids": [], "event_id": None,
                                "polarity": None, "support_spans": [], "note": None}
                               for q in case["candidates"]],
            "derived_fields": [], "missed_candidate_spans": [], "case_note": None}


def readable_packet(cases: list[dict]) -> str:
    lines = ["# 关系边独立盲标包", "", "只读允许的 facts/meta 视图。每个候选的标签填入各自 reviewer 模板；",
             "标注前不要查看银标、配对实验结果或 manifest 的选样层。", ""]
    for number, case in enumerate(cases, 1):
        lines.extend([f"## {number}. {case['id']}", "",
                      f"目标人：{case['target']}；别名：{', '.join(case['aliases']) or '无'}", "",
                      "### 可见原文", ""])
        for view in case["allowed_views"]:
            lines.extend([f"- `{view['id']}` `{view['type']}` [{view['start']},{view['end']}): "
                          + view["text"].replace("\n", " ⏎ "), ""])
        lines.extend(["### 数值/日期候选", "", "| ID | 类型 | 原文 | 坐标 |",
                      "| --- | --- | --- | --- |"])
        for q in case["candidates"]:
            raw = q["raw"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{q['candidate_id']}` | {q['type']} | {raw} | [{q['start']},{q['end']}) |")
        lines.append("")
    return "\n".join(lines)


def run(teacher_path: Path, originals_path: Path, silver_path: Path,
        paired_path: Path, out_dir: Path) -> dict:
    if out_dir.exists():
        raise ValueError("output_dir_already_exists")
    teachers = {r["id"]: r for r in rows(teacher_path)}
    originals = {r["id"]: r["text_full"] for r in rows(originals_path)}
    silver = {r["id"]: r for r in rows(silver_path)
              if r.get("metadata", {}).get("split") in {"train", "valid"}}
    paired = json.loads(paired_path.read_text("utf-8"))
    if paired.get("scope") != "train_valid_only" or paired.get("records") != len(silver):
        raise ValueError("paired_scope_mismatch")
    selection = choose(teachers, silver, paired)
    out_dir.mkdir(parents=True)
    cases = []
    for rid, _ in selection:
        inp = teachers[rid]
        text = originals[rid]
        if digest(text) != inp["source_sha256"]:
            raise ValueError("source_hash_mismatch")
        cases.append(review_case(inp, text))
    def write_jsonl(name: str, data: list[dict]) -> None:
        (out_dir / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in data), "utf-8")
    write_jsonl("blind-cases.jsonl", cases)
    forms = [blank_form(c) for c in cases]
    for name in ("reviewer-A-template.jsonl", "reviewer-B-template.jsonl"):
        write_jsonl(name, forms)
    (out_dir / "blind-review.md").write_text(readable_packet(cases), "utf-8")
    template = (Path(__file__).with_name("edge_review_ui_template.html")).read_text("utf-8")
    html = (template.replace("__CASES_JSON__", json.dumps(cases, ensure_ascii=False).replace("<", "\\u003c"))
                    .replace("__FORMS_JSON__", json.dumps(forms, ensure_ascii=False).replace("<", "\\u003c")))
    (out_dir / "blind-review.html").write_text(html, "utf-8")
    manifest = {"purpose": "optional_independent_human_edge_review", "status": "prepared_not_annotated",
                "selection_policy": "14 paired disagreements, 4 age operands, 6 deterministic controls; event-disjoint",
                "population_inference_allowed": False, "test_split_used": False,
                "input_sha256": {"teacher": hashlib.sha256(teacher_path.read_bytes()).hexdigest(),
                                 "originals": hashlib.sha256(originals_path.read_bytes()).hexdigest(),
                                 "silver": hashlib.sha256(silver_path.read_bytes()).hexdigest(),
                                 "paired": hashlib.sha256(paired_path.read_bytes()).hexdigest()},
                "counts": dict(Counter(s for _, s in selection)),
                "items": [{"id": rid, "stratum": stratum,
                           "source_sha256": teachers[rid]["source_sha256"],
                           "event_sha256": digest(silver[rid]["metadata"].get("event_id") or rid)}
                          for rid, stratum in selection],
                "private_packet_sha256": {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
                                          for name in ("blind-cases.jsonl", "reviewer-A-template.jsonl",
                                                       "reviewer-B-template.jsonl", "blind-review.md",
                                                       "blind-review.html")}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "paired", "out_dir"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    result = run(args.teacher, args.originals, args.silver, args.paired, args.out_dir)
    print(json.dumps({"counts": result["counts"], "cases": len(result["items"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
