"""M1 要素抽取（原型）：qwen3.5:9b + JSON Schema 受限解码 + 原文证据校验 + 代码规范化取值。

设计要点（见引擎方案 M1、门禁方法冻结表）：
- 模型只输出原文中有信息的字段，值一律写成字符串；数字、日期、枚举由代码按字段类型解析
  （大模型负责"找"，代码负责"算"）
- 每个值必须附逐字证据；证据在原文中找不到的值直接丢弃（从源头防事实幻觉）
- 默认关闭思考、温度 0：可复现、速度快；按需升级（多次采样）由调用方决定

P2 接入平台时改走模型网关（需要网关支持结构化输出参数）；当前直接请求 Ollama。
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from enum import Enum
from typing import get_args

import httpx

from .schema import AmountRange, FieldStatus, GamblingElements, iter_fields

DEFAULT_MODEL = "qwen3.5:9b"
FIELD_PATHS = [p for p, _, _ in iter_fields()]

# ---------- 取值规范化 ----------

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def cn_to_number(s: str) -> float | None:
    """中文或阿拉伯数字（可带"万"）转数值：三千 → 3000，1.2万 → 12000，二十三 → 23。"""
    s = s.strip().replace(",", "").replace("，", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(万)?", s)
    if m:
        return float(m.group(1)) * (10000 if m.group(2) else 1)
    if not s or any(ch not in _CN_DIGIT and ch not in _CN_UNIT and ch != "万" for ch in s):
        return None
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (num or 1) * _CN_UNIT[ch]
            num = 0
        elif ch == "万":
            total += (section + num) * 10000
            section, num = 0, 0
    return float(total + section + num)


def parse_amount(text: str) -> AmountRange | None:
    """"800" / "800元" / "3000-3999" / "三千余元" / "1.2万元" / "约5万元" → 金额区间（元）。"""
    t = text.replace("人民币", "").replace("元", "").replace("约", "").replace("左右", "").strip()
    m = re.fullmatch(r"(.+?)\s*[-~—至到]\s*(.+)", t)
    if m:
        lo, hi = cn_to_number(m.group(1)), cn_to_number(m.group(2))
        return AmountRange(min=lo, max=hi) if lo is not None and hi is not None and lo <= hi else None
    more = re.fullmatch(r"(.+?)\s*[余多]\s*(万)?", t)
    if more:
        base = cn_to_number(more.group(1) + (more.group(2) or ""))
        if base is None:
            return None
        # "三千余元" → 3000–3999；"1万余元" → 10000–19999；"50余万元" → 500000–599999；"十余万元" → 100000–199999
        step = 10 ** (len(str(int(base))) - 1) if base >= 10 else 1
        return AmountRange(min=base, max=base + step - 1)
    v = cn_to_number(t)
    if v is None:
        return None
    if "约" in text or "左右" in text:
        return AmountRange(min=round(v * 0.9), max=round(v * 1.1))
    return AmountRange(min=v, max=v)


def parse_int(text: str) -> int | None:
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    v = cn_to_number(re.sub(r"[人名次台场天日个余多]", "", text))
    return int(v) if v is not None else None


def parse_bool(text: str) -> bool | None:
    t = text.strip().lower()
    if t in ("是", "true", "有", "yes", "1"):
        return True
    if t in ("否", "false", "无", "没有", "no", "0"):
        return False
    return None


def parse_date(text: str) -> tuple[date, bool] | None:
    """返回 (日期, 是否推断)。只写到月份时取 1 日，按标注指南标"推断"。"""
    m = re.search(r"(\d{4})\s*[-年./]\s*(\d{1,2})(?:\s*[-月./]\s*(\d{1,2}))?", text)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        return date(y, mo, int(d) if d else 1), d is None
    except ValueError:
        return None


def parse_enum(text: str, enum_cls: type[Enum]) -> Enum | None:
    t = text.strip()
    for e in enum_cls:
        if t == e.value:
            return e
    for e in enum_cls:
        if e.value in t:
            return e
    return None


def _value_type(path: str):
    for p, _, typ in iter_fields():
        if p == path:
            return get_args(typ)[0] if get_args(typ) else typ
    raise KeyError(path)


def normalize(path: str, raw: str):
    """按字段类型把模型输出的字符串转成 schema 取值；无法解析返回 None。"""
    typ = _value_type(path)
    if typ is AmountRange:
        return parse_amount(raw)
    if typ is bool:
        return parse_bool(raw)
    if typ is int:
        return parse_int(raw)
    if typ is float:
        v = cn_to_number(re.sub(r"[天日]", "", raw))
        return v
    if typ is date:
        r = parse_date(raw)
        return r[0] if r else None
    if isinstance(typ, type) and issubclass(typ, Enum):
        return parse_enum(raw, typ)
    return None


# ---------- 证据定位 ----------

_QUOTES = str.maketrans({c: '"' for c in "“”‘’「」『』'＂"})
_ELLIPSIS = re.compile(r"\.{3,}|…+|⋯+|。{3,}")


def _canon(text: str) -> tuple[str, list[int]]:
    """规范化文本，并记录规范化后每个字符对应的原文位置。

    模型复述原文时常见三种改动：全角半角互换、引号样式改变、在汉字与数字之间插入空格。
    这里对原文和引文做同样的处理（NFKC、统一引号、去空白），再在规范化后的文本上匹配。
    """
    out, index = [], []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_QUOTES):
            if not c.isspace():
                out.append(c)
                index.append(i)
    return "".join(out), index


def _locate_segment(q: str, src: str, src_index: list[int], start: int, min_ratio: float) -> tuple[int, int, int] | None:
    """在规范化原文 src 的 start 之后定位规范化片段 q；返回 (原文起点, 原文终点, 规范化终点)。"""
    if not q:
        return None
    i = src.find(q, start)
    if i < 0:
        n, best, best_i = len(q), 0.0, -1
        for j in range(start, max(start + 1, len(src) - n + 1)):
            r = SequenceMatcher(None, q, src[j:j + n], autojunk=False).ratio()
            if r > best:
                best, best_i = r, j
        if best < min_ratio:
            return None
        i = best_i
    j = min(i + len(q), len(src)) - 1
    return src_index[i], src_index[j] + 1, i + len(q)


def locate(quote: str, source: str, min_ratio: float = 0.9, min_segment: int = 4) -> list[tuple[int, int]] | None:
    """证据在原文中的位置（原文字符区间列表）；找不到返回 None。

    引文含省略号时拆成多段，每段至少 min_segment 个字且按顺序都能找到才算成立。
    """
    src, src_index = _canon(source)
    parts = [p for p in (_canon(seg)[0] for seg in _ELLIPSIS.split(quote)) if p]
    if not parts or (len(parts) > 1 and any(len(p) < min_segment for p in parts)):
        return None
    spans, pos = [], 0
    for p in parts:
        hit = _locate_segment(p, src, src_index, pos, min_ratio)
        if hit is None:
            return None
        spans.append(hit[:2])
        pos = hit[2]
    return spans


# ---------- 提示与受限解码 ----------

def _field_lines() -> str:
    lines = []
    for path, desc, typ in iter_fields():
        inner = get_args(typ)[0] if get_args(typ) else typ
        if inner is AmountRange:
            fmt = "金额（元），如 800、3000-3999、三千余元"
        elif inner is bool:
            fmt = "是 / 否"
        elif inner is int:
            fmt = "整数"
        elif inner is float:
            fmt = "数字"
        elif inner is date:
            fmt = "日期，如 2025-08 或 2025-08-01"
        elif isinstance(inner, type) and issubclass(inner, Enum):
            fmt = "取值之一：" + "、".join(e.value for e in inner)
        else:
            fmt = "文本"
        lines.append(f"- {path}：{desc}。格式：{fmt}")
    return "\n".join(lines)


SYSTEM_PROMPT = """你是法律文书要素抽取员。从案情中抽取指定人员的事实要素，严格遵守：
1. 只抽取事实，不做法律判断；原文没有的信息不要输出，不要猜测。
2. 每个要素必须附 quote：从案情中逐字复制的一段连续原文，不得改写、省略或拼接。
3. status 只能是"明确"（原文直接写明）或"推断"（由上下文合理推出）。
4. 数额以元为单位；"三千余元"写成"三千余元"即可，由程序换算。
5. 只抽取目标人员本人的要素；参赌人数、现场赌资等共同事实也要抽取。
6. 只列出原文中有信息的要素（通常 5–15 个），没有信息的要素一律不要列出；不要写"未知""未提及"。
7. value 只写原文中出现的数字、数额或文字，不要计算、不要写算式或不等式（人均、合计等由程序计算）。
8. 输出紧凑的 JSON，不要换行和缩进。

