"""发现层 L3 分诊单测。样例均为合成文本，复刻 M1 抽查中真实出现过的页面形态（不含真实个人信息）。

运行（仓库根目录）：python -m pytest research/discretion/discover/tests -q
"""

from __future__ import annotations

import pytest

from triage import classify, dedupe_by_doc_no, doc_no, gambling_status, law_article, strip_citations, triage_hit

DECISION = ("违法行为人张xx，男。现查明：2024年4月1日，张xx在李xx家中以打麻将的方式进行赌博，赌资300元。"
            "根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对张xx行政拘留五日。")


@pytest.mark.parametrize("title,content,expected", [
    ("定兴公(天)行罚决字〔2024〕0325号行政处罚决定书", DECISION, "处罚决定"),
    ("政府信息公开", DECISION, "处罚决定"),  # 标题泛化，靠摘录认出
    ("武义县人民政府行政复议决定书 金武政复决字〔2024〕132号", "申请人：王某某 被申请人：武义县公安局", "复议"),
    ("某县政府信息公开", "1、违法行为人杨某因赌博……2、违法行为人祁某因赌博……", "处罚汇总"),
    ("某县公安局2026年4月份行政处罚结果", "序号 姓名 案由 赌博 处罚", "执法结果表"),
    ("定安县公安局2024年7月份行政处罚、行政强制汇总表", "5 陈某参与网络赌博案 行政处罚", "执法结果表"),
    ("中华人民共和国公安部令", "第九条 行政案件由违法行为地的公安机关管辖。由违法行为人居住地公安机关管辖更为适宜的……赌博的案件除外", "法规清单"),
    ("湖南省公安行政处罚裁量权基准实施办法的通知", "各市州公安局：现将……当事人……处罚决定……印发给你们", "法规清单"),
    ("四人被行政拘留！某县公安局快速查处一起赌博案", "为严厉打击赌博违法犯罪活动……近日，某派出所查处一起赌博案", "新闻案例"),
    ("【行政处罚】某县公安局赌博案件行政处罚案例", "白某等人涉嫌赌博一案简要案情：在棋牌馆内以麻将赌博", "处罚决定"),
    ("起诉书(张某赌博案)", "某区人民检察院起诉书", "诉讼刑事文书"),
    ("关于对某某的不予行政处罚决定书", "现查明：……情节轻微，决定不予行政处罚", "不予处罚"),
])
def test_classify(title, content, expected):
    assert classify(title, content) == expected


def test_single_decision_citing_prior_case_is_not_summary():
    c = ("辛公(张)行罚决字〔2023〕0305号行政处罚决定书 被处罚人郭某。违法前科：因开设赌场案被移送起诉，"
         "曾被辛公(张)行罚决字〔2022〕0100号处罚。现查明：郭某等人赌博。")
    assert classify("辛集市公安局辛公(张)行罚决字〔2023〕00305号行政处罚决定书", c) == "处罚决定"


def test_citation_alone_is_not_gambling():
    text = ("《中华人民共和国治安管理处罚法》第十一条规定：“办理治安案件所查获的毒品、淫秽物品等违禁品，赌具、赌资，"
            "吸食、注射毒品的用具以及直接用于实施违反治安管理行为的本人所有的工具，应当收缴，按照规定处理。”"
            "申请人因殴打他人被处罚。")
    assert "赌" not in strip_citations(text)
    assert gambling_status("行政复议决定书", text, "复议") == "否"


def test_article_70_quote_alone_is_not_gambling():
    text = "第七十条规定：“以营利为目的，为赌博提供条件的，或者参与赌博赌资较大的，处五日以下拘留。”本案系噪音扰民。"
    assert gambling_status("行政复议决定书", text, "复议") == "否"


def test_prior_record_is_not_gambling():
    # 醉驾决定书里写着前科"曾因赌博被拘留"（M4 辛集、五河）
    text = ("被处罚人王某。违法前科：2024年05月因赌博被辛集市公安局行政拘留三日。"
            "现查明：2025年01月04日，王某醉酒后驾驶小型轿车。根据道路交通安全法之规定，现决定罚款。")
    assert gambling_status("辛集市公安局行政处罚决定书", text, "处罚决定") == "待定"
    still = "违法经历：2015年1月因赌博被拘留十日。现查明：2024年，马某在家中以打麻将的方式进行赌博。"
    assert gambling_status("行政处罚", still, "处罚决定") == "是"


def test_unquoted_jurisdiction_clause_is_not_gambling():
    text = ("申请人：沈某 被申请人：杭州市公安局萧山区分局。由违法行为人居住地公安机关管辖更为适宜的，可以由违法行为人"
            "居住地公安机关管辖，但是涉及卖淫、嫖娼、赌博、毒品的案件除外。本案系消防违法。")
    assert gambling_status("案号：杭萧政复〔2021〕311号", text, "复议") == "待定"


def test_enforcement_measure_report_and_news_types():
    assert classify("毕某等人赌博案行政强制结果", "证据保全决定书编号：当公(太)证保决字〔2022〕276号 当事人姓名：毕某") == "强制措施"
    assert classify("温岭市公安局2024年度行政执法统计年报", "共计罚没收入……加大了对黄赌等案件的执法力度") == "法规清单"
    assert classify("应急响应等级刚下调，他们顶风作案！抓！", "派出所接报，有人在聚众赌博，民警赶赴现场") == "新闻案例"


def test_truncated_police_case_is_pending():
    text = "申请人：沈某 被申请人：杭州市公安局拱墅区分局。申请人不服行罚决字[2023]×号《行政处罚决定书》……"
    assert gambling_status("行政复议决定书", text, "复议") == "待定"


def test_mahjong_counts_as_gambling():
    assert gambling_status("政府信息公开", "申请人请求退还收缴的4张麻将桌", "复议") == "是"


def test_doc_no_prefers_review_number_for_review():
    content = "金武政复决字〔2024〕132号 申请人不服武公白洋行罚决字【2024】01567号行政处罚决定书"
    no, year = doc_no("行政复议决定书", content, "复议")
    assert "复决字" in no and year == "2024"
    no2, _ = doc_no("", content, "处罚决定")
    assert "行罚决字" in no2


def test_law_article():
    assert law_article("根据治安管理处罚法第八十二条之规定") == "82"
    assert law_article("第七十条……第八十二条") == "70/82"


def test_priority_boost_for_2026_and_pending_low():
    hit = {"url": "https://www.x.gov.cn/a", "title": "博公(塔)行罚决字〔2026〕17号", "content": DECISION}
    assert triage_hit(hit)["priority"] == 4  # 处罚决定 3 + 2026 年 1
    pend = {"url": "https://www.x.gov.cn/b", "title": "行政复议决定书",
            "content": "申请人：沈某 被申请人：某市公安局。申请人不服行政处罚决定书"}
    assert triage_hit(pend)["gambling"] == "待定" and triage_hit(pend)["priority"] == 1


def test_dedupe_by_doc_no_keeps_www_host():
    a = {"url": "https://zwfw.d.gov.cn/1", "host": "zwfw.d.gov.cn", "doc_no": "定兴公(田)行罚决字〔2024〕0474号", "doc_type": "处罚决定"}
    b = {"url": "https://www.d.gov.cn/1", "host": "www.d.gov.cn", "doc_no": "定兴公(田)行罚决字〔2024〕0474号", "doc_type": "处罚决定"}
    kept = dedupe_by_doc_no([a, b])
    assert len(kept) == 1 and kept[0]["host"] == "www.d.gov.cn" and kept[0]["alt_urls"] == [a["url"]]
