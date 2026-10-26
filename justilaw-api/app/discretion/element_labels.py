"""I-20 要素教师输出契约；只定义提示、结构与证据校验，不调用模型。

一条输入记录只对应一名本人。调用方提供 seg-v2 的 facts 与位于 facts 前的
meta/当事人句，绝不能把 reasoning、decision、review 当成事实输入。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import get_args

from .schema import AmountRange, GROUPS, SCHEMA_VERSION, iter_fields

PROMPT_VERSION = "element-v1"
STATUSES = ("明确", "推断", "未提及")
# 指南 v0.2 裁定"值记 null、状态推断"的模糊量值字段（其余字段推断时值必须可定）
NULLABLE_WHEN_INFERRED = ("conduct.times", "persons.participant_count", "person.age")
FIELD_INFO = {path: (description, next(t for t in get_args(typ) if t is not type(None))
                               if get_args(typ) else typ)
              for path, description, typ in iter_fields()}


@dataclass(frozen=True)
class LabelIssue:
    code: str
    field: str
    message: str


def _value_schema(typ: type) -> dict:
    if isinstance(typ, type) and issubclass(typ, Enum):
        return {"type": "string", "enum": [member.value for member in typ]}
    if typ is AmountRange:
        return {"type": "object", "properties": {
            "min": {"type": "number", "minimum": 0},
            "max": {"type": ["number", "null"], "minimum": 0},
        }, "required": ["min", "max"], "additionalProperties": False}
    if typ is date:
        return {"type": "string", "format": "date"}
    if typ is bool:
        return {"type": "boolean"}
    if typ is int:
        return {"type": "integer", "minimum": 0}
    if typ is float:
        return {"type": "number", "minimum": 0}
    raise TypeError(f"未支持的要素值类型: {typ}")


def teacher_output_schema(*, located: bool = False) -> dict:
    """七组字段全量输出；located=True 是 S2 定位后的入库契约。"""
    groups: dict[str, dict] = {}
    for path, (description, typ) in FIELD_INFO.items():
        group, name = path.split(".")
        group_schema = groups.setdefault(group, {"type": "object", "properties": {},
                                                   "required": [], "additionalProperties": False})
        group_schema["properties"][name] = {
            "type": "object", "description": description,
            "properties": {
                "status": {"type": "string", "enum": list(STATUSES)},
                "value": {"anyOf": [_value_schema(typ), {"type": "null"}]},
                "evidence": {"type": "array", "items": {"type": "object", "properties": {
                    "quote": {"type": "string", "minLength": 1},
                    **({"start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1}} if located else {})},
                    "required": ["quote", "start", "end"] if located else ["quote"],
                    "additionalProperties": False}},
            },
            "required": ["status", "value", "evidence"], "additionalProperties": False,
        }
        group_schema["required"].append(name)
    return {"type": "object", "properties": groups, "required": list(GROUPS),
            "additionalProperties": False}


def teacher_system_prompt() -> str:
    lines = [f"{path}：{description}" for path, (description, _) in FIELD_INFO.items()]
    return "\n".join([
        f"你是行政赌博案件要素标注教师。只输出符合 element-v1 / schema {SCHEMA_VERSION} 的 JSON。",
        "一条记录只标一名目标当事人；aliases 仅是同一人的不同写法，不是其他参赌人。",
        "只读给定的当事人/事实句；不得借处罚决定、说理、所引法条、机关信封或常识补事实。",
        "每个字段都输出 {status,value,evidence}；状态只用 明确/推断/未提及。",
        "未提及时 value=null、evidence=[]；有值时 evidence 为逐字连续引文数组，每项仅含 quote，不输出坐标。",
        "未提及是正常且常见的结果；原文没有本人专属信息时不要猜，也不要从处罚结果反推。",
        "金额用元的 {min,max}：确数两者相同；'以上/逾/超过/至少/不低于'只写下界，max=null，不补上界。",
        "只收台费/场地费可记 commission，但不证明 profit_purpose；营利目的严格按字段说明。",
        "年龄与前科优先看当事人句；当事人句缺失时不得从其他人的身份或处罚推断。",
        "全部字段必须出现，且只出现下列字段：", *lines,
    ])


def teacher_messages(*, target: str, facts_text: str, meta_text: str = "",
                     aliases: tuple[str, ...] = ()) -> list[dict[str, str]]:
    """供网页线 S1 客户端直接接入；meta 只允许 facts 前的当事人/身份句。"""
    if not target.strip():
        raise ValueError("subject_mention/target 不能为空，不能按整篇匿名猜本人")
    if not (facts_text.strip() or meta_text.strip()):
        raise ValueError("当事人句与事实句不能同时为空")
    alias_line = "、".join(a for a in aliases if a and a != target) or "无"
    user = (f"目标当事人：{target}\n同一人的其他写法：{alias_line}\n"
            f"当事人/身份句：\n{meta_text or '（原文未提供）'}\n"
            f"事实句：\n{facts_text or '（原文未提供）'}")
    return [{"role": "system", "content": teacher_system_prompt()},
            {"role": "user", "content": user}]


def _valid_value(value: object, typ: type) -> bool:
    if isinstance(typ, type) and issubclass(typ, Enum):
        return isinstance(value, str) and value in {member.value for member in typ}
    if typ is AmountRange:
        if not isinstance(value, dict) or set(value) != {"min", "max"}:
            return False
        lo, hi = value["min"], value["max"]
        return (_nonnegative_number(lo) and (hi is None or _nonnegative_number(hi))
                and (hi is None or lo <= hi))
    if typ is date:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return False
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    if typ is bool:
        return type(value) is bool
    if typ is int:
        return type(value) is int and value >= 0
    if typ is float:
        return _nonnegative_number(value)
    return False


def _nonnegative_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_teacher_output(payload: object, *, evidence_text: str,
                            located: bool = False) -> list[LabelIssue]:
    """教师初稿校验 quote；located=True 时验收 S2 原文坐标和逐字回放。"""
    issues: list[LabelIssue] = []
    if not isinstance(payload, dict):
        return [LabelIssue("bad_root", "", "输出必须为七组对象")]
    for group in set(payload) - set(GROUPS):
        issues.append(LabelIssue("unknown_group", group, "非本体分组"))
    for group in GROUPS:
        fields = payload.get(group)
        if not isinstance(fields, dict):
            issues.append(LabelIssue("missing_group", group, "缺少分组对象"))
            continue
        expected = {p.split(".")[1] for p in FIELD_INFO if p.startswith(group + ".")}
        for name in set(fields) - expected:
            issues.append(LabelIssue("unknown_field", f"{group}.{name}", "非本体字段"))
        for name in expected:
            path = f"{group}.{name}"
            if name not in fields:
                issues.append(LabelIssue("missing_field", path, "必须显式标未提及"))
                continue
            item = fields[name]
            if not isinstance(item, dict) or set(item) != {"status", "value", "evidence"}:
                issues.append(LabelIssue("bad_field_shape", path, "字段须含且只含 status/value/evidence"))
                continue
            status, value, evidence = item["status"], item["value"], item["evidence"]
            if status not in STATUSES:
                issues.append(LabelIssue("bad_status", path, "状态不在三值枚举中"))
            if status == "未提及":
                if value is not None or evidence != []:
                    issues.append(LabelIssue("absent_inconsistent", path, "未提及时值应为空且无证据"))
                continue
            if status not in STATUSES:
                continue
            if value is None and status == "推断" and path in NULLABLE_WHEN_INFERRED:
                pass  # 指南 v0.2 裁定：'多次/数人''三十余岁'等模糊量值记 null、状态推断，仍须附据以推断的原文
            elif not _valid_value(value, FIELD_INFO[path][1]):
                issues.append(LabelIssue("bad_value", path, "值类型或取值不符合 schema"))
            if not isinstance(evidence, list) or not evidence:
                issues.append(LabelIssue("evidence_missing", path, "有值时须附逐字证据"))
                continue
            for ev in evidence:
                expected_keys = {"quote", "start", "end"} if located else {"quote"}
                if not isinstance(ev, dict) or set(ev) != expected_keys or not isinstance(ev["quote"], str):
                    issues.append(LabelIssue("bad_evidence_shape", path, "证据键或引文类型不符"))
                    continue
                if not ev["quote"].strip() or ev["quote"] not in evidence_text:
                    issues.append(LabelIssue("evidence_not_found", path, "引文不在核对文本中"))
                if located:
                    start, end = ev["start"], ev["end"]
                    if (type(start) is not int or type(end) is not int or start < 0 or end <= start
                            or evidence_text[start:end] != ev["quote"]):
                        issues.append(LabelIssue("evidence_offset_mismatch", path, "S2 原文坐标切不出引文"))
    return issues
