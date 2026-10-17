"""I-20 要素教师契约的关键边界。"""
import json
from pathlib import Path

from app.discretion.element_labels import (FIELD_INFO, teacher_messages,
                                           teacher_output_schema, validate_teacher_output)
from app.discretion.schema import iter_fields


def blank():
    out = {}
    for path in FIELD_INFO:
        group, name = path.split(".")
        out.setdefault(group, {})[name] = {"status": "未提及", "value": None, "evidence": []}
    return out


def test_schema_tracks_ontology():
    schema = teacher_output_schema()
    assert len(FIELD_INFO) == len(list(iter_fields())) == 36
    assert len(schema["properties"]) == 7
    assert len(teacher_output_schema(located=True)["properties"]["conduct"]
               ["properties"]["role"]["properties"]["evidence"]["items"]["required"]) == 3
    fixture_root = Path(__file__).resolve().parents[3] / "research" / "eval" / "fixtures"
    for name, located in (("element-teacher-v1.schema.json", False),
                          ("element-located-v1.schema.json", True)):
        assert json.loads((fixture_root / name).read_text("utf-8")) == teacher_output_schema(located=located)
    assert json.loads((fixture_root / "element-empty-v1.json").read_text("utf-8")) == blank()


def test_absent_and_original_offsets():
    full = "甲在棋牌室参赌，赌资一万元以上。"
    out = blank()
    assert validate_teacher_output(out, evidence_text=full, located=True) == []
    quote = "赌资一万元以上"
    start = full.index(quote)
    out["amounts"]["personal_stake"] = {
        "status": "明确", "value": {"min": 10000, "max": None},
        "evidence": [{"quote": quote, "start": start, "end": start + len(quote)}]}
    assert validate_teacher_output(out, evidence_text=full, located=True) == []
    out["amounts"]["personal_stake"]["evidence"][0]["end"] -= 1
    assert "evidence_offset_mismatch" in {i.code for i in validate_teacher_output(
        out, evidence_text=full, located=True)}


def test_prompt_target_and_profit_guard():
    messages = teacher_messages(target="甲", aliases=("甲某",), facts_text="甲收台费。")
    assert "只收台费" in messages[0]["content"]
    assert "同一人的其他写法：甲某" in messages[1]["content"]
    assert "处罚决定" not in messages[1]["content"]
