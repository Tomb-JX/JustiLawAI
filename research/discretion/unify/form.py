"""form 真值判别（parse-format-chain-design v1.2 §5.2，Q1 决策：S0 确定性标记，严禁模型预测）。

八值枚举（pkulaw 现有三值为子集，映射兼容）：
叙述式-独立成篇 / 叙述式-结果栏内 / 字段表公示 / 标题汇总公示 / 叙述式-复议 / 判决书 / 混合-弱模板 / 合作案卷
"""

from __future__ import annotations

import re

FORMS = [
    "叙述式-独立成篇", "叙述式-结果栏内", "字段表公示", "标题汇总公示",
    "叙述式-复议", "判决书", "混合-弱模板", "合作案卷",
]

# 字段表模板词（web 实测词表，design §4.2；命中以"词+冒号/换行/行首"为准）
LABEL_WORDS = [
    "违法事实", "行政处罚事由", "处罚事由", "处罚事项", "简要案情", "主要违法事实", "案件情况",
    "处罚依据", "行政处罚依据", "法律依据", "违反的法律条款",
    "处罚内容", "处罚结果", "处理结果", "处罚类别", "处罚种类", "罚款金额", "案件名称",
    "决定书文号", "文书号", "处罚决定日期", "决定日期", "执法主体名称", "处罚机关",
    "违法嫌疑人", "当事人", "被处罚人", "行政处罚", "行政处罚决定书正文",
]
# 注意：主题词（赌博）不在标签词表——"赌博案"是标题汇总式的标题，不是字段标签

TITLE_SUMMARY = re.compile(r"^[一-龥]{1,4}[某某]{1,2}(?:等人?)?赌博案$")


def _label_hits(text: str) -> int:
    lines = text.split("\n")
    hit = 0
    for w in LABEL_WORDS:
        if (w + "：") in text or (w + ":") in text or (w + "\n") in text:
            hit += 1
            continue
        if any(ln.startswith(w) for ln in lines):
            hit += 1
    return hit


def _is_title_summary(text: str) -> bool:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    title_lines = sum(1 for ln in lines if TITLE_SUMMARY.match(ln))
    colon_lines = sum(1 for ln in lines if "：" in ln or ":" in ln)
    return title_lines >= 1 and colon_lines == 0


def detect_form(source_type: str, text: str, pku_form: str = "") -> str:
    """确定性判别。pkulaw 渠道的 quality.form 已是真值（叙述式-独立成篇/叙述式-结果栏内/字段式公示），
    直接复用；web 渠道按规则判别。"""
    if source_type == "行政复议决定书":
        return "叙述式-复议"
    if source_type == "行政判决书":
        return "判决书"
    if source_type == "合作案卷":
        return "合作案卷"
    if pku_form in ("叙述式-独立成篇", "叙述式-结果栏内", "字段式公示"):
        return pku_form
    # 标签密集（≥3）即字段表形态，不要求 source_type=执法公示——
    # 网页渠道把字段表页/列表页误标成处罚决定书的泄漏由 form 层兜住（实测 L1/L2 仅 8 件翻形，全为目标）
    if _label_hits(text) >= 3:
        return "字段表公示"
    if source_type in ("处罚决定书", "不予处罚决定书"):
        return "叙述式-独立成篇"
    if source_type == "执法公示":
        hits = _label_hits(text)
        if hits >= 3:
            return "字段表公示"
        if _is_title_summary(text):
            return "标题汇总公示"
        return "混合-弱模板"
    return "混合-弱模板"
