"""Evidence-bound Chinese temporal/quantity adapters; no engine ontology overrides.

JioNLP supplies expression parsing. Precision, open endpoints and compatibility
losses remain explicit here. No function reads the clock or guesses an event anchor.
"""
from __future__ import annotations

import calendar
import ast
import contextlib
import hashlib
import io
import re
import threading
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from evidence_types import SourceSpan

VERSION = "zh-normalizer-1"
JIO_VERSION = "1.5.29"
NUM = r"[0-9０-９〇零一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两点.,，]+"
_local = threading.local()
_init_lock = threading.Lock()
_classes = None


@lru_cache(maxsize=1)
def backend_fingerprint():
    from importlib.util import find_spec
    installed = version("jionlp")
    if installed != JIO_VERSION:
        raise RuntimeError(f"normalizer_backend_version:{installed}!={JIO_VERSION}")
    root = Path(find_spec("jionlp").origin).parent
    zip_source = root / 'util/zip_file.py'
    required = next(ast.literal_eval(n.value) for n in ast.parse(zip_source.read_text('utf-8')).body
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'UNZIP_FILE_LIST' for t in n.targets))
    if any(not (root / 'dictionary' / name).is_file() for name in required):
        raise RuntimeError('normalizer_dictionary_missing:预部署资源，不在运行期解压或下载')
    paths = sorted(root.rglob('*.py'))
    # Dictionary assets are part of the deployed parser, not fetched on demand.
    paths += sorted(p for p in (root / "dictionary").glob("*") if p.is_file())
    return {"adapter": VERSION, "jionlp": installed,
            "resources": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}


def _backend():
    global _classes
    if not hasattr(_local, "time"):
        backend_fingerprint()
        with _init_lock:
            if _classes is None:
                # JioNLP's package init prints a banner; keep machine CLI output JSON.
                with contextlib.redirect_stdout(io.StringIO()):
                    from jionlp.gadget.time_parser import TimeParser
                    from jionlp.gadget.money_parser import MoneyParser
                _classes = TimeParser, MoneyParser
        # Instances mutate state: never share a parser across worker threads.
        _local.time, _local.money = _classes[0](), _classes[1]()
    return _local


def _base(raw: str, ref: SourceSpan):
    if not isinstance(ref, SourceSpan) or raw != ref.quote:
        raise ValueError("normalization_requires_exact_source_reference")
    return {"raw": raw, "source_ref": ref.to_dict(), "normalizer": VERSION,
            "backend": f"jionlp@{JIO_VERSION}", "resolution": "unresolved", "reason": None}


def normalize_time(raw: str, ref: SourceSpan, *, anchor: dict | None = None, kind_hint=None):
    out = _base(raw, ref)
    out.update(kind="unknown", precision=None, start_date=None, end_date=None, anchor_ref=None, calendar='gregorian')
    expr = raw.strip()
    if re.search(r'农历|阴历|闰月|公元前', expr):
        return {**out, 'reason': 'unsupported_calendar'}
    duration = kind_hint == "duration" or bool(re.fullmatch(fr"{NUM}个?(?:小时|分钟|个月|月|年|天|日|周)", expr))
    # A bare "30日" can also be a calendar day. Require the caller to disambiguate.
    if re.fullmatch(fr"{NUM}日", expr) and kind_hint != "duration":
        duration = False
    full_year = bool(re.search(r"(?:\d{4}|[〇零一二三四五六七八九]{4})年|^\d{4}[-./]", expr))
    relative = bool(re.search(r"同年|当年|去年|前年|今年|次日|翌日|当天|当日|昨日|本月|上月", expr))
    needs_anchor = not duration and (not full_year or relative)
    base = [2000, 1, 1, 12, 0, 0]  # Only ignored components of absolute expressions/durations.
    if needs_anchor:
        if (not anchor or anchor.get("resolution") != "resolved" or not anchor.get("start_date")
                or anchor.get("source_ref", {}).get("text_sha256") != ref.text_sha256):
            return {**out, "reason": "missing_evidence_anchor"}
        if re.search(r"次日|翌日|当天|当日|昨日", expr) and anchor.get("precision") != "day":
            return {**out, "reason": "anchor_precision_insufficient"}
        if not re.search(r"年", expr) and not re.search(r"月", expr) and anchor.get("precision") == "year":
            return {**out, "reason": "anchor_precision_insufficient"}
        ad = date.fromisoformat(anchor["start_date"])
        base = [ad.year, ad.month, ad.day, 12, 0, 0]
        out["anchor_ref"] = anchor["source_ref"]
    try:
        # A complete relative-day relation is handled without a parser default.
        if expr in {"次日", "翌日", "当天", "当日", "昨日"}:
            delta = {"次日": 1, "翌日": 1, "当天": 0, "当日": 0, "昨日": -1}[expr]
            day = date(*base[:3]) + timedelta(days=delta)
            return {**out, "kind": "calendar_range", "precision": "day", "resolution": "resolved",
                    "start_date": day.isoformat(), "end_date": day.isoformat()}
        got = _backend().time(expr, time_base=base, strict=True, ret_future=False,
                              **({"time_type": "time_delta"} if duration else {}))
        if got["type"] == "time_delta":
            return {**out, "kind": "duration", "resolution": "resolved", "duration": got["time"],
                    "definition": got["definition"]}
        if got["type"] not in {"time_point", "time_span"} or any(not isinstance(x, str) for x in got["time"]):
            return {**out, "reason": "unsupported_temporal_kind"}
        start, end = [date.fromisoformat(x[:10]) for x in got["time"]]
        if end < start:
            raise ValueError("reversed_time")
        precision = "range"
        if start == end:
            precision = "day"
        elif start.day == 1 and end == date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]):
            precision = "month"
        elif start == date(start.year, 1, 1) and end == date(start.year, 12, 31):
            precision = "year"
        if re.search(r"\d+[时点分秒]", expr):
            return {**out, "reason": "instant_not_supported"}
        return {**out, "kind": "calendar_range", "resolution": "resolved", "precision": precision,
                "start_date": start.isoformat(), "end_date": end.isoformat(), "definition": got["definition"]}
    except (ValueError, TypeError, KeyError, OverflowError, AssertionError):
        return {**out, "reason": "invalid_or_unsupported_time"}


