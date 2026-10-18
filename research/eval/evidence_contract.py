"""证据语义校验契约（E-05 批准包）。

本模块是标注指南 §3.10 的代码级权威实现。
后处理线（Codex element_contract）应 import 本模块或将逻辑复制到
element_contract 中（保持行为一致）。

用法：
    from evidence_contract import EvidenceValidator, EvidenceIssue

Codex 对接：element_contract 在 S2 定位后、入库前调用
EvidenceValidator.validate_record() 校验证据合规性。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# 证据来源限制：只能来自 facts_text 和 meta_text，不能来自
# reasoning_text / decision_text / 法条引用
_FORBIDDEN_SOURCES = ("reasoning_text", "decision_text", "review_text", "law_text")

# 字段信息：哪些字段是事实型（证据来自 facts），哪些是当事人型（证据来自 meta）
# 这是一个保守的映射——meta 字段的证据也可以出现在 facts 中
_META_FIELDS = {"person.age", "person.pregnant_or_nursing",
                "circumstances.last_prior_penalty_date",
                "persons.civil_servant"}

# 指南 v0.2 裁定："多次/数人""三十余岁"等模糊量值记 null、状态推断（仍须附据以推断的原文）。
# 须与 justilaw-api app/discretion/element_labels.py NULLABLE_WHEN_INFERRED 保持一致。
NULLABLE_WHEN_INFERRED = ("conduct.times", "persons.participant_count", "person.age")


@dataclass(frozen=True)
class EvidenceIssue:
    """一条证据校验问题。"""
    code: str           # 问题代码
    field: str          # 字段路径（如 "conduct.role"）
    message: str        # 人话描述
    severity: str = "error"  # error | warning


class EvidenceValidator:
    """证据语义校验器（引擎侧唯一契约）。

    规则（标注指南 §3.10）：
    1. 逐字连续：证据必须是原文中的连续片段，逐字摘录，不得改写、拼接或省略。
    2. 来源限制：证据只能来自 facts_text 和 meta_text。
    3. 多段证据：一个值需要多处原文支持时，附多段证据。
    4. 坐标定位（S2）：located=True 时，text_full[start:end] == quote。
    5. 推断时的证据：状态为"推断"时，证据是据以推断的原文。
    6. 未提及时无证据：状态为"未提及"时，evidence 必须为空数组。
    """

    def validate_record(self, record: dict, *, located: bool = True) -> list[EvidenceIssue]:
        """校验一条记录的全部证据。

        Args:
            record: {id, input:{text_full, facts_text, meta_text}, elements:{七组}}
            located: True 时校验 S2 坐标。

        Returns:
            问题列表（空 = 通过）。
        """
        issues: list[EvidenceIssue] = []
        inp = record.get("input") or {}
        text_full = inp.get("text_full") or ""
        facts_text = inp.get("facts_text") or ""
        meta_text = inp.get("meta_text") or ""
        elements = record.get("elements") or {}

        for group_name, group in elements.items():
            if not isinstance(group, dict):
                continue
            for field_name, item in group.items():
                if not isinstance(item, dict):
                    continue
                path = f"{group_name}.{field_name}"
                issues.extend(self._validate_field(
                    path, item, text_full=text_full,
                    facts_text=facts_text, meta_text=meta_text, located=located))
        return issues

    def _validate_field(self, path: str, item: dict, *,
                        text_full: str, facts_text: str, meta_text: str,
                        located: bool) -> list[EvidenceIssue]:
        issues: list[EvidenceIssue] = []
        status = item.get("status")
        value = item.get("value")
        evidence = item.get("evidence")

        # 规则 6：未提及时无证据
        if status == "未提及":
            if value is not None:
                issues.append(EvidenceIssue(
                    "absent_with_value", path,
                    "状态为'未提及'时值必须为空"))
            if evidence and evidence != []:
                issues.append(EvidenceIssue(
                    "absent_with_evidence", path,
                    "状态为'未提及'时 evidence 必须为空数组"))
            return issues

        # 有值时必须有证据
        if status in ("明确", "推断"):
            if value is None and not (status == "推断" and path in NULLABLE_WHEN_INFERRED):
                issues.append(EvidenceIssue(
                    "present_without_value", path,
                    "状态为'明确'或'推断'时必须给出值"))
                return issues
            if not isinstance(evidence, list) or not evidence:
                issues.append(EvidenceIssue(
                    "present_without_evidence", path,
                    "有值时必须附原文证据"))
                return issues

        # 逐条校验证据
        for idx, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                issues.append(EvidenceIssue(
                    "bad_evidence_shape", path,
                    f"evidence[{idx}] 必须是对象"))
                continue

            quote = ev.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                issues.append(EvidenceIssue(
                    "empty_quote", path,
                    f"evidence[{idx}].quote 必须为非空字符串"))
                continue

            # 规则 1：逐字连续——引文必须在 text_full 中
            if quote not in text_full:
                issues.append(EvidenceIssue(
                    "quote_not_in_text", path,
                    f"evidence[{idx}].quote 不在 text_full 中"))
                continue

            # 规则 2：来源限制——引文必须在 facts_text 或 meta_text 中
            if quote not in facts_text and quote not in meta_text:
                issues.append(EvidenceIssue(
                    "quote_forbidden_source", path,
                    f"evidence[{idx}].quote 不在 facts_text 或 meta_text 中"
                    f"（可能来自 reasoning/decision/法条）"))

            # 规则 4：S2 坐标校验
            if located:
                start = ev.get("start")
                end = ev.get("end")
                if type(start) is not int or type(end) is not int:
                    issues.append(EvidenceIssue(
                        "missing_offsets", path,
                        f"evidence[{idx}] 缺少 start/end 整数坐标"))
                elif start < 0 or end <= start:
                    issues.append(EvidenceIssue(
                        "invalid_offsets", path,
                        f"evidence[{idx}] start/end 不合法（start={start}, end={end}）"))
                elif start >= len(text_full) or end > len(text_full):
                    issues.append(EvidenceIssue(
                        "offsets_out_of_range", path,
                        f"evidence[{idx}] start/end 超出 text_full 范围"))
                elif text_full[start:end] != quote:
                    issues.append(EvidenceIssue(
                        "offset_mismatch", path,
                        f"evidence[{idx}] text_full[{start}:{end}] ≠ quote"))

        return issues

    def validate_batch(self, records: list[dict], *, located: bool = True) -> dict:
        """批量校验，返回聚合报告。

        Returns:
            {total, passed, failed, issue_counts, issues}
        """
        all_issues: list[dict] = []
        for rec in records:
            rid = rec.get("id", "?")
            issues = self.validate_record(rec, located=located)
            for iss in issues:
                all_issues.append({"id": rid, "field": iss.field,
                                   "code": iss.code, "message": iss.message,
                                   "severity": iss.severity})
        from collections import Counter
        counts = Counter(i["code"] for i in all_issues)
        failed_ids = {i["id"] for i in all_issues if i["severity"] == "error"}
        return {
            "total": len(records),
            "passed": len(records) - len(failed_ids),
            "failed": len(failed_ids),
            "issue_counts": dict(counts),
            "issues": all_issues,
        }