可抽取的要素：
{fields}
"""


def output_schema() -> dict:
    """受限解码用的 JSON Schema：只列有信息的字段，值为字符串。"""
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "enum": FIELD_PATHS},
                        "value": {"type": "string", "minLength": 1},
                        "status": {"type": "string", "enum": ["明确", "推断"]},
                        "quote": {"type": "string", "minLength": 2},
                    },
                    "required": ["path", "value", "status", "quote"],
                },
                "maxItems": 30,
            }
        },
        "required": ["items"],
    }


@dataclass
class ExtractionResult:
    elements: GamblingElements
    dropped: list[dict] = field(default_factory=list)   # 证据找不到或取值无法解析而丢弃的条目
    raw: str = ""
    seconds: float = 0.0
    eval_tokens: int = 0


def build_elements(items: list[dict], source: str) -> tuple[GamblingElements, list[dict]]:
    data: dict[str, dict] = {}
    dropped = []
    for it in items:
        path = it.get("path")
        if path not in FIELD_PATHS:
            dropped.append({**it, "reason": "未知字段"})
            continue
        spans = locate(it.get("quote", ""), source)
        if spans is None:
            dropped.append({**it, "reason": "证据在原文中找不到"})
            continue
        evidence = [{"quote": source[a:b], "start": a, "end": b} for a, b in spans]
        value = normalize(path, it.get("value", ""))
        if value is None:
            dropped.append({**it, "reason": "取值无法解析"})
            continue
        status = FieldStatus.INFERRED if it.get("status") == "推断" else FieldStatus.EXPLICIT
        if _value_type(path) is date and parse_date(it.get("value", ""))[1]:
            status = FieldStatus.INFERRED       # 只写到月份，按指南标推断
        group, name = path.split(".")
        if name in data.setdefault(group, {}):   # 同一字段多次出现：保留第一个值，证据追加
            data[group][name]["evidence"].extend(evidence)
            continue
        data[group][name] = {"value": value.model_dump() if isinstance(value, AmountRange) else
                             (value.value if isinstance(value, Enum) else value),
                             "status": status.value, "evidence": evidence}
    return GamblingElements.model_validate(data), dropped


def extract(fact: str, target: str | None = None, *, base_url: str = "http://127.0.0.1:11434",
            model: str = DEFAULT_MODEL, timeout: float = 300, num_ctx: int = 8192) -> ExtractionResult:
    user = (f"目标人员：{target}\n\n" if target else "") + f"案情：\n{fact}"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(fields=_field_lines())},
                     {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "format": output_schema(),
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": 3000},
        "keep_alive": "30m",
    }
    t0 = time.time()
    with httpx.Client(timeout=timeout, trust_env=False) as c:
        r = c.post(f"{base_url}/api/chat", json=payload)
        if r.status_code == 500 and "repeat" in r.text:
            # 温度 0 的贪心解码遇到乱码等异常输入时会陷入重复循环（Ollama 报 token repeat limit）；
            # 只在这种情况下用小温度 + 重复惩罚重试一次，正常案例仍保持温度 0、结果可复现
            payload["options"].update(temperature=0.3, repeat_penalty=1.15, seed=0)
            r = c.post(f"{base_url}/api/chat", json=payload)
        r.raise_for_status()
        j = r.json()
    raw = j["message"]["content"]
    try:
        items = json.loads(raw).get("items", [])
    except json.JSONDecodeError:
        items = []
    elements, dropped = build_elements(items, fact)
    return ExtractionResult(elements, dropped, raw, time.time() - t0, j.get("eval_count", 0))