def _decimal(value):
    # JioNLP money uses decimal strings. Reject a backend float rather than claim
    # Decimal(str(float)) recovers precision already lost upstream.
    if type(value) not in (str, int):
        raise ValueError("non_decimal_backend_number")
    d = Decimal(value)
    if not d.is_finite() or d < 0 or d > Decimal("1e12") or d.as_tuple().exponent < -2:
        raise ValueError("outside_supported_currency_precision")
    return d


def normalize_quantity(raw: str, ref: SourceSpan, *, unit="CNY"):
    if unit not in {'CNY','count'}:
        raise ValueError('unsupported_quantity_unit')
    out = _base(raw, ref)
    out.update(unit=unit, kind="unknown", lower=None, upper=None,
               lower_inclusive=True, upper_inclusive=True, operator=None)
    expr = raw.strip()
    if unit != "CNY":
        match = re.fullmatch(fr"(至少|超过|不足|至多)?({NUM})(?:至|到|[-~～])?({NUM})?(?:余|多)?(?:名|个)?(人|次|场|台)", expr)
        if not match:
            return {**out, "reason": "unsupported_count_expression"}
        prefix, a, b, suffix = match.groups()
        expr = (prefix or "") + a + ("至" + b if b else "") + "元"
    try:
        got = _backend().money(expr)
        if got.get("case") != "元":
            return {**out, "reason": "unsupported_currency"}
        nums = got["num"] if isinstance(got["num"], list) else [got["num"]]
        values = [_decimal(v) for v in nums]
        if len(values) not in (1, 2) or (len(values) == 2 and values[0] > values[1]):
            raise ValueError("invalid_quantity_range")
        lo, hi = values[0], values[-1]
        if unit != "CNY" and any(v != v.to_integral_value() for v in values):
            raise ValueError("fractional_count")
        kind, op, li, ui = ("interval" if len(values) == 2 else "exact"), "=", True, True
        # Match exclusion before its contained inclusion (不超过 vs 超过).
        if re.search(r"不超过|至多|以下", raw):
            kind, op, lo, hi = "upper_bound", "<=", Decimal(0), hi
        elif re.search(r"不足|不到|低于", raw):
            kind, op, lo, hi, ui = "upper_bound", "<", Decimal(0), hi, False
        elif re.search(r"超过|逾", raw):
            kind, op, hi, li = "lower_bound", ">", None, False
        elif re.search(r"至少|不低于|以上", raw):
            kind, op, hi = "lower_bound", ">=", None
        elif re.search(r"约|近|余|多|左右|上下", raw) or (got.get("definition") != "accurate"
                and not (len(values) == 2 and re.search(r"至|到|[-~～]", raw))):
            # Preserve fuzzy scope; the backend's heuristic range is not a true bound.
            return {**out, "kind": "approximate", "operator": "~", "resolution": "resolved",
                    "center": str(lo), "backend_hint": [str(v) for v in values],
                    "reason": "requires_explicit_approximation_policy"}
        return {**out, "kind": kind, "operator": op, "resolution": "resolved",
                "lower": str(lo), "upper": str(hi) if hi is not None else None,
                "lower_inclusive": li, "upper_inclusive": ui}
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError, AssertionError):
        return {**out, "reason": "invalid_or_unsupported_quantity"}


