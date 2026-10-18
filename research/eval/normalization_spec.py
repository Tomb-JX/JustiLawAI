"""引擎侧唯一日期/金额归一化规则（E-05 批准包）。

本模块是标注指南 §3.8–§3.9 的代码级权威实现。
后处理线（Codex element_contract）应 import 本模块或按本模块的逻辑实现，
不得另立第二套规则。JioNLP 仅作实现选项，其输出须经本模块校验。

用法：
    from normalization_spec import normalize_amount, normalize_date, normalize_duration

Codex 对接：element_contract 的日期/金额归一化步骤应调用本模块的函数，
或将本模块的逻辑复制到 element_contract 中（保持行为一致）。
"""
from __future__ import annotations

import re
from datetime import date

# --- 金额归一化（§3.9 + 标注指南 §2） ---

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "壹": 1, "贰": 2, "叁": 3,
              "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
             "拾": 10, "佰": 100, "仟": 1000}


def cn_to_number(text: str) -> float | None:
    """中文大写/小写数字 → 浮点数。'三千五百' → 3500，'1.2万' → 12000。"""
    t = text.strip().replace(",", "").replace("，", "")
    if not t:
        return None
    # 纯阿拉伯数字
    try:
        return float(t)
    except ValueError:
        pass
    # 阿拉伯数字+万/亿单位后缀
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([万亿])", t)
    if m:
        v = float(m.group(1))
        return v * (10000 if m.group(2) == "万" else 100000000)
    # 中文数字
    result = 0
    current = 0
    yi_pos = t.find("亿")
    if yi_pos >= 0:
        yi_part = t[:yi_pos]
        result += (_cn_small(yi_part) if yi_part else 1) * 100000000
        t = t[yi_pos + 1:]
    wan_pos = t.find("万")
    if wan_pos >= 0:
        wan_part = t[:wan_pos]
        result += (_cn_small(wan_part) if wan_part else 1) * 10000
        t = t[wan_pos + 1:]
    result += _cn_small(t)
    return result if result > 0 else None


def _cn_small(t: str) -> float:
    """解析万以下的中文数字段。"""
    result = 0
    current = 0
    for ch in t:
        if ch in _CN_DIGITS:
            current = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if current == 0 and unit >= 10:
                current = 1  # "十五" → 15
            result += current * unit
            current = 0
        elif ch in (".", "点"):
            # 小数点后逐字
            decimal_str = t[t.index(ch) + 1:]
            decimal_val = sum(_CN_DIGITS.get(c, 0) / (10 ** (i + 1))
                              for i, c in enumerate(decimal_str))
            return result + current + decimal_val
    return result + current


def _last_unit(n: float) -> int:
    """取最末非零数位的一个单位。12500 → 100，3000 → 1000。"""
    unit = 1
    n = int(n)
    while n > 0 and n % 10 == 0:
        n, unit = n // 10, unit * 10
    return unit


def normalize_amount(text: str) -> dict | None:
    """引擎侧唯一金额归一化规则。

    输入：原文中的金额表述（如"三千余元""万元以上""约5万元"）。
    输出：{"min": float, "max": float|None} 或 None（无法解析）。
    单位：元。max=None 表示开口（只给了下界）。

    规则（标注指南 §2 + §3.9）：
    - 确切数额 → min=max
    - "以上/逾/超过/至少/不低于" → min=X, max=None（不补上界）
    - "X余元/X多元" → min=X, max=X + 末位非零数位的一个单位 - 1
    - "约X/X左右" → min=X*0.9, max=X*1.1
    - "数/几+单位" → min=2*单位, max=(9+1)*单位 - 1
    - "近X/将近X" → min=X*0.9, max=X
    - "不足X/不到X/X以下" → min=0, max=X
    - 打码（"xx元"）→ None
    """
    if not text or not isinstance(text, str):
        return None
    # 打码检测
    if re.search(r"[xX]{2,}\s*元?", text):
        return None

    is_approx = "约" in text or "左右" in text
    t = text.replace("人民币", "").replace("元", "").replace("约", "").replace("左右", "").strip()
    # 去掉常见前缀
    t = re.sub(r"^(?:个人|现场|累计|涉案)?(?:赌资|赌金|金额)(?:数额)?", "", t).strip()

    # 开口写法检测
    is_open = bool(re.search(r"以上|逾|超过|至少|不低于|不少于", t))
    if is_open:
        t = re.sub(r"^(?:逾|超过|至少|不低于|不少于)?\s*", "", t)
        t = re.sub(r"\s*以上$", "", t)
        base = cn_to_number(t)
        return {"min": base, "max": None} if base is not None else None

    # 区间写法
    m = re.fullmatch(r"(.+?)\s*[-~—至到]\s*(.+)", t)
    if m:
        lo, hi = cn_to_number(m.group(1)), cn_to_number(m.group(2))
        if lo is not None and hi is not None and lo <= hi:
            return {"min": lo, "max": hi}
        return None

    # 不足/不到/以下
    m = re.fullmatch(r"(?:不足|不到|低于)\s*(.+)|(.+?)\s*以下", t)
    if m:
        v = cn_to_number(m.group(1) or m.group(2))
        return {"min": 0, "max": v} if v is not None else None

    # 近/将近
    m = re.fullmatch(r"(?:近|将近|接近)\s*(.+)", t)
    if m:
        v = cn_to_number(m.group(1))
        if v is not None:
            return {"min": round(v * 0.9), "max": v}
        return None

    # 数/几 + 单位
    m = re.fullmatch(r"([数几])\s*([十百千万]+)", t)
    if m:
        unit = cn_to_number("一" + m.group(2)) if m.group(2) != "万" else cn_to_number("1万")
        if unit is not None:
            lo, hi = (2, 9) if m.group(1) == "数" else (2, 9)
            return {"min": lo * unit, "max": (hi + 1) * unit - 1}
        return None

    # 余/多
    m = re.fullmatch(r"(.+?)\s*[余多]\s*(万)?", t)
    if m:
        base = cn_to_number(m.group(1) + (m.group(2) or ""))
        if base is not None:
            return {"min": base, "max": base + _last_unit(base) - 1}
        return None

    # 确切数额（含近似判断）
    v = cn_to_number(t)
    if v is not None:
        if is_approx:
            return {"min": round(v * 0.9), "max": round(v * 1.1)}
        return {"min": v, "max": v}
    return None


