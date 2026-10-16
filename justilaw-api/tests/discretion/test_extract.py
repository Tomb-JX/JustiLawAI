"""M1 取值规范化与证据定位（不调用模型）。"""
from datetime import date

import pytest

from app.discretion import extract as ex
from app.discretion.schema import AmountRange


def test_cn_numbers():
    assert ex.cn_to_number("三千") == 3000
    assert ex.cn_to_number("二十三") == 23
    assert ex.cn_to_number("一万二千") == 12000
    assert ex.cn_to_number("1.2万") == 12000
    assert ex.cn_to_number("十五") == 15


def test_parse_amount():
    assert ex.parse_amount("800元") == AmountRange(min=800, max=800)
    assert ex.parse_amount("3000-3999") == AmountRange(min=3000, max=3999)
    assert ex.parse_amount("三千余元") == AmountRange(min=3000, max=3999)
    assert ex.parse_amount("1万余元") == AmountRange(min=10000, max=19999)
    assert ex.parse_amount("人民币52670元") == AmountRange(min=52670, max=52670)
    assert ex.parse_amount("约5万元") == AmountRange(min=45000, max=55000)
    assert ex.parse_amount("50余万元") == AmountRange(min=500000, max=599999)
    assert ex.parse_amount("十余万元") == AmountRange(min=100000, max=199999)
    assert ex.parse_amount("math.ceil(173890/2)") is None
    assert ex.parse_amount("若干") is None


@pytest.mark.parametrize("text, lo, hi", [
    ("赌资在万元以上", 10000, None),        # W-000608 的原文写法
    ("一万元以上", 10000, None),
    ("五千元以上", 5000, None),
    ("达5000元以上", 5000, None),
    ("12500元以上", 12500, None),          # 不是 12500–12999，也不是确切数
    ("逾5000元", 5000, None),
    ("至少2000元", 2000, None),
    ("不足1000元", 0, 1000),
    ("500元以下", 0, 500),
    ("近万元", 9000, 10000),
    ("数千元", 2000, 9999),
    ("数百元", 200, 999),
    ("数万元", 20000, 99999),
    ("12500余元", 12500, 12599),           # 余 = 末位非零数位上不足一个单位
    ("一万二千余元", 12000, 12999),
    ("7000余元", 7000, 7999),
])
def test_parse_amount_bounds(text, lo, hi):
    r = ex.parse_amount(text)
    assert (r.min, r.max) == (lo, hi)


def test_parse_other_types():
    assert ex.parse_int("三人") == 3 and ex.parse_int("12名") == 12
    assert ex.parse_bool("是") is True and ex.parse_bool("否") is False
    assert ex.parse_date("2025年8月") == (date(2025, 8, 1), True)
    assert ex.parse_date("2026-03-12") == (date(2026, 3, 12), False)


def test_normalize_by_field_type():
    assert ex.normalize("amounts.commission", "2000元").min == 2000
    assert ex.normalize("conduct.behavior_type", "为赌博提供条件").value == "为赌博提供条件"
    assert ex.normalize("persons.participant_count", "四人") == 4
    assert ex.normalize("conduct.behavior_type", "胡说") is None


def test_locate_evidence():
    src = "被告人胡某在其经营的副食店内为他人赌博提供场地及赌具，从中抽头非法获利2000元。"
    assert ex.locate("从中抽头非法获利2000元", src) == [(src.find("从中"), src.find("元。") + 1)]
    assert ex.locate("非法获利9000元并购买房产一套", src) is None


def test_locate_tolerates_model_formatting():
    """2026-10-15 实测中模型复述原文的三种改动（M1 探针 v1）。"""
    src = "当场缴获投注单77张、收受的投注现金2900元。利用香港“六合彩”开奖号码，按照投注额3%或10%分得提成。"
    # 1. 在汉字与数字之间插空格
    a, b = ex.locate("当场缴获投注单 77 张", src)[0]
    assert src[a:b] == "当场缴获投注单77张"
    # 2. 改变引号样式
    a, b = ex.locate("利用香港‘六合彩’开奖号码", src)[0]
    assert src[a:b] == "利用香港“六合彩”开奖号码"
    # 3. 用省略号省略中间部分：拆段按顺序定位
    spans = ex.locate("当场缴获投注单77张...按照投注额3%或10%分得提成", src)
    assert len(spans) == 2 and src[spans[1][0]:spans[1][1]] == "按照投注额3%或10%分得提成"
    # 省略号两侧顺序颠倒或片段过短都不成立
    assert ex.locate("按照投注额3%或10%分得提成...当场缴获投注单77张", src) is None
    assert ex.locate("当...提成", src) is None


def test_build_elements_drops_unsupported():
    src = "被告人胡某为他人赌博提供场地，从中抽头非法获利2000元。"
    items = [
        {"path": "amounts.commission", "value": "2000元", "status": "明确", "quote": "从中抽头非法获利2000元"},
        {"path": "persons.participant_count", "value": "5", "status": "明确", "quote": "共有五人参赌"},   # 编造的证据
        {"path": "conduct.behavior_type", "value": "为赌博提供条件", "status": "明确", "quote": "为他人赌博提供场地"},
    ]
    e, dropped = ex.build_elements(items, src)
    assert e.amounts.commission.value.min == 2000
    assert e.amounts.commission.evidence[0].start == src.find("从中抽头")
    assert e.persons.participant_count.value is None
    assert [d["reason"] for d in dropped] == ["证据在原文中找不到"]


def test_output_schema_lists_all_fields():
    s = ex.output_schema()
    assert set(s["properties"]["items"]["items"]["properties"]["path"]["enum"]) == set(ex.FIELD_PATHS)
