"""收割与解析单测：合成 HTML/正文复刻 2026-10-15 实测遇到的页面形态（不含真实个人信息），不联网。

运行（仓库根目录）：python -m pytest research/discretion/harvest/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harvest import attachments, fill, filter_titles, main_text, page_templates  # noqa: E402
from parse import cn2int, field_values, outcome_from, parse_date, parse_page, split_items  # noqa: E402

DECISION = """保定市某县政府网——某公（天）行罚决字〔2024〕0325号行政处罚决定书
当前位置：首页 >> 行政执法公示专栏
某县公安局
行政处罚决定书
某公（天）行罚决字〔2024〕0325号
违法行为人李xx，男，xxxx年xx月xx日出生，无违法犯罪经历。
现查明：2024年4月18日12时40分，在xx县xx村朱xx家同王xx等人以打麻将的方式进行赌博，现场查获赌博资金共计3078元。
以上事实有询问笔录、接处警视频等证据证实。
根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对李xx行政拘留十日，并处罚款伍佰元整。
被处罚人如不服本决定，可以在收到本决定书之日起六十日内申请行政复议。
某县公安局
二〇二四年四月十九日"""

FIELDS = """魏公（泊）行罚决字〔2024〕0270号
决定书（通知书）文号： 魏公（泊）行罚决字〔 2024 〕 0270 号
行政相对人名称： 辛 xx
违法事实： 2024 年 03 月 06 日在工作中发现，辛 xx 以"快 x"的方式参与赌博，充值 23000 元左右用于赌博。
违反的法律条款： 《中华人民共和国治安管理处罚法》第七十条
处罚类型： 行政处罚
做出处罚的法律依据条款： 根据《中华人民共和国治安管理处罚法》第七十条之规定
处罚结果： 行政拘留十日，并处罚款伍佰元整。
决定 ( 通知 ) 日期： 2024-03-06
实施机关： 魏县公安局"""

SUMMARY = """1、违法行为人张某，于2026年1月26日因赌博的违法行为，被玉溪市公安局红塔分局根据《中华人民共和国治安管理处罚法》第八十二条、第二十条第五项之规定，对张某给予十日拘留的处罚。行政处罚决定书文号：玉红公（凤凰）行罚决字〔2026〕51号。
2、违法行为人花某，于2026年1月26日因未按规定执行住宿实名制的违法行为，被玉溪市公安局红塔分局凤凰派出所根据《中华人民共和国治安管理处罚法》第六十七条第一款之规定，对花某给予警告的处罚。行政处罚决定书文号：玉红公（凤凰）行罚决字〔2026〕50号。
3、违法行为人吴某，于2026年5月25日因实施赌博的违法行为，被玉溪市公安局红塔分局根据《中华人民共和国治安管理处罚法》第八十二条、第十一条第一款之规定，对吴某给予行政拘留十日，并处罚款一千元的处罚，并收缴赌资现金人民币600元。行政处罚决定书文号：玉红公（北）行罚决字〔2026〕101号。"""

REVIEW = """武义县人民政府行政复议决定书 金武政复决字〔2024〕132号
申请人：王某某 被申请人：武义县公安局
申请人不服武义县公安局作出的武公白洋行罚决字【2024】01567号行政处罚决定书，该决定依据第七十条对申请人作出行政拘留12日的处罚。
经审理查明：2024年7月，申请人在某棋牌室以"牛牛"方式参与赌博，个人赌资800元。
本机关认为：被申请人认定事实清楚，证据确凿，适用依据正确，程序合法，处罚适当。
根据《中华人民共和国行政复议法》第六十八条之规定，本机关决定如下：维持被申请人作出的行政处罚决定。
武义县人民政府
2025年7月21日"""


def page(text_title: str = "") -> dict:
    return {"page_id": "p1", "manifest_id": "W-000001", "url": "https://www.x.gov.cn/a.html",
            "fetched_at": "2026-10-15T12:00:00", "site": "x.gov.cn", "title": text_title, "publisher": ""}


def test_cn2int_and_dates():
    assert cn2int("十") == 10 and cn2int("十三") == 13 and cn2int("伍佰") == 500 and cn2int("壹仟陆佰") == 1600
    assert cn2int("一千") == 1000 and cn2int("3,000") == 3000 and cn2int("两千") == 2000 and cn2int("x") is None
    assert parse_date("二〇二四年四月十九日") == "2024-04-19"
    assert parse_date("2024年04月29日晚") == "2024-04-29"
    assert parse_date("2024-03-06") == "2024-03-06"
    assert parse_date("2025年2月至3月") == "2025-02"


def test_narrative_decision():
    c = parse_page(page(), DECISION)[0]
    assert c["segmented"] and c["source_type"] == "处罚决定书"
    assert "打麻将" in c["text_facts"] and "决定" not in c["text_facts"]
    assert "证据证实" in c["text_evidence"]
    oc = c["outcome"]
    assert (oc["type"], oc["detention_days"], oc["fine"]) == ("拘留并处罚款", 10, 500)
    assert oc["articles"] == ["治安管理处罚法第七十条"] and oc["law_version"] == "旧法"
    assert c["decision_date"] == "2024-04-19" and c["behavior_date"] == "2024-04-18"
    assert c["gambling"] == "是" and c["in_scope"] and c["completeness"] == {"has_amount": True, "has_outcome": True}


def test_field_format():
    fv = field_values(FIELDS)
    assert "赌博" in fv["facts"] and "拘留" in fv["result"] and "魏县公安局" in fv["authority"]
    c = parse_page(page(), FIELDS)[0]
    assert c["outcome"]["type"] == "拘留并处罚款" and c["decision_date"] == "2024-03-06"
    assert c["in_scope"] and c["completeness"]["has_amount"]


def test_title_word_is_not_a_field_label():
    assert "result" not in field_values("某公（天）行罚决字〔2025〕0692号行政处罚决定书\n附件：xx.jpg")


def test_summary_split_and_per_item_gambling():
    items = split_items(SUMMARY)
    assert len(items) == 3
    cases = parse_page(page(), SUMMARY)
    assert [c["id"] for c in cases] == ["W-000001-1", "W-000001-2", "W-000001-3"]
    assert [c["gambling"] for c in cases] == ["是", "否", "是"]
    assert cases[0]["outcome"]["detention_days"] == 10 and cases[0]["outcome"]["law_version"] == "新法"
    assert cases[2]["outcome"]["fine"] == 1000 and "赌资" in cases[2]["outcome"]["confiscation"]


def test_review():
    c = parse_page(page("武义县人民政府行政复议决定书"), REVIEW)[0]
    assert c["source_type"] == "行政复议决定书" and c["review"]["result"] == "维持"
    assert "牛牛" in c["text_facts"] and "本机关认为" in c["text_review"]
    assert c["outcome"]["detention_days"] == 12 and c["authority"].endswith("公安局")


def test_attachment_only_page_needs_ocr():
    p = {**page(), "attachment_files": ["raw/x.gov.cn/p1_att1.jpg"]}
    c = parse_page(p, "某公（天）行罚决字〔2025〕0692号行政处罚决定书\n附件：某公（天）行罚决字〔2025〕0692号行政处罚决定书.jpg")[0]
    assert c["needs_ocr"] and c["gambling"] == "待定" and not c["in_scope"]


def test_outcome_variants():
    assert outcome_from("现决定给予警告。")["type"] == "警告"
    assert outcome_from("决定不予行政处罚。")["type"] == "不予处罚"
    oc = outcome_from("依据第七十条决定行政拘留十日；根据第十六条之规定，现决定合并执行行政拘留十三日，并处罚款伍佰元整。")
    assert oc["detention_days"] == 13 and oc["fine"] == 500
    assert outcome_from("根据修订前《中华人民共和国治安管理处罚法》第七十条之规定，给予罚款五百元")["law_version"] == "旧法"


def test_main_text_and_attachments():
    html = ('<div class="nav">首页 新闻</div><div class="c"><p>某公（天）行罚决字〔2025〕0692号行政处罚决定书</p>'
            '<p>附件：<a href="/viewFile.do?type=2&amp;filename=a.jpg&amp;file=1/2025/a.jpg">决定书.jpg</a></p>'
            '<img src="/images/logo.png"></div><div>网站地图 版权所有</div><a href="/x/b.pdf">页脚PDF</a>')
    assert main_text(html).startswith("某公（天）行罚决字") and "网站地图" not in main_text(html)
    att = attachments(html, "https://www.x.gov.cn/xzzfcon-467-1.html")
    assert att == ["https://www.x.gov.cn/viewFile.do?type=2&filename=a.jpg&file=1/2025/a.jpg"]  # 无 logo、无页脚 PDF


def test_page_templates():
    js = "<script>function goPage(page){var strHref='?view=xzzflist&ccid=467';}</script>"
    tpls = page_templates(js, "https://www.x.gov.cn/xzzflist-467-more.html")
    assert "https://www.x.gov.cn/xzzflist-467-more.html?view=xzzflist&ccid=467&page={n}" in tpls
    trs = "<script>createPageHTML(20, 0, 'index', 'html');</script>"
    assert fill([t for t in page_templates(trs, "http://www.x.gov.cn/a/b/") if "index_" in t][0], 3) == "http://www.x.gov.cn/a/b/index_2.html"
    nxt = '<a href="/zfxxgk/cfqz_2">下一页</a>'
    assert "https://www.x.gov.cn/zfxxgk/cfqz_{n}" in page_templates(nxt, "https://www.x.gov.cn/zfxxgk/cfqz")


def test_filter_titles():
    mixed = [("u1", "辛集市交通运输局行政处罚决定书冀0181交罚"), ("u2", "辛集市公安局辛公(张)行罚决字〔2023〕0305号"),
             ("u3", "辛环罚决〔2026〕0036号"), ("u4", "关于赌博案件的处罚")]
    assert [u for u, _ in filter_titles(mixed)] == ["u2", "u4"]
    names = [("a", "王某某"), ("b", "易某某"), ("c", "宗某某")]
    assert filter_titles(names) == names  # 标题只有人名：看不出部门，全留
