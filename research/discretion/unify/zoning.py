"""确定性分区（parse-interface-v2-design §2.4 的落地，最小有效规模路线）：

公示族（字段表公示/标题汇总公示/混合-弱模板）不走模型分区——正则侧对它们的
facts/decision 抽取依赖确定性标签，本就可靠；把 parsed-1 的正则分段（原文坐标）
映射到句表（seg-v2 的坐标基座），直接生成 zones。模型在该形态只做字段抽取。

收益：公示族 ~1,100 件零分区调用（成本/时延/稳定性三收）；facts 区间缺失类失败
（试点 99 件中 87 件属公示族）结构性消除。叙述式仍走模型分区（语义边界）。
"""

from __future__ import annotations

from locate import OffsetIndex  # noqa: F401  保留：模型侧对照仍用

SEG_TYPES = ["facts", "evidence", "reasoning", "decision", "review"]


FACTS_LABELS = ["违法事实", "主要违法事实", "简要案情", "案件情况", "行政处罚事由", "处罚事由", "处罚事项"]
DECISION_LABELS = ["处罚依据", "行政处罚依据", "法律依据", "处罚内容", "处罚结果", "处理结果", "罚款金额"]
META_LABELS = ["案件名称", "决定书文号", "文书号", "处罚决定日期", "决定日期", "执法主体名称", "处罚机关",
               "证件类型", "证件号", "身份证", "当事人", "违法嫌疑人", "被处罚人", "决定书名称", "行政处罚"]


def _label_type(s: str) -> str | None:
    """句首标签词 → 段类型。"""
    s = s.strip()
    for w in FACTS_LABELS:
        if s.startswith(w):
            return "facts"
    for w in DECISION_LABELS:
        if s.startswith(w):
            return "decision"
    for w in META_LABELS:
        if s.startswith(w):
            return "meta"
    return None


def _label_mode_zones(sentences: list, cleaned: str) -> list[dict] | None:
    """标签模式兜底（正则 facts 坐标缺失时）：标签行开启同型区间，无标签行归入当前开区间
    （facts 值行跟随其标签行），首个标签前与仍无类型的句子归 meta。"""
    types: dict[int, str] = {}
    open_type = None
    for sid, (a, b) in enumerate(sentences, 1):
        s = (cleaned or "")[a:b].strip()
        t = _label_type(s)
        if t:
            open_type = t
            types[sid] = t
        elif open_type:
            types[sid] = open_type
        else:
            types[sid] = "meta"
    if not any(t != "meta" for t in types.values()):
        return None
    zones: list[dict] = []
    i = 1
    n = len(sentences)
    while i <= n:
        t = types.get(i, "meta")
        j = i
        while j + 1 <= n and types.get(j + 1, "meta") == t:
            j += 1
        zones.append({"type": t, "from": i, "to": j})
        i = j + 1
    return zones


def deterministic_zones(regex_segments: dict, sentences: list, o2c, cleaned: str = "") -> list[dict] | None:
    """正则分段（原文坐标）→ 句号分区 zones。

    规则：句子与正则 facts/decision/review/evidence/reasoning 区间有重叠即归该类型
    （facts 优先序在循环序里）；无任何重叠的句子归 meta。输出保证铺满句表（结构性）。
    o2c(orig_span) -> clean_span|None：原文→cleaned 坐标映射（来自 CleanResult.kept_intervals）。
    regex_segments 为 parsed-1 记录的 segments（键 text_facts 等）。正则 facts 缺失时
    回退标签模式（句首标签词判型），标签也判不出才返回 None（交模型或队列）。
    """
    clean_spans: dict[str, list[tuple[int, int]]] = {}
    for typ in SEG_TYPES:
        pos = regex_segments.get(f"text_{typ}")
        if isinstance(pos, list) and len(pos) == 2 and pos[1] > pos[0]:
            got = o2c(tuple(pos))
            if got:
                clean_spans.setdefault(typ, []).append(got)
    if not clean_spans.get("facts"):
        got = _label_mode_zones(sentences, cleaned)
        if got is not None:
            return got
        return None   # 标签模式也判不出（交模型或队列）

    zones: list[dict] = []
    i = 1
    n = len(sentences)

    def type_of(sid: int) -> str:
        a, b = sentences[sid - 1]
        for typ in SEG_TYPES:
            for cs, ce in clean_spans.get(typ, []):
                if a < ce and b > cs:
                    return typ
        return "meta"

    while i <= n:
        typ = type_of(i)
        j = i
        while j + 1 <= n and type_of(j + 1) == typ:
            j += 1
        zones.append({"type": typ, "from": i, "to": j})
        i = j + 1
    return zones


def is_public_form(form: str) -> bool:
    """公示族判定：字段表公示/标题汇总公示/混合-弱模板（source_type=执法公示的确定性形态）。"""
    return any(k in form for k in ("字段表公示", "标题汇总公示", "混合-弱模板"))


def merge_fact_fallback(zones: list[dict], sentences: list, facts_span) -> list[dict] | None:
    """模型漏标 facts 区间时的兜底：正则 facts 参照（clean 坐标）内的句子中，
    meta/未分类的改标 facts——语义判断句（reasoning 等）保留不改。
    返回新 zones；无可用改标时返回 None（调用方送队列）。"""
    if not facts_span:
        return None
    a, b = facts_span
    types: dict[int, str] = {}
    for z in (zones or []):
        for s in range(z["from"], z["to"] + 1):
            types[s] = z["type"]
    changed = False
    for sid in range(1, len(sentences) + 1):
        sa, sb = sentences[sid - 1]
        if a < sb and b > sa and types.get(sid, "meta") == "meta":
            types[sid] = "facts"
            changed = True
    if "facts" not in types.values():
        return None
    if not changed:
        return zones
    out: list[dict] = []
    sids = sorted(types)
    i = 0
    while i < len(sids):
        j = i
        while j + 1 < len(sids) and sids[j + 1] == sids[j] + 1 and types[sids[j + 1]] == types[sids[i]]:
            j += 1
        out.append({"type": types[sids[i]], "from": sids[i], "to": sids[j]})
        i = j + 1
    return out
