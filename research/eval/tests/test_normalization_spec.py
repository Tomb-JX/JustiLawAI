"""Tests for normalization_spec.py — engine-side date/amount normalization."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from normalization_spec import (cn_to_number, normalize_amount,  # noqa: E402
                                 normalize_count, normalize_date,
                                 normalize_date_range, normalize_duration,
                                 validate_amount_against_source,
                                 validate_date_against_source)


# --- cn_to_number ---

def test_cn_arabic():
    assert cn_to_number("123") == 123.0
    assert cn_to_number("1.2万") == 12000.0
    assert cn_to_number("3.5亿") == 350000000.0


def test_cn_chinese():
    assert cn_to_number("三千五百") == 3500
    assert cn_to_number("十五") == 15
    assert cn_to_number("一万二千") == 12000


# --- normalize_amount ---

def test_exact_amount():
    r = normalize_amount("3910元")
    assert r == {"min": 3910, "max": 3910}


def test_open_amount():
    r = normalize_amount("万元以上")
    assert r == {"min": 10000, "max": None}
    r2 = normalize_amount("逾5000元")
    assert r2 == {"min": 5000, "max": None}


def test_yu_amount():
    r = normalize_amount("三千余元")
    assert r == {"min": 3000, "max": 3999}
    r2 = normalize_amount("1万余元")
    assert r2 == {"min": 10000, "max": 19999}
    r3 = normalize_amount("12500余元")
    assert r3 == {"min": 12500, "max": 12599}


def test_approximate_amount():
    r = normalize_amount("约5万元")
    assert r == {"min": 45000, "max": 55000}


def test_few_amount():
    r = normalize_amount("数百元")
    assert r == {"min": 200, "max": 999}
    r2 = normalize_amount("数千元")
    assert r2 == {"min": 2000, "max": 9999}


def test_near_amount():
    r = normalize_amount("近万元")
    assert r == {"min": 9000, "max": 10000}


def test_below_amount():
    r = normalize_amount("不足1000元")
    assert r == {"min": 0, "max": 1000}


def test_range_amount():
    r = normalize_amount("3000-3999")
    assert r == {"min": 3000, "max": 3999}


def test_masked_amount():
    assert normalize_amount("xx元") is None
    assert normalize_amount("XXXX元") is None


def test_empty_amount():
    assert normalize_amount("") is None
    assert normalize_amount(None) is None


# --- normalize_date ---

def test_exact_date():
    d, status = normalize_date("2025-08-15")
    assert d == date(2025, 8, 15) and status == "明确"


def test_month_only():
    d, status = normalize_date("2025年8月")
    assert d == date(2025, 8, 1) and status == "推断"


def test_year_only():
    d, status = normalize_date("2025年")
    assert d == date(2025, 7, 1) and status == "推断"


def test_invalid_date():
    assert normalize_date("2025-02-30") is None
    assert normalize_date("") is None


# --- normalize_duration ---

def test_days():
    assert normalize_duration("15天") == 15.0


def test_months():
    assert normalize_duration("三个月") == 90.0
    assert normalize_duration("3个月") == 90.0


def test_years():
    assert normalize_duration("一年") == 365.0


def test_chinese_duration():
    assert normalize_duration("十五天") == 15.0


def test_empty_duration():
    assert normalize_duration("") is None


# --- validate_against_source ---

def test_validate_amount_consistent():
    assert validate_amount_against_source({"min": 3910, "max": 3910},
                                          "现场查获赌资 3910 元") is True


def test_validate_amount_inconsistent():
    assert validate_amount_against_source({"min": 5000, "max": 5000},
                                          "现场查获赌资 3910 元") is False


def test_validate_amount_ambiguous():
    # 多个金额提及，无法机械对账 → True
    assert validate_amount_against_source({"min": 100, "max": 100},
                                          "赌资 100 元和 200 元") is True


def test_validate_date_consistent():
    assert validate_date_against_source("2025-08-15", "于2025年8月15日") is True


def test_validate_date_inconsistent():
    assert validate_date_against_source("2025-08-15", "于2025年9月1日") is False


# --- normalize_date_range（E-05 补全，供 unify supply_packet / evidence_graph 调用）---

def test_date_range_same_year_month_precision():
    r = normalize_date_range("2025年1月至3月")
    assert r == {"start": date(2025, 1, 1), "end": date(2025, 3, 31), "days": 90}


def test_date_range_explicit_cross_year():
    r = normalize_date_range("2025年12月至2026年1月")
    assert r["start"] == date(2025, 12, 1) and r["end"] == date(2026, 1, 31)


def test_date_range_implicit_cross_year():
    # 右段缺年且 end<start → 年 +1 重试
    r = normalize_date_range("2025年12月至1月")
    assert r["start"] == date(2025, 12, 1) and r["end"] == date(2026, 1, 31)


def test_date_range_day_precision_endpoints():
    r = normalize_date_range("2025年1月5日至10日")
    assert r["start"] == date(2025, 1, 5) and r["end"] == date(2025, 1, 10)


def test_single_date_is_not_a_range():
    # 单点日期须返回 None，由调用方回退 normalize_date（birth 日期不得当区间）
    assert normalize_date_range("1995年11月28日") is None
    assert normalize_date_range("2025年3月") is None


def test_date_range_invalid():
    assert normalize_date_range("") is None
    assert normalize_date_range(None) is None
    # 无法定位到年 → None
    assert normalize_date_range("1月5日至10日") is None


# --- normalize_count（E-05 补全，供 unify supply_packet count/age 调用）---

def test_count_exact():
    assert normalize_count("3台") == {"min": 3, "max": 3, "exact": True}
    assert normalize_count("30岁") == {"min": 30, "max": 30, "exact": True}
    assert normalize_count("三人") == {"min": 3, "max": 3, "exact": True}


def test_count_range_not_exact():
    assert normalize_count("3至5人") == {"min": 3, "max": 5, "exact": False}


def test_count_bound_and_vague_not_exact():
    assert normalize_count("至少3次") == {"min": 3, "max": None, "exact": False}
    assert normalize_count("20余人") == {"min": 20, "max": None, "exact": False}
    assert normalize_count("约5人") == {"min": 5, "max": 5, "exact": False}
    assert normalize_count("不超过10人") == {"min": 0, "max": 10, "exact": False}


def test_count_invalid():
    assert normalize_count("") is None
    assert normalize_count("赌博") is None