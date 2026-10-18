"""Engine-owned element semantics with a versioned sentence-reference wire format.

No ontology or acceptance threshold is defined here. element-ref-v2 is a transport
version, NOT a declaration that the engine has approved an element-v2 ontology.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

WIRE_VERSION = "element-ref-v2"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def engine_contract():
    # An explicit path is mandatory outside the known sibling-worktree layout.
    sibling = Path(__file__).resolve().parents[3].parent / "discretion-engine/justilaw-api"
    path = Path(os.environ.get("JUSTILAW_ENGINE_API") or sibling)
    if not (path / "app/discretion/element_labels.py").is_file():
        raise RuntimeError("引擎契约不可达；设 JUSTILAW_ENGINE_API，不得在网页侧重定义字段")
    sys.path.insert(0, str(path))
    module = importlib.import_module("app.discretion.element_labels")
    actual = Path(module.__file__).resolve()
    if actual != (path / "app/discretion/element_labels.py").resolve():
        raise RuntimeError("已加载其他引擎契约；在新进程中固定 JUSTILAW_ENGINE_API")
    return module


def contract_snapshot(engine) -> dict:
    paths = [Path(engine.__file__), Path(engine.__file__).with_name("schema.py"),
             Path(engine.__file__).with_name("extract.py")]
    here = Path(__file__).resolve().parent
    dependencies = [here.parent / "harvest/parse.py", here.parent / "harvest/parse_qc.py",
                    Path(engine.__file__).resolve().parents[3] / "research/eval/key_field_presence.py"]
    from s1 import data_root
    caps = data_root() / "config/legal_caps.json"
    dependencies.append(caps)
    return {"wire_version": WIRE_VERSION, "engine_prompt_version": engine.PROMPT_VERSION,
            "engine_schema_version": engine.SCHEMA_VERSION,
            "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            "implementation": implementation_snapshot(),
            "dependencies": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in dependencies if p.is_file()}}


def implementation_snapshot() -> dict:
    # Freeze local prompts, projection, normalization and billing code as well as
    # the engine schema. A transport version alone cannot identify these changes.
    here = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(here.glob("*.py"))}


def reference_schema(engine) -> dict:
    schema = copy.deepcopy(engine.teacher_output_schema())
    for path in engine.FIELD_INFO:
        group, name = path.split(".")
        item = schema["properties"][group]["properties"][name]
        item["properties"]["evidence"] = {
            "type": "array", "items": {"type": "object", "properties": {
                "sentence_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                 "items": {"type": "string", "minLength": 1}}},
                "required": ["sentence_ids"], "additionalProperties": False}}
        item["allOf"] = [{"if": {"properties": {"status": {"const": "未提及"}}},
                          "then": {"properties": {"value": {"type": "null"},
                                                    "evidence": {"maxItems": 0}}},
                          "else": {"properties": {"value": {"not": {"type": "null"}},
                                                    "evidence": {"minItems": 1}}}}]
    return schema


def messages(engine, inp: dict, *, decisions: list | None = None) -> list[dict]:
    # Always transmit the complete engine value schema, including enums.
    from contract_bundle import make_bundle
    bundle = make_bundle(engine)
    schema = bundle['output_schema']
    system = bundle['prompt'] + (
        "\n【传输契约覆盖】证据不抄引文、不算坐标，只选本次允许句的 sentence_ids。"
        "不得引用其他记录或范围外句。未提及须由已读输入支持，缺字段不等于未提及。"
        "按下面完整 JSON Schema 输出七组对象，禁止平铺、包裹或额外键。\n"
        + json.dumps(schema, ensure_ascii=False))
    user = {"target": inp["target"], "aliases": inp["aliases"], "contract_bundle_hash": bundle['hash'],
            "allowed_sentences": inp["sentence_view"]}
    if decisions is not None:
        # C emits complete fields under the same schema, with exactly the same view.
        user["disagreements"] = decisions
        user["instruction"] = "独立依据本人的允许句重标全部字段；可纠正两候选，但新值必须给自己的有效引用。"
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def compile_references(payload: object, inp: dict, text_full: str, engine) -> dict:
    """Validate wire types, compile allowed IDs, then run the engine's final validator."""
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(reference_schema(engine)).iter_errors(payload),
                    key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError("wire_schema:" + ";".join(f"{list(e.path)}:{e.validator}" for e in errors[:10]))
    allowed = {s["id"]: s for s in inp["sentence_view"]}
    result = copy.deepcopy(payload)
    for group in result.values():
        for field in group.values():
            evidence = []
            seen = set()
            for ev in field["evidence"]:
                for sid in ev["sentence_ids"]:
                    if sid not in allowed:
                        raise ValueError(f"reference_not_allowed:{sid}")
                    s = allowed[sid]
                    a, b = s["start"], s["end"]
                    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text_full):
                        raise ValueError("reference_out_of_bounds")
                    if text_full[a:b] != s["text"]:
                        raise ValueError("reference_source_mismatch")
                    if (a, b) not in seen:
                        evidence.append({"quote": text_full[a:b], "start": a, "end": b})
                        seen.add((a, b))
            field["evidence"] = evidence
    issues = engine.validate_teacher_output(result, evidence_text=text_full, located=True)
    if issues:
        raise ValueError("engine_validation:" + ";".join(f"{i.field}:{i.code}" for i in issues))
    check_money_support(result)
    return result