# --- 日期归一化（§3.8 + 标注指南 §3） ---

def normalize_date(text: str) -> tuple[date, str] | None:
    """引擎侧唯一日期归一化规则。

    输入：原文中的日期表述。
    输出：(date, status) 或 None（无法解析）。
    status: "明确"（精确到日）、"推断"（只写到月或年）。

    规则（标注指南 §3 + §3.8）：
    - 精确到日 → date, 明确
    - 只写到月 → 该月 1 日, 推断
    - 只写到年 → 该年 7 月 1 日, 推断
    - 非法日期（2月30日等）→ None
    """
    if not text or not isinstance(text, str):
        return None
    # 精确到日
    m = re.search(r"(\d{4})\s*[-年./]\s*(\d{1,2})\s*[-月./]\s*(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "明确"
        except ValueError:
            return None
    # 只写到月
    m = re.search(r"(\d{4})\s*[-年./]\s*(\d{1,2})\s*月?", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1), "推断"
        except ValueError:
            return None
    # 只写到年
    m = re.search(r"(\d{4})\s*年", text)
    if m:
        try:
            return date(int(m.group(1)), 7, 1), "推断"
        except ValueError:
            return None
    return None


def normalize_duration(text: str) -> float | None:
    """持续时间归一化（天）。

    输入：原文中的持续时间表述（如"持续三个月""一年"）。
    输出：天数（float）或 None。

    规则（标注指南 §3.8）：月 × 30，年 × 365。
    """
    if not text or not isinstance(text, str):
        return None
    t = text.strip()
    # N天
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:天|日)", t)
    if m:
        return float(m.group(1))
    # N个月
    m = re.search(r"(\d+(?:\.\d+)?)\s*个?\s*月", t)
    if m:
        return float(m.group(1)) * 30
    # N年
    m = re.search(r"(\d+(?:\.\d+)?)\s*年", t)
    if m:
        return float(m.group(1)) * 365
    # 中文数字+单位
    m = re.search(r"([一二三四五六七八九十百千万]+)\s*个?\s*(天|日|月|年)", t)
    if m:
        v = cn_to_number(m.group(1))
        if v is not None:
            unit_map = {"天": 1, "日": 1, "月": 30, "年": 365}
            return v * unit_map[m.group(2)]
    return None


# --- 校验接口（供 Codex element_contract 调用） ---

def validate_amount_against_source(normalized: dict, evidence_text: str) -> bool:
    """校验归一化后的金额是否与证据文本一致。

    只对唯一的阿拉伯数额做机械对账；无法确定的返回 True（留给仲裁）。
    """
    if not normalized or not evidence_text:
        return True
    pattern = re.compile(r"\d+(?:\.\d+)?\s*(?:万)?元(?:以上|余|多|以下)?")
    mentions = pattern.findall(evidence_text)
    if len(mentions) != 1:
        return True  # 无法机械对账
    parsed = normalize_amount(mentions[0])
    if parsed is None:
        return True
    return (round(normalized.get("min", 0), 6) == round(parsed["min"], 6)
            and (normalized.get("max") is None) == (parsed["max"] is None)
            and (normalized.get("max") is None
                 or round(normalized["max"], 6) == round(parsed["max"], 6)))


def validate_date_against_source(normalized_iso: str, evidence_text: str) -> bool:
    """校验归一化后的日期是否在证据文本中有对应。"""
    if not normalized_iso or not evidence_text:
        return True
    result = normalize_date(evidence_text)
    if result is None:
        return True  # 无法从证据解析日期
    parsed_date, _ = result
    return normalized_iso[:10] == parsed_date.isoformat()