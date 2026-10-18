"""S0 统一规范化引擎与规则册（parse-format-chain-design-2026-10-17 v1.2 §4）。

角色：parsed-1 原文 → cleaned_text + 区间变换日志（RLE）。纯确定性、可单测、可回放：
- 逐字符映射在内存中构造；随批次以紧凑区间日志落盘（edits.rle.jsonl，由 to_unified 写出），
  下游可脱离本模块独立回放（CleanResult.replay / replay_edits）；
- 每次删除/替换带规则 id（规则标记点），供 S2 模糊对齐禁止跨界收缩；
- 规则按源分册（web/pkulaw），同一机制；清理单点挂 S0，渠道解析层不再加清理规则。

引擎语义：规则 = 在"当前文本"上找不重叠命中区（del 或同长 sub），从后往前应用；
删除按原文位置记录（可能不连续，输出时压缩为区间），替换记录（原文位置, 原字符, 新字符）。
"""

from __future__ import annotations

import re
from collections import Counter

from form import LABEL_WORDS

CLEAN_VERSION = "clean:v1.1"

_CJK_DIGIT = re.compile(r"[一-龥0-9０-９，,、]")


# ---------- 引擎 ----------

class _State:
    def __init__(self, orig: str) -> None:
        self.ch = list(orig)
        self.src = list(range(len(orig)))
        self.subs: dict[int, tuple[str, str, str]] = {}  # 原文位置 -> (原字符, 新字符, 规则)
        self.deletes: dict[str, set[int]] = {}           # 规则 -> 原文位置集合
        self.fired: Counter = Counter()

    def text(self) -> str:
        return "".join(self.ch)

    def apply(self, rule_id: str, finder) -> None:
        text = self.text()
        hits = finder(text)
        if not hits:
            return
        del_pos: list[int] = []
        for start, end, action in sorted(hits, key=lambda h: -h[0]):
            if action == "del":
                del_pos.extend(range(start, end))
            else:  # ("sub", 同长字符串)
                repl = action[1]
                if len(repl) != end - start:
                    raise ValueError(f"规则 {rule_id} 替换长度不等长：{start}:{end}")
                for k, p in enumerate(range(start, end)):
                    src = self.src[p]
                    orig_ch = self.subs[src][0] if src in self.subs else self.ch[p]
                    self.subs[src] = (orig_ch, repl[k], rule_id)
                    self.ch[p] = repl[k]
        self.deletes.setdefault(rule_id, set()).update(self.src[p] for p in del_pos)
        # 压缩掉被删字符
        keep_c, keep_s = [], []
        for c, s in zip(self.ch, self.src):
            if s not in self.deletes.get(rule_id, ()):
                keep_c.append(c)
                keep_s.append(s)
        self.ch, self.src = keep_c, keep_s
        self.fired[rule_id] = len(hits)


class CleanResult:
    """S0 产物：cleaned_text + 变换日志（删除区间/替换表，按规则分组）。"""

    def __init__(self, orig_len: int, cleaned: str, deletes: dict[str, set[int]],
                 subs: dict[str, list[tuple[int, str, str]]]) -> None:
        self.orig_len = orig_len
        self.cleaned = cleaned
        self._del_pos = deletes    # 规则 -> 原文位置集合
        self._subs = subs          # 规则 -> [(原文位置, 原字符, 新字符)]
        self.deletes = {rule: _compress(sorted(pos)) for rule, pos in deletes.items()}
        self.subs = {rule: sorted(v) for rule, v in subs.items()}
        self.clean_version = CLEAN_VERSION

    # --- 回放：任何下游可不依赖本模块的规则册，仅凭日志重构 cleaned_text ---

    def replay(self, orig: str) -> str:
        mask = bytearray(len(orig))
        for rule, ranges in self.deletes.items():
            for start, ln in ranges:
                mask[start:start + ln] = b"\x01" * ln
        subs = {}
        for rule, rows in self._subs.items():
            for pos, orig_ch, _new in rows:
                if orig[pos] != orig_ch:
                    raise ValueError(f"回放断言失败：位置 {pos} 原文为 {orig[pos]!r}，日志记 {orig_ch!r}")
                subs[pos] = _new
        return "".join(subs.get(i, ch) for i, ch in enumerate(orig) if not mask[i])

    # --- RLE 区间：kept 区间 (orig_start, orig_len, clean_start, clean_len) ---

    def kept_intervals(self) -> list[tuple[int, int, int, int]]:
        deleted = set()
        for pos in self._del_pos.values():
            deleted.update(pos)
        kept = sorted(set(range(self.orig_len)) - deleted)
        out: list[tuple[int, int, int, int]] = []
        i = 0
        while i < len(kept):
            j = i
            while j + 1 < len(kept) and kept[j + 1] == kept[j] + 1:
                j += 1
            out.append((kept[i], j - i + 1, i, j - i + 1))
            i = j + 1
        return out

    # --- edits.rle.jsonl 行 ---

    def to_edits(self) -> dict:
        return {
            "clean_version": self.clean_version,
            "orig_len": self.orig_len,
            "cleaned_len": len(self.cleaned),
            "deletes": [[s, ln, rule] for rule, ranges in self.deletes.items() for s, ln in ranges],
            "subs": [[pos, oc, nc, rule] for rule, rows in self._subs.items() for pos, oc, nc in rows],
        }


