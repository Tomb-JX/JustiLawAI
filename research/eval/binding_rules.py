"""主体/事件绑定规则（E-05 补充：Gate B 绑定表）。

多人案卷中，提取目标当事人的要素时，每段证据属于哪一类绑定：
- shared_fact：场景级事实，适用于在场所有人（如现场赌资总额、参赌人数、场所类型）
- target_specific：仅属于目标本人的事实（如本人持有的赌资、本人的角色、本人年龄）
- needs_review：绑定模糊，无法自动判定（需人工复核）

本模块是引擎侧唯一规则，后处理线 element_contract 应 import 或按此逻辑实现。

用法：
    from binding_rules import BindingType, classify_binding, classify_record_bindings
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class BindingType(str, Enum):
    SHARED = "shared_fact"
    TARGET = "target_specific"
    REVIEW = "needs_review"


class ReviewReason(str, Enum):
    """needs_review 的子类，用于诊断分析。"""
    NO_SUBJECT = "no_subject"      # 证据没提到任何人名 → 大概率 shared
    AMBIGUOUS = "ambiguous"        # 证据提到多人但无法区分 → 真正模糊
    IMPLICIT = "implicit"          # 证据用代词/隐含指代 → 需要共指消解
    FIELD_DEFAULT = "field_default"  # 字段级默认命中 target 但证据提到其他人
    UNKNOWN_FIELD = "unknown_field"  # 未知字段


# --- resolve_binding 可消费的绑定类型 ---
# shared_fact 是场景级事实（如现场赌资总额），resolve 应该接受。
# needs_review 暂不自动消费，留待人工或后续规则处理。
ACCEPT_IN_RESOLVE: tuple[str, ...] = ("lexical_candidate", "target_specific", "shared_fact")

# --- 字段级默认绑定类型 ---
# 有些字段天然属于场景级（shared），有些天然属于个人级（target），
# 有些取决于证据内容（需按规则判定）。

FIELD_DEFAULT_BINDING: dict[str, BindingType] = {
    # 场景级：这些字段的证据总是 shared_fact
    "amounts.onsite_stake_total": BindingType.SHARED,
    "amounts.cumulative_stake": BindingType.SHARED,
    "persons.participant_count": BindingType.SHARED,
    "persons.cumulative_participants": BindingType.SHARED,
    "persons.minors_involved": BindingType.SHARED,
    "persons.relatives_only": BindingType.SHARED,
    # civil_servant 和 abroad_organized_count 是关于目标本人的
    "persons.civil_servant": BindingType.TARGET,
    "persons.abroad_organized_count": BindingType.TARGET,
    "venue.venue_type": BindingType.SHARED,
    "conduct.method": BindingType.SHARED,
    # 个人级：这些字段的证据总是 target_specific
    "conduct.role": BindingType.TARGET,
    "conduct.cheating": BindingType.TARGET,
    "amounts.personal_stake": BindingType.TARGET,
    "amounts.per_bet": BindingType.TARGET,
    "amounts.commission": BindingType.TARGET,
    "amounts.illegal_gain": BindingType.TARGET,
    "intent.profit_purpose": BindingType.TARGET,
    "circumstances.last_prior_penalty_date": BindingType.TARGET,
    "circumstances.surrendered": BindingType.TARGET,
    "circumstances.truthful_statement": BindingType.TARGET,
    "circumstances.admits_and_accepts": BindingType.TARGET,
    "circumstances.remedied_consequence": BindingType.TARGET,
    "circumstances.victim_forgiveness": BindingType.TARGET,
    "circumstances.coerced_or_lured": BindingType.TARGET,
    "circumstances.meritorious": BindingType.TARGET,
    "circumstances.instigated_others": BindingType.TARGET,
    "circumstances.retaliation": BindingType.TARGET,
    "circumstances.obstructed_police": BindingType.TARGET,
    "circumstances.minor_circumstance": BindingType.TARGET,
    "circumstances.first_offense": BindingType.TARGET,
    "circumstances.violations_last_year": BindingType.TARGET,
    "person.age": BindingType.TARGET,
    "person.pregnant_or_nursing": BindingType.TARGET,
}

# 需要按证据内容判定的字段（无固定默认值）
FIELD_CONTENT_DEPENDENT: set[str] = {
    "conduct.behavior_type",  # 可能是"甲参与赌博"（target）或"甲等人赌博"（shared）
    "conduct.times",          # 可能是"甲赌博三次"（target）或"该赌场运营三个月"（shared）
    "conduct.duration_days",  # 同上
}


@dataclass(frozen=True)
class BindingResult:
    """一条证据的绑定判定结果。"""
    field: str
    binding_type: BindingType
    reason: str
    confidence: float = 1.0  # 1.0=确定, 0.5=推测, 0.0=无法判定
    review_reason: ReviewReason | None = None  # 仅 binding_type=REVIEW 时有值


def classify_binding(field: str, evidence_text: str, *,
                     target_mention: str,
                     all_subjects: tuple[str, ...] = ()) -> BindingResult:
    """判定一条证据的绑定类型。

    Args:
        field: 字段路径（如 "amounts.personal_stake"）
        evidence_text: 证据引文原文
        target_mention: 目标当事人的写法（如 "甲"）
        all_subjects: 案卷中所有当事人的写法（如 ("甲", "乙", "丙")）

    Returns:
        BindingResult
    """
    # 1. 字段级默认
    if field in FIELD_DEFAULT_BINDING:
        default = FIELD_DEFAULT_BINDING[field]
        # 即使有默认值，如果证据明确提到其他人而非目标，仍需审查
        if default == BindingType.TARGET and _mentions_others(evidence_text, target_mention, all_subjects):
            return BindingResult(field, BindingType.REVIEW,
                                 "个人级字段的证据提到了其他人", 0.5,
                                 ReviewReason.AMBIGUOUS)
        return BindingResult(field, default, f"字段默认绑定: {default.value}")

    # 2. 内容依赖字段
    if field in FIELD_CONTENT_DEPENDENT:
        return _classify_content_dependent(field, evidence_text, target_mention, all_subjects)

    # 3. 未知字段 → needs_review
    return BindingResult(field, BindingType.REVIEW, "未知字段，需人工判定", 0.0,
                         ReviewReason.UNKNOWN_FIELD)


def _mentions_others(text: str, target: str, all_subjects: tuple[str, ...]) -> bool:
    """证据是否提到了目标以外的其他人。"""
    for subj in all_subjects:
        if subj != target and subj in text:
            return True
    return False


def _classify_content_dependent(field: str, text: str, target: str,
                                all_subjects: tuple[str, ...]) -> BindingResult:
    """对内容依赖字段按证据文本判定绑定类型。"""
    # 行为类型判定
    if field == "conduct.behavior_type":
        # "甲参与赌博" → target；"甲、乙等人赌博" → shared
        if re.search(rf"{re.escape(target)}\s*(?:参与|实施|进行)", text):
            return BindingResult(field, BindingType.TARGET,
                                 f"证据描述 {target} 个人行为", 1.0)
        if _mentions_others(text, target, all_subjects):
            # 多人共同行为 → shared
            return BindingResult(field, BindingType.SHARED,
                                 "证据描述多人共同行为", 0.8)
        # 只提到目标 → target
        if target in text:
            return BindingResult(field, BindingType.TARGET,
                                 f"证据只提到 {target}", 0.9)
        # 没提到任何人 → needs_review (no_subject: 大概率 shared)
        return BindingResult(field, BindingType.REVIEW,
                             "行为描述未明确指向具体当事人", 0.3,
                             ReviewReason.NO_SUBJECT)

    # 次数/持续时间
    if field in ("conduct.times", "conduct.duration_days"):
        if target in text and not _mentions_others(text, target, all_subjects):
            return BindingResult(field, BindingType.TARGET,
                                 f"次数/时长描述仅指向 {target}", 0.9)
        if _mentions_others(text, target, all_subjects):
            return BindingResult(field, BindingType.SHARED,
                                 "次数/时长描述涉及多人", 0.7)
        return BindingResult(field, BindingType.REVIEW,
                             "次数/时长描述未明确指向", 0.3,
                             ReviewReason.NO_SUBJECT)

    return BindingResult(field, BindingType.REVIEW, "内容依赖字段无法自动判定", 0.0,
                         ReviewReason.UNKNOWN_FIELD)


def classify_record_bindings(record: dict, *,
                             target_mention: str,
                             all_subjects: tuple[str, ...] = ()) -> list[BindingResult]:
    """对一条记录的全部有值字段的全部证据做绑定判定。

    Args:
        record: {elements: {group: {field: {status, value, evidence}}}}
        target_mention: 目标当事人
        all_subjects: 所有当事人

    Returns:
        每段证据的绑定判定列表
    """
    results: list[BindingResult] = []
    elements = record.get("elements") or {}
    for group_name, group in elements.items():
        if not isinstance(group, dict):
            continue
        for field_name, item in group.items():
            if not isinstance(item, dict):
                continue
            if item.get("status") == "未提及" or item.get("value") is None:
                continue
            path = f"{group_name}.{field_name}"
            evidence = item.get("evidence") or []
            for ev in evidence:
                if isinstance(ev, dict) and isinstance(ev.get("quote"), str):
                    results.append(classify_binding(
                        path, ev["quote"],
                        target_mention=target_mention,
                        all_subjects=all_subjects))
    return results


def binding_summary(bindings: list[BindingResult]) -> dict:
    """汇总绑定判定结果，含 needs_review 子类分解。"""
    from collections import Counter
    counts = Counter(b.binding_type.value for b in bindings)
    review_reasons = Counter(b.review_reason.value for b in bindings
                             if b.binding_type == BindingType.REVIEW and b.review_reason)
    by_field: dict[str, dict] = {}
    for b in bindings:
        entry = by_field.setdefault(b.field, {"shared": 0, "target": 0, "review": 0, "items": []})
        entry[b.binding_type.value] = entry.get(b.binding_type.value, 0) + 1
        entry["items"].append({"type": b.binding_type.value, "reason": b.reason,
                                "confidence": b.confidence,
                                "review_reason": b.review_reason.value if b.review_reason else None})
    return {
        "total": len(bindings),
        "shared_fact": counts.get("shared_fact", 0),
        "target_specific": counts.get("target_specific", 0),
        "needs_review": counts.get("needs_review", 0),
        "needs_review_by_reason": dict(review_reasons),
        "by_field": by_field,
    }