def project_time(value, *, policy=None):
    if value["resolution"] != "resolved" or value["kind"] != "calendar_range":
        return {"value": None, "reason": "not_a_resolved_calendar_date", "losses": []}
    if value["precision"] == "day":
        return {"value": value["start_date"], "status": "明确", "losses": []}
    if value["precision"] == "month" and policy == "schema-1.1.0-month-first":
        return {"value": value["start_date"], "status": "推断", "losses": ["month_to_first_day"], "policy": policy}
    return {"value": None, "reason": "precision_not_losslessly_projectable", "losses": []}


def project_quantity(value, *, policy=None):
    losses = []
    if value["resolution"] != "resolved" or value["kind"] == "approximate":
        return {"value": None, "reason": "quantity_not_losslessly_projectable", "losses": losses}
    if not value["lower_inclusive"] or not value["upper_inclusive"]:
        if policy != "schema-1.1.0-close-endpoints":
            return {"value": None, "reason": "open_endpoint", "losses": losses}
        losses.append("open_endpoint_closed")
    lo, hi = value["lower"], value["upper"]
    if value["unit"] != "CNY":
        if lo != hi:
            return {"value": None, "reason": "count_range_not_integer", "losses": losses}
        result = int(Decimal(lo))
    else:
        result = {"min": lo, "max": hi}  # Decimal strings until the engine's explicit wire conversion.
    return {"value": result, "losses": losses, "policy": policy}


def derive_age(birth, behavior):
    """Calendar arithmetic; callers independently establish person/event binding."""
    if any(v.get('resolution') != 'resolved' or v.get('kind') != 'calendar_range' for v in (birth, behavior)):
        return {'resolution': 'unresolved', 'reason': 'missing_calendar_range'}
    def age(b, e):
        return e.year - b.year - ((e.month, e.day) < (b.month, b.day))
    b0, b1 = (date.fromisoformat(birth[k]) for k in ('start_date', 'end_date'))
    e0, e1 = (date.fromisoformat(behavior[k]) for k in ('start_date', 'end_date'))
    low, high = age(b1, e0), age(b0, e1)
    if not 0 <= low <= high <= 130:
        return {'resolution': 'unresolved', 'reason': 'implausible_or_reversed_age'}
    return {'resolution': 'resolved', 'min': low, 'max': high,
            'exact': low == high, 'requires_subject_event_binding': True,
            'source_refs': [birth['source_ref'], behavior['source_ref']]}


def project_duration_days(value, *, policy=None):
    if value.get('resolution') != 'resolved' or value.get('kind') != 'duration':
        return {'value': None, 'reason': 'not_a_resolved_duration', 'losses': []}
    duration = value['duration']
    if set(duration) <= {'day', 'week'}:
        return {'value': duration.get('day', 0) + 7 * duration.get('week', 0), 'losses': []}
    if policy == 'schema-1.1.0-30day-month' and set(duration) <= {'month', 'day', 'week'}:
        return {'value': duration.get('day', 0) + 7 * duration.get('week', 0) + 30 * duration.get('month', 0),
                'losses': ['calendar_month_to_30_days'], 'policy': policy}
    return {'value': None, 'reason': 'calendar_duration_not_fixed_days', 'losses': []}


# --- E-05 approval package: authoritative normalization ---
# These functions delegate to normalization_spec.py (engine-side authority).
# The JioNLP-based functions above remain for complex cases (anchors, relative dates).
# For simple amount/date/duration normalization, prefer these E-05 functions.

def normalize_amount_e05(text: str) -> dict | None:
    """E-05 权威金额归一化。返回 {"min": float, "max": float|None} 或 None。"""
    from element_contract import normalize_amount_e05 as _fn
    return _fn(text)


def normalize_date_e05(text: str):
    """E-05 权威日期归一化。返回 (date, status) 或 None。"""
    from element_contract import normalize_date_e05 as _fn
    return _fn(text)


def normalize_duration_e05(text: str) -> float | None:
    """E-05 权威持续时间归一化（天）。"""
    from element_contract import normalize_duration_e05 as _fn
    return _fn(text)


def validate_amount_e05(normalized: dict, evidence_text: str) -> bool:
    """E-05 金额归一化对账。True=一致或无法机械对账。"""
    from element_contract import validate_amount_e05 as _fn
    return _fn(normalized, evidence_text)


def validate_date_e05(normalized_iso: str, evidence_text: str) -> bool:
    """E-05 日期归一化对账。True=一致或无法解析。"""
    from element_contract import validate_date_e05 as _fn
    return _fn(normalized_iso, evidence_text)