def _compress(sorted_pos: list[int]) -> list[tuple[int, int]]:
    """排序后的原文位置 -> [(起点, 长度)] 区间压缩。"""
    out: list[tuple[int, int]] = []
    for p in sorted_pos:
        if out and out[-1][0] + out[-1][1] == p:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((p, 1))
    return out


def replay_edits(orig: str, edits: dict) -> str:
    """edits.rle.jsonl 行（to_edits 产物）→ 重构 cleaned_text（供批级独立回放）。"""
    mask = bytearray(len(orig))
    for s, ln, _rule in edits["deletes"]:
        mask[s:s + ln] = b"\x01" * ln
    subs = {pos: nc for pos, _oc, nc, _rule in edits["subs"]}
    return "".join(subs.get(i, ch) for i, ch in enumerate(orig) if not mask[i])


# ---------- 句表（seg-v2 分区接口的确定性输入，parse-interface-v2-design §2） ----------

_SENT_ITEM = re.compile(r"[^。！？；\n]*(?:[。！？；]|\n|$)")


def sentence_table(cleaned: str) -> list[list[int]]:
    """cleaned_text → 编号句表 [[start, end], ...]（cleaned 坐标，1 基序号由顺序隐含）。
    切分：句块＝非分隔符段 + 一个句末标点/换行/文末（消费式 finditer，坐标无缝不吞位）；
    空白句丢弃；句表是分区调用的确定性坐标基座——覆盖性/不重叠由"区间必须完整铺满
    句表"的结构校验保证，不依赖模型自觉。"""
    table: list[list[int]] = []
    for m in _SENT_ITEM.finditer(cleaned or ""):
        seg = m.group(0)
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            table.append([m.start() + lead, m.start() + len(seg.rstrip())])
    return table


# ---------- 规则（finder：text -> [(start, end, "del" | ("sub", 同长串))]） ----------

def _iter_lines(text: str):
    start = 0
    for line in text.split("\n"):
        yield start, line
        start += len(line) + 1


# web 导航样板：整行删除（白名单：锚定行首、行短、无句号——不碰正文散文）
NAV_LINE = re.compile(
    r"^(?:首页\s*>|当前位置[：:]|【?字体|打印本?页?|关闭|关闭窗口|发布时间[：:]|来源[：:]|出处[：:]|"
    r"责任编辑[：:]|编辑[：:]|审核[：:]|作者[：:]|点击[数次数]?[：:]|时间[：:]|日期[：:]"
    r"|走进.+(?:专题|频道|栏目))")


def _finder_nav(text: str):
    hits = []
    for pos, line in _iter_lines(text):
        s = line.strip()
        if not s or len(s) > 60 or "。" in s:
            continue
        if NAV_LINE.match(s):
            hits.append((pos, pos + len(line), "del"))
    return hits


# 日期变体：数字间全角点/句号 → 半角点（1:1）
DATE_VARIANT = re.compile(r"(?<=[0-9０-９])[．。](?=[0-9０-９])")


def _finder_date(text: str):
    return [(m.start(), m.end(), ("sub", ".")) for m in DATE_VARIANT.finditer(text)]


def _finder_pipe(text: str):
    """管道：行内 ≥2 个 → 逐个替换为换行（结构表行）；单管道 → 删除（续行拼接）。"""
    hits = []
    for pos, line in _iter_lines(text):
        n = line.count("|")
        for off, ch in enumerate(line):
            if ch == "|":
                p = pos + off
                if n >= 2:
                    hits.append((p, p + 1, ("sub", "\n")))
                else:
                    hits.append((p, p + 1, "del"))
    return hits


def _is_label(s: str) -> bool:
    """纯标签行：存在标签词且词后余量 ≤2 字（容忍冒号）——带渠道前缀的"行政处罚决定书文号"
    命中（词后零余量），而"标签+值"混写行（词后有实际值）不算。"""
    if not s:
        return False
    for w in LABEL_WORDS:
        i = s.find(w)
        if i >= 0 and len(s) - (i + len(w)) <= 2:
            return True
    return False


def _is_label_line(s: str) -> bool:
    """标签行（宽松，用于"下一行是新键值行则保留换行"）：短行内含任一标签词。
    覆盖带渠道前缀的写法（如"行政处罚决定书文号"含标签词"决定书文号"）。"""
    return bool(s) and len(s) <= 14 and any(w in s for w in LABEL_WORDS)


def _starts_key_value_line(s: str) -> bool:
    """Preserve a table cell boundary even when the label and value share a long line."""
    return any(re.match(rf"^(?:行政处罚|处罚|行政)?{re.escape(w)}\s*[:：]", s) for w in LABEL_WORDS)