def check_money_support(payload):
    """Local monetary grounding only, NOT a claim of semantic entailment.

    Existing engine rules decide ranges. Unsupported forms are quarantined rather
    than borrowing a different amount from the rest of the document.
    """
    from app.discretion.extract import parse_amount
    from s3 import _text_numbers
    tokens = re.compile(r"(?:约|近|超过|至少|逾|不足|不低于)?[0-9０-９〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟两.,，]+[余多]?元(?:以上|以下)?")
    for name, item in payload.get("amounts", {}).items():
        if item["status"] == "未提及":
            continue
        supported = set()
        for ev in item["evidence"]:
            for match in tokens.finditer(ev["quote"]):
                value = parse_amount(match.group())
                if value is not None:
                    supported.add((value.min, value.max))
                else:
                    # Exact upper/lowercase numerals supported by the existing S3 parser.
                    if not re.search(r"约|近|超过|至少|逾|不足|以上|以下|余|多", match.group()):
                        supported.update((n, n) for n in _text_numbers(match.group(), "元"))
        value = item["value"]
        if (value["min"], value["max"]) not in supported:
            raise ValueError(f"numeric_evidence_unsupported:amounts.{name}")


def validate_located(payload, text_full: str, engine, regions=()) -> None:
    issues = engine.validate_teacher_output(payload, evidence_text=text_full, located=True)
    if issues:
        raise ValueError("invalid_candidate:" + ";".join(f"{i.field}:{i.code}" for i in issues))
    for group in payload.values():
        for item in group.values():
            for ev in item["evidence"]:
                if regions and not any(a <= ev["start"] < ev["end"] <= b for a, b in regions):
                    raise ValueError("evidence_outside_input")
    check_money_support(payload)


def merge_valid(a: dict, b: dict, engine, text_full: str, regions=(), c=None):
    """Keep the existing strict comparison; never default missing/invalid fields to absent."""
    validate_located(a, text_full, engine, regions)
    validate_located(b, text_full, engine, regions)
    if c is not None:
        validate_located(c, text_full, engine, regions)
    merged, differences, unresolved = {}, [], []
    for path in engine.FIELD_INFO:
        group, name = path.split(".")
        va, vb = a[group][name], b[group][name]
        def key(v):
            return (v["status"], digest(v["value"]),
                    frozenset((e["start"], e["end"]) for e in v["evidence"]))
        if key(va) == key(vb):
            chosen = va
        else:
            kind = ("status_difference" if va["status"] != vb["status"] else
                    "value_difference" if digest(va["value"]) != digest(vb["value"]) else "evidence_only")
            d = {"path": path, "kind": kind, "a": va, "b": vb}
            differences.append(d)
            if c is None:
                unresolved.append(d)
                continue
            chosen = c[group][name]
        merged.setdefault(group, {})[name] = copy.deepcopy(chosen)
    if not unresolved:
        validate_located(merged, text_full, engine, regions)
    return merged, unresolved, differences
