"""2026-10-16 晚代理试标发现的脱敏漏网（r1 交付）的回归测试：表格续行切开的人名与日期、带名字用字的遮挡写法残字、
"宋某某明"、非常见姓的"X某Y"、"在×××开设"。合成样例，姓名为虚构。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import cell_wraps, deidentify  # noqa: E402
from r6_scan import scan_text  # noqa: E402

TWO_COL = ("|违法事实  |经查：2021年8月份至今，行为人张 |\r\n|          |伟在某市等地，通过微信下注参与六合彩赌博，涉案金额"
           "共计为9000元左右。行为人张伟后于2022年8月13 |\r\n|          |日，自某派出所投案自首。 |\r\n|处罚依据  |治安管理处罚法 |")
ONE_COL = "|另查明，违法行为人钱 |\n|大勇于2016年7月份开始至案发在孙小飞开设的棋牌室内多次参与赌博。违法行为人甲 |\n|对违法事实供认不讳。|"


def test_cell_wrap_names_and_dates_are_masked():
    t = deidentify(TWO_COL, behavior=None).text
    assert "张" not in t and "伟在" not in t and "行为人甲" in t
    assert "13日" not in t and "13" not in t and "2022年8月" in t     # 跨续行的日也要截到月
    assert "处罚依据" in t                                             # 两栏表的新一行不并
    t = deidentify(ONE_COL, behavior=None).text
    assert "钱" not in t and "大勇" not in t and "孙小飞" not in t


def test_cell_wraps_keeps_new_rows():
    assert cell_wraps("|处罚结果 |罚款五百元 |\n|处罚依据 |治安管理处罚法 |") == []
    assert len(cell_wraps(TWO_COL)) == 2


def test_projection_through_cell_wraps():
    d = deidentify(TWO_COL, behavior=None)
    seg = "自某派出所投案自首。"
    a = TWO_COL.find(seg)
    assert d.text[d.project(a, is_end=False): d.project(a + len(seg), is_end=True)] == seg


def test_masked_with_given_char_every_occurrence():
    t = deidentify("违法行为人吴某芳和陈某丽、过某华、陈某强等人以干二八杠的方式赌博，吴某芳携带赌资20元，输20元。",
                   behavior=None).text
    assert "芳" not in t and "华" not in t and "过某" not in t and t.count("甲") == 2
    t = deidentify("违法行为人郭xx、郭x青在郭xx家里利用牌九进行赌博，郭x青携带赌资170元。", behavior=None).text
    assert "青" not in t
    # 源文名字后多一个遮挡残字（"周x山x2022年"）：残字一起换掉，免得和前一个字拼成新的遮挡写法
    t = deidentify("被处罚人张xx，男。经核查周x山x2022年3月开始代理赌博软件。以上事实有周x山的陈述证实。", behavior=None).text
    assert "山" not in t and "x" not in t


def test_double_mou_with_given_char():
    t = deidentify("何某某伙同林某某、宋某某明等人多次在某村赌博。", behavior=None).text
    assert "宋" not in t and "明等" not in t


def test_r6_catches_wrapped_real_name_without_review_false_positives():
    assert any(h.cat == "person_role" and h.hard for h in scan_text("经查，行为人张 |\r\n|      |伟在某市赌博。"))
    assert any(h.cat == "date_day" for h in scan_text("行为人甲后于2022年8月13 |\r\n|      |日投案。"))
    review = "被申请人民警当场向申请人宣读后并依法记录。被申请人于同日对申请人作出处罚决定。"
    assert not [h for h in scan_text(review) if h.hard]