def _finder_cell_wrap(text: str):
    """短片段裸换行处理（键值感知，v1.2 实现修订）：
    - 前行是模板标签（≤12 字、以标签词开头）且未带冒号 → 换行替换为"："（标签：值 键值行）；
    - 后行是模板标签 → 保留换行（新键值行起始，不拼接）；
    - 其余（含前行以：结尾的值续行）→ 删除换行拼接。
    仅在换行两侧均为汉字/数字且至少一侧是短行（≤20 字）时触发——长散文行分段不碰。
    首跑教训：无分隔拼接曾把 63 件字段表块的 14 个模板词压成 1 个（标签与值融成连串）。"""
    hits = []
    for m in re.finditer("\n", text):
        p = m.start()
        if p == 0 or p + 1 >= len(text):
            continue
        if not (_CJK_DIGIT.match(text[p - 1]) and _CJK_DIGIT.match(text[p + 1])):
            continue
        ls = text.rfind("\n", 0, p) + 1
        prev = text[ls:p].strip()
        nl2 = text.find("\n", p + 1)
        nxt = text[p + 1: nl2 if nl2 >= 0 else len(text)].strip()
        if _is_label_line(nxt) or _starts_key_value_line(nxt):
            continue  # 后行是新键值行：保留换行
        prev_len = p - ls
        nl_next = nl2 if nl2 >= 0 else len(text)
        next_len = nl_next - (p + 1)
        if prev_len <= 20 or next_len <= 20:
            if _is_label(prev) and not prev.endswith(("：", ":")):
                hits.append((p, p + 1, ("sub", "：")))
            else:
                hits.append((p, p + 1, "del"))
    return hits


def _finder_comma_join(text: str):
    """逗号尾续行：行尾为 ，/, 且后随换行 → 删除换行拼接（法宝 Word 转换残留）。"""
    hits = []
    for pos, line in _iter_lines(text):
        s = line.rstrip()
        if s and s[-1] in "，," and pos + len(line) < len(text):
            # 换行恰在行尾（其后是下一行）；行尾若还有空白交给 ws_fold 处理
            hits.append((pos + len(line), pos + len(line) + 1, "del"))
    return hits


def _finder_ws_chars(text: str):
    """字符级空白归一：全角空格/不换行空格/制表符 → 半角空格；回车删除。"""
    hits = []
    for m in re.finditer(r"[\u3000\u00a0\t]", text):
        hits.append((m.start(), m.end(), ("sub", " ")))
    for m in re.finditer(r"\r", text):
        hits.append((m.start(), m.end(), "del"))
    return hits


def _finder_ws_fold(text: str):
    """空白串折叠：连续空白（空格/换行）→ 含换行折叠为单个换行，否则单个空格；文本首尾删除。
    对每个 run 输出一组互不重叠的 del + 至多一个 sub，引擎按位置排序应用。"""
    hits = []
    for m in re.finditer(r"[ \n]+", text):
        s, e = m.start(), m.end()
        if s == 0 or e == len(text):
            hits.extend((p, p + 1, "del") for p in range(s, e))
            continue
        run = text[s:e]
        keep = s + run.find("\n") if "\n" in run else s
        target = "\n" if "\n" in run else " "
        for p in range(s, e):
            if p == keep:
                if text[p] != target:
                    hits.append((p, p + 1, ("sub", target)))
            else:
                hits.append((p, p + 1, "del"))
    return hits


WEB_RULES = [
    ("web_nav", _finder_nav),
    ("date_variant", _finder_date),
    ("pipe", _finder_pipe),
    ("cell_wrap", _finder_cell_wrap),
    ("ws_chars", _finder_ws_chars),
    ("ws_fold", _finder_ws_fold),
]

PKULAW_RULES = [
    ("pipe", _finder_pipe),
    ("cell_wrap", _finder_cell_wrap),
    ("comma_join", _finder_comma_join),
    ("ws_chars", _finder_ws_chars),
    ("ws_fold", _finder_ws_fold),
]

REGISTRIES = {"web": WEB_RULES, "pkulaw": PKULAW_RULES}


def cleanse(orig: str, channel: str) -> CleanResult:
    """按渠道规则册执行 S0。channel ∈ {web, pkulaw}。"""
    rules = REGISTRIES.get(channel)
    if rules is None:
        raise ValueError(f"未知渠道规则册：{channel}")
    state = _State(orig or "")
    for rule_id, finder in rules:
        state.apply(rule_id, finder)
    return CleanResult(
        orig_len=len(orig or ""),
        cleaned=state.text(),
        deletes=state.deletes,
        subs=_subs_by_rule(state),
    )


def _subs_by_rule(state: _State) -> dict[str, list[tuple[int, str, str]]]:
    out: dict[str, list[tuple[int, str, str]]] = {}
    for pos, (oc, nc, rule) in state.subs.items():
        out.setdefault(rule, []).append((pos, oc, nc))
    return {rule: sorted(rows) for rule, rows in out.items()}
