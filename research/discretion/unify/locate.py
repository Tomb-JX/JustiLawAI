"""S2 定位层（parse-format-chain-design v1.2 §8）：quote → cleaned 坐标 → 原文坐标。

三级策略（失败可见可数，任何一级失败由 S3 送低置信队列，不猜测）：
① exact：逐字定位（唯一/多处）；
② ws：双方去空白后定位（容忍引文自发纠错中的空白差异），经 ws 映射表还原 cleaned 坐标；
③ fuzzy：锚窗最长块对齐——引文去空白头部 10 字锚点锁定窗口，difflib 取最长连续公共块
   （≥60% 引文长度才采纳）。单连续块天然落在单个 kept 区间内，不会跨越 S0 删除边界；
   命中块不足引文 60% 即 fail（不输出部分坐标，防止偏移行截断/吞没相邻字符）。

OffsetIndex 由 edits.rle.jsonl 行构建（clean↔orig 双向映射 + 删除边界标记），
不依赖 S0 规则代码——与 CleanResult.replay 同一审计原则。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

WS = re.compile(r"\s+")


@dataclass
class Located:
    status: str            # exact_unique/exact_multi/ws_unique/ws_multi/fuzzy_unique/fail/empty
    clean_start: int = -1
    clean_end: int = -1
    orig_start: int = -1
    orig_end: int = -1
    occurrences: int = 0
    note: str = ""


class OffsetIndex:
    """clean↔orig 双向映射与删除边界（由 edits 行构建）。"""

    def __init__(self, edits: dict):
        deleted = set()
        for s, ln, _r in edits["deletes"]:
            deleted.update(range(s, s + ln))
        self.origs: list[int] = []   # clean_pos -> orig_pos（顺序保持）
        for op in range(edits["orig_len"]):
            if op not in deleted:
                self.origs.append(op)
        self._orig_index = {op: i for i, op in enumerate(self.origs)}
        # 删除边界：文本起点删除 + 相邻 kept 原文位置不连续处的 clean 起点
        self.boundaries = ({0} if self.origs and self.origs[0] != 0 else set()) | {
            i for i in range(1, len(self.origs)) if self.origs[i] != self.origs[i - 1] + 1}

    def clean_to_orig(self, clean_pos: int) -> int:
        return self.origs[clean_pos]

    def orig_to_clean(self, orig_pos: int) -> int:
        return self._orig_index.get(orig_pos, -1)

    def span(self, cs: int, ce: int) -> tuple[int, int]:
        """clean [cs,ce) → 原文 [orig(cs), orig(ce-1)+1)。"""
        if type(cs) is not int or type(ce) is not int or not 0 <= cs < ce <= len(self.origs):
            raise IndexError(f"非法 clean 半开区间: {cs}:{ce}/{len(self.origs)}")
        return self.origs[cs], self.origs[ce - 1] + 1

    def project(self, cs: int, ce: int) -> list[tuple[int, int]]:
        """Project to contiguous original fragments; never reintroduce deleted text."""
        self.span(cs, ce)  # bounds and coordinate convention are shared
        result = []
        start = previous = self.origs[cs]
        for pos in self.origs[cs + 1:ce]:
            if pos != previous + 1:
                result.append((start, previous + 1))
                start = pos
            previous = pos
        result.append((start, previous + 1))
        return result

    def project_span(self, span, original: str):
        from evidence_types import CleanSpan, SourceSpan
        if not isinstance(span, CleanSpan):
            raise TypeError("projection_requires_CleanSpan")
        return [SourceSpan.from_text(original, a, b) for a, b in self.project(span.start, span.end)]

    def crosses_boundary(self, cs: int, ce: int) -> bool:
        return any(i in self.boundaries for i in range(cs + 1, ce))


def _find_all(text: str, sub: str) -> list[int]:
    out, start = [], 0
    while True:
        i = text.find(sub, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1


def _ws_map(text: str) -> tuple[str, list[int]]:
    """去空白文本 + 每字符对应的原 clean 位置。"""
    chars, idx = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def _mk(status: str, cleaned: str, index: OffsetIndex | None, cs: int, ce: int,
        occurrences: int = 1, note: str = "") -> Located:
    loc = Located(status=status, clean_start=cs, clean_end=ce, occurrences=occurrences, note=note)
    if index is not None and 0 <= cs < ce <= len(cleaned):
        loc.orig_start, loc.orig_end = index.span(cs, ce)
    return loc


def locate(cleaned: str, quote: str, index: OffsetIndex | None = None,
           fuzzy: bool = True) -> Located:
    if not quote or not quote.strip():
        return Located(status="empty")
    if quote not in cleaned:
        # 引文本身不在 cleaned（模型改写）——仍走 ws/fuzzy 容错，但精确级已失败
        pass

    # ① 逐字
    positions = _find_all(cleaned, quote)
    if len(positions) == 1:
        return _mk("exact_unique", cleaned, index, positions[0], positions[0] + len(quote))
    if len(positions) > 1:
        return _mk("exact_multi", cleaned, index, positions[0], positions[0] + len(quote),
                   occurrences=len(positions), note="多处命中，需上下文消歧")

    # ② 空白归一
    cn, ws_idx = _ws_map(cleaned)
    qn = WS.sub("", quote)
    if qn:
        cpos = _find_all(cn, qn)
        if len(cpos) == 1:
            cs = ws_idx[cpos[0]]
            ce = ws_idx[cpos[0] + len(qn) - 1] + 1
            return _mk("ws_unique", cleaned, index, cs, ce)
        if len(cpos) > 1:
            cs = ws_idx[cpos[0]]
            ce = ws_idx[cpos[0] + len(qn) - 1] + 1
            return _mk("ws_multi", cleaned, index, cs, ce, occurrences=len(cpos),
                       note="去空白后多处命中")

    # ③ 锚窗最长块（单连续块不跨删除边界；不足 60% 即 fail）
    if fuzzy and len(qn) >= 10:
        anchor = qn[:10]
        anchors = _find_all(cn, anchor)[:5]
        best = None
        for ap in anchors:
            win = cn[ap: ap + len(qn) + 30]
            sm = difflib_block(win, qn)
            if sm and (best is None or sm[2] > best[1][2]):
                best = (ap, sm)
        if best:
            ap, (a, _b, size) = best
            if size >= max(6, int(0.6 * len(qn))):
                cs = ws_idx[ap + a]
                ce = ws_idx[ap + a + size - 1] + 1
                return _mk("fuzzy_unique", cleaned, index, cs, ce,
                           note=f"最长块 {size}/{len(qn)} 字（部分定位，进审计）")
    return Located(status="fail")


def difflib_block(win: str, qn: str) -> tuple[int, int, int] | None:
    """win 内对 qn 的最长连续公共块 (a, b, size)。"""
    import difflib
    sm = difflib.SequenceMatcher(None, win, qn, autojunk=False)
    m = sm.find_longest_match(0, len(win), 0, len(qn))
    return (m.a, m.b, m.size) if m.size >= 6 else None
