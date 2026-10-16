"""北大法宝导出解析单测：合成样本复刻 2026-10-16 实样的两种形态（不含真实个人信息），不联网。

运行（仓库根目录）：python -m pytest research/discretion/collect/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pkulaw_ingest import (  # noqa: E402
    build_judgment_record,
    build_record,
    catalog_stats,
    cn2int,
    cn_num_to_arabic_article,
    is_narrative,
    outcome_from,
    parse_any_doc,
    parse_articles,
    parse_catalog,
    parse_date,
    parse_enforcement_doc,
    penalty_articles,
    pkulaw_id_from_name,
    province_of,
)

# 复刻「目录列表.xls」导出的 CSV（表头两行 + 字段行 + 数据行 + 版权页脚）
CATALOG_CSV = """北大法宝V6-行政执法-行政执法字段表单,,,,,,,,,,
搜索条件：案件名称： 赌博；,,,,,下载时间：2026-10-16,,,,,
序号,标题,执法机关,发文案号,公布日期,行政相对人,执法依据,处罚种类,执法地域,原文链接,罚没总金额（万元）
_1,张*三赌博案(某公(某新)行罚决字〔2025〕00289号),某县公安局,某公(某新)行罚决字〔2025〕00289号,2025.12.29,,中华人民共和国治安管理处罚法(2012修正) 第70条   ,罚款、没收违法所得、没收非法财物,某省,https://www.pkulaw.com/apy/0000bdfb.html,0.03
_2,李*四赌博案(某公(某新)行罚决字〔2025〕00290号),某县公安局,某公(某新)行罚决字〔2025〕00290号,2025.12.25,,中华人民共和国治安管理处罚法(2025修订) 第82条,行政拘留,某省,https://www.pkulaw.com/apy/1111bdfb.html,0
© 北大法宝：(www.pkulaw.com)专业提供法律信息、法学知识和法律软件领域各类解决方案。北大法宝为您提供丰富的参考资料，正式引用法规条文时请与标准文本核对。
扫码添加法小宝微信号,,,,,手机扫一扫关注北大法宝公众号,,,,
,,,,,,,,,,
"""

# 复刻 .doc 经 antiword 取出的文本（元数据块 + 决定表 + 页脚）
DOC_TEXT = """   张*三赌博案(某公(某新)行罚决字〔2025〕00289号)

    主题分类： 公安

    处罚种类： 罚款、没收违法所得、没收非法财物

    行政相对人： 张*三

    执法级别： 省级

    执法机关：某县公安局

    执法地域： 某省

    公布日期：2025.12.29

    发文案号：某公(某新)行罚决字〔2025〕00289号

    罚没情况：对张*三赌博罚款三百元

    执法依据： 中华人民共和国治安管理处罚法(2012修正)第70条

   |行政处罚决定书文号                      |某公(某新)行罚决字〔2025〕00289号     |
|被处罚对象                              |张*三                                   |
|处罚事由                                |赌博                                    |
|处罚依据                                |《中华人民共和国治安管理处罚法》第七十条  |
|处罚结果                                |罚款三百元                              |
|处罚决定日期                            |2025-12-29                              |
|处罚机关                                |某县公安局                    |

©北大法宝：（www.pkulaw.com）专业提供法律信息、法学知识和法律软件领域各类解决方案。
原文链接：https://www.pkulaw.com/apy/9445d6e6deb7c9d2da58383f0133290de14dc328de1b2154bdfb.html
"""

DOC_NAME = "张*三赌博案(某公(某新)行罚决字〔2025〕00289号)(FBM-CLI.ALE.47644244).doc"


def test_cn2int():
    assert cn2int("三百") == 300
    assert cn2int("十") == 10
    assert cn2int("十日") is None          # 带单位"日"的不认，由调用方的正则先剥掉
    assert cn2int("伍佰") == 500
    assert cn2int("1382") == 1382
    assert cn2int("两千") == 2000
    assert cn2int("1,382") == 1382
    assert cn2int("三十日") is None


def test_article_normalization():
    assert cn_num_to_arabic_article("第82条") == "第八十二条"
    assert cn_num_to_arabic_article("第70条") == "第七十条"
    assert cn_num_to_arabic_article("第八十二条") == "第八十二条"
    assert cn_num_to_arabic_article("第144条") == "第一百四十四条"


def test_parse_date():
    assert parse_date("2025.12.29") == "2025-12-29"
    assert parse_date("2025-12-29") == "2025-12-29"
    assert parse_date("2025年12月29日") == "2025-12-29"
    assert parse_date("二〇二五年十二月二十九日") == "2025-12-29"
    assert parse_date("下载时间：2026-10-16") == "2026-10-16"


def test_catalog_parse(tmp_path):
    p = tmp_path / "catalog_1.csv"
    p.write_text(CATALOG_CSV, encoding="utf-8")
    meta, rows = parse_catalog(p)
    assert meta["library"].startswith("北大法宝V6-行政执法")
    assert meta["search"] == "案件名称： 赌博"
    assert meta["download_time"] == "2026-10-16"
    assert len(rows) == 2                       # 版权行与空行都没有混进来
    assert rows[0]["发文案号"] == "某公(某新)行罚决字〔2025〕00289号"
    assert rows[0]["公布日期"] == "2025-12-29"
    assert rows[0]["罚没总金额_元"] == 300
    assert rows[1]["罚没总金额_元"] == 0
    stats = catalog_stats(rows)
    assert stats["按法律版本与法条"]["旧法 第七十条"] == 1
    assert stats["按法律版本与法条"]["新法 第八十二条"] == 1
    assert stats["按处罚种类"]["行政拘留"] == 1


def test_pkulaw_id_from_name():
    assert pkulaw_id_from_name(DOC_NAME) == "CLI.ALE.47644244"   # 统一去掉 FBM- 前缀
    assert pkulaw_id_from_name("没有引证号.doc") == ""


# 复刻「司法案例库」的目录表（与行政执法库列完全不同；实测 2026-10-16）
CASES_CSV = """北大法宝V6-司法案例-司法案例字段表单,,,,,,,,
搜索条件：全 文： 赌博；,,,,,下载时间：2026-10-16,,,,
序号,标题,审理程序,案由,文书类型,审理法院,案件字号,审结日期,省份
1,贺某赌博一案,简易程序,刑事>妨害社会管理秩序罪>扰乱公共秩序罪>赌博罪;,判决书,湖南省溆浦县人民法院,(2026)湘1224刑初264号,2026.09.30,湖南省溆浦县人民法院
2,褚某、李某民间借贷纠纷一案,二审,民事>合同、准合同纠纷>借款合同纠纷>民间借贷纠纷;,判决书,江苏省常州市中级人民法院,(2026)苏04民终4141号,2026.09.30,江苏省常州市中级人民法院
© 北大法宝：(www.pkulaw.com)专业提供法律信息、法学知识和法律软件领域各类解决方案。
扫码添加法小宝微信号,,,,手机扫一扫关注北大法宝公众号,,,,
"""


def test_province_of():
    assert province_of("湖南省溆浦县人民法院") == "湖南省"
    assert province_of("新疆维吾尔自治区喀什地区中级人民法院") == "新疆维吾尔自治区"
    assert province_of("上海市公安局长宁分局") == "上海市"
    assert province_of("") == ""


def test_case_catalog_parse(tmp_path):
    """司法案例库目录：列名与行政执法库完全不同，表头行靠"已知列名 ≥3 个"识别，不写死列。"""
    p = tmp_path / "catalog_1.csv"
    p.write_text(CASES_CSV, encoding="utf-8")
    meta, rows = parse_catalog(p)
    assert meta["library"].startswith("北大法宝V6-司法案例")
    assert meta["search"] == "全 文： 赌博"
    assert len(rows) == 2
    assert rows[0]["案件字号"] == "(2026)湘1224刑初264号"
    assert rows[0]["审结日期"] == "2026-09-30"
    assert rows[0]["省份规范"] == "湖南省"
    stats = catalog_stats(rows)
    assert stats["按案由（一级）"] == {"刑事": 1, "民事": 1}
    assert stats["按案由（末级）"]["赌博罪"] == 1
    assert stats["按文书类型"] == {"判决书": 2}
    assert stats["按省份"]["湖南省"] == 1 and stats["按省份"]["江苏省"] == 1
    assert "按法律版本与法条" not in stats          # 司法案例库没有执法依据列，不产生这一项


def test_enforcement_doc_meta_and_table():
    p = parse_enforcement_doc(DOC_TEXT, filename=DOC_NAME)
    assert p["pkulaw_id"] == "CLI.ALE.47644244"
    assert p["doc_no"] == "某公(某新)行罚决字〔2025〕00289号"
    assert p["subject"] == "张*三"
    assert p["authority"] == "某县公安局"
    assert p["region_text"] == "某省"
    assert p["publish_date"] == "2025-12-29"
    assert p["decision_date"] == "2025-12-29"
    assert p["penalty_kinds"] == "罚款、没收违法所得、没收非法财物"
    assert p["result_text"] == "罚款三百元"
    assert p["subject_matter"] == "赌博"
    assert p["source_url"].startswith("https://www.pkulaw.com/apy/")
    assert "北大法宝" not in p["body"]           # 版权页脚已截掉


def test_articles_and_law_version():
    arts, ver = parse_articles("中华人民共和国治安管理处罚法(2012修正)第70条")
    assert arts == ["治安管理处罚法第七十条"] and ver == "旧法"
    arts, ver = parse_articles("中华人民共和国治安管理处罚法(2025修订) 第82条")
    assert arts == ["治安管理处罚法第八十二条"] and ver == "新法"
    arts, ver = parse_articles("《中华人民共和国治安管理处罚法》第七十条")
    assert arts == ["治安管理处罚法第七十条"] and ver == ""


def test_outcome_variants():
    oc = outcome_from("罚款三百元", "罚款、没收违法所得、没收非法财物")
    assert oc["type"] == "罚款" and oc["fine"] == 300 and oc["detention_days"] == 0
    assert "没收" in oc["confiscation"]

    oc = outcome_from("行政拘留十日并处罚款五百元", "行政拘留")
    assert oc["type"] == "拘留并处罚款" and oc["detention_days"] == 10 and oc["fine"] == 500

    oc = outcome_from("行政拘留五日", "行政拘留")
    assert oc["type"] == "拘留" and oc["detention_days"] == 5 and oc["fine"] == 0

    oc = outcome_from("合并执行拘留二十日", "行政拘留")
    assert oc["detention_days"] == 20

    oc = outcome_from("对张*三不予处罚", "")
    assert oc["type"] == "不予处罚"

    oc = outcome_from("", "", "")               # 抽不出结果 → 给解析告警留口子
    assert oc["type"] == ""


def test_record_is_outcome_only_and_flags():
    p = parse_enforcement_doc(DOC_TEXT, filename=DOC_NAME)
    cat_row = {"罚没总金额_元": 300}
    rec = build_record(p, harvest_date="2026-10-16", catalog_row=cat_row)
    assert rec["source_type"] == "执法公示"
    assert rec["behavior_date"] is None          # 硬缺口：执法公示不发行为日期
    assert rec["text_facts"] == ""
    assert rec["quality"]["outcome_only"] is True
    assert rec["quality"]["has_amount"] is False  # 事实段没有金额 → 不满足信息完整度
    assert rec["quality"]["law_version_raw"] == "2012修正"
    assert rec["quality"]["parse_warnings"] == ["facts_missing"]
    assert rec["outcome"]["articles"] == ["治安管理处罚法第七十条"]
    assert rec["outcome"]["law_version"] == "旧法"
    assert rec["event_hint"]["doc_seq"] == "00289"

    # 罚款额与目录表不一致 → 记告警（双源交叉核对）
    rec2 = build_record(p, catalog_row={"罚没总金额_元": 500})
    assert any(w.startswith("fine_mismatch") for w in rec2["quality"]["parse_warnings"])


def test_record_serializable_and_schema_keys():
    rec = build_record(parse_enforcement_doc(DOC_TEXT, filename=DOC_NAME))
    s = json.dumps(rec, ensure_ascii=False)      # 交付是 JSONL，必须可序列化
    assert "behavior_date" in json.loads(s)
    for key in ("id", "source_type", "source_ref", "harvest_date", "deidentified", "behavior_date",
                "decision_date", "authority", "region", "text_facts", "text_decision", "outcome", "review"):
        assert key in rec, key


# 复刻「法宝行政执法库」的叙述式决定书（河北/山东等地公示形态；人名与号码全部虚构）
NARRATIVE_TEXT = """　　某县公安局公安行政处罚决定书
某公（天）行罚决字〔2024〕0325号
　　违法行为人张某某，男，1990年1月1日出生，户籍地某省某县。
　　现查明：2024年4月18日12时40分，在某县某村李某某家，张某某同王某某等人以打麻将的方式进行赌博，现场查获赌博资金共计3078元。
　　以上事实有询问笔录、接处警视频等证据证实。
　　根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对张某某行政拘留十日，并处罚款伍佰元整。
　　被处罚人如不服本决定，可以在收到本决定书之日起六十日内向某县人民政府申请行政复议。
某县公安局
二〇二四年四月十九日

©北大法宝：（www.pkulaw.com）专业提供法律信息、法学知识和法律软件领域各类解决方案。
原文链接：https://www.pkulaw.com/apy/0000bdfb.html
【法宝引证码】CLI.ALE.50000001
1/1下载日期：2026-10-16
"""


def test_narrative_doc_parsed_as_facts():
    """叙述式决定书必须被识别成含事实的形态（A 类），而不是当字段式公示（B 类）。"""
    p = parse_any_doc(NARRATIVE_TEXT, filename="某公（天）行罚决字〔2024〕0325号(FBM-CLI.ALE.50000001).doc")
    assert p["form"].startswith("叙述式")            # 独立成篇形态
    assert p["pkulaw_id"] == "CLI.ALE.50000001"          # 引证码（正文里的，文件名去掉 FBM- 前缀）
    assert "以打麻将的方式进行赌博" in p["facts"]
    assert "询问笔录" in p["evidence"]
    assert "行政拘留十日" in p["decision"]

    rec = build_record(p, harvest_date="2026-10-16")
    assert rec["source_type"] == "处罚决定书"            # 有事实 → A 类
    assert rec["segmented"] is True
    assert rec["text_facts"] and rec["text_evidence"] and rec["text_decision"]
    assert rec["behavior_date"] == "2024-04-18"          # 事实段首个日期
    assert rec["decision_date"] == "2024-04-19"          # 落款日期
    oc = rec["outcome"]
    assert oc["type"] == "拘留并处罚款" and oc["detention_days"] == 10 and oc["fine"] == 500
    assert oc["articles"] == ["治安管理处罚法第七十条"] and oc["law_version"] == "旧法"
    assert rec["quality"]["outcome_only"] is False
    assert rec["quality"]["form"].startswith("叙述式")
    assert rec["quality"]["has_amount"] is True          # 事实段有"赌资"


def test_narrative_detection_and_public_form_fallback():
    """没有"现查明"的仍是字段式公示；两者不能判错。"""
    assert is_narrative(NARRATIVE_TEXT) is True
    assert is_narrative(DOC_TEXT) is False
    assert parse_any_doc(DOC_TEXT, filename=DOC_NAME)["form"] == "字段式公示"


def test_pkulaw_id_from_text_when_filename_renamed():
    """文件被改名时，靠正文里的【法宝引证码】兜底。"""
    p = parse_any_doc(NARRATIVE_TEXT, filename="无名文件.doc")
    assert p["pkulaw_id"] == "CLI.ALE.50000001"


# 复刻「司法案例库」判决书记录（29 字段、法宝已分段；人名等全部虚构）
JUDGMENT = {
    "Title": "某甲与某县公安局公安行政处罚一审行政判决书",
    "Category": ["行政", "行政主体", "其他（公安）"],
    "CaseGrade": ["普通案例"],
    "Court": "湖南省某县人民法院",
    "LastInstanceDate": "2025.05.02",
    "CaseFlag": "(2024)湘1021行初253号",
    "CaseClassName": "行政一审",
    "DocumentAttr": ["判决书"],
    "CriminalPunish": ["行政", "行政处罚", "行政拘留", "罚款"],
    "TrialAfter": "原告某甲与被告某县公安局公安行政处罚一案，于2024年12月18日向本院提起行政诉讼。",
    "PlaintiffClaims": "原告某甲诉称，被告对其作出行政拘留十二日，并处罚款一千九百元的处罚决定。",
    "DefenseViewpoint": "被告某县公安局辩称，原告参与赌博的事实存在。",
    "Ascertain": "经审理查明，2024年10月30日9时许，某县公安局在某镇一无名牌馆查获涉嫌赌博人员21人，"
                 "现场查获赌资2664元。同日，被告以原告参与赌博为由，根据《中华人民共和国治安管理处罚法》"
                 "第七十条规定，作出了某公（城）决字〔2024〕第2166号公安行政处罚决定，对原告行政拘留12日，"
                 "并处罚款1900元；收缴赌资2664元。",
    "Identified": "本院认为，被告认定原告参与赌博的事实清楚，情节严重，处罚幅度适当。依照《中华人民共和国"
                  "行政诉讼法》第六十九条之规定，判决如下：",
    "RefereeBasis": "《中华人民共和国治安管理处罚法》第九十三条\n《中华人民共和国治安管理处罚法》第七十条\n"
                    "《中华人民共和国行政诉讼法》第六十九条",
    "RefereeResult": "驳回原告某甲的诉讼请求。",
    "Url": "[北大法宝](https://www.pkulaw.com/pfnl/a25051f3312b07f3b9f06d79842693eaa76b741a206847a2bdfb.html?way=mcp)",
}


def test_penalty_articles_excludes_court_procedural_rules():
    """处罚依据不能混进法院的程序条文（第九十三条/行政诉讼法第六十九条）。"""
    facts = JUDGMENT["Ascertain"]
    arts = penalty_articles(facts, JUDGMENT["RefereeBasis"])
    assert arts == ["治安管理处罚法第七十条"]
    # 事实段没有"根据…作出…决定"时，退回裁判依据里只保留处罚性条款
    arts2 = penalty_articles("（事实段没有引用条文）", JUDGMENT["RefereeBasis"])
    assert arts2 == ["治安管理处罚法第七十条"]


def test_judgment_record_mapping():
    rec = build_judgment_record(JUDGMENT, harvest_date="2026-10-16")
    assert rec["source_type"] == "行政判决书"
    assert rec["pkulaw_id"] == "a25051f3312b07f3b9f06d79842693eaa76b741a206847a2"   # 原文链接里的 pfnl 哈希
    assert rec["doc_no"] == "(2024)湘1021行初253号"
    assert rec["court"] == "湖南省某县人民法院"
    assert rec["region"] == "湖南省"
    assert rec["authority"] == "某县公安局"
    assert rec["behavior_date"] == "2024-10-30"
    assert rec["decision_date"] == "2024-10-30"        # 原处罚决定日（从事实段复述里取）
    assert rec["segmented"] is True                     # 法宝已分段，不再自切
    assert rec["text_facts"] == JUDGMENT["Ascertain"]   # 经审理查明 → text_facts
    assert rec["text_review"] == JUDGMENT["Identified"]  # 本院认为 → text_review（法院审查意见）
    assert rec["deidentified"] is False                 # 判决书是真名
    oc = rec["outcome"]                                 # 原行政处罚（不是判决结果）
    assert oc["type"] == "拘留并处罚款" and oc["detention_days"] == 12 and oc["fine"] == 1900
    assert oc["articles"] == ["治安管理处罚法第七十条"] and oc["law_version"] == "旧法"
    assert oc["stated_circumstances"] == ["情节严重"]
    assert rec["review"]["result"] == "维持"            # 驳回诉讼请求 = 原处罚被维持
    assert rec["review"]["judgment_date"] == "2025-05-02"
    assert rec["quality"]["has_amount"] and rec["quality"]["has_outcome"]
    assert rec["quality"]["outcome_only"] is False
    assert rec["quality"]["parse_warnings"] == []


def test_judgment_review_results_and_changed_outcome():
    """撤销 / 变更 / 确认违法；变更类要给出变更后的处罚。"""
    def variant(**over):
        r = dict(JUDGMENT, **over)
        return build_judgment_record(r)

    assert variant(RefereeResult="撤销被告某县公安局作出的行政处罚决定。")["review"]["result"] == "撤销"
    assert variant(RefereeResult="确认被告作出的行政处罚违法。")["review"]["result"] == "确认违法"
    v = variant(RefereeResult="变更被告某县公安局作出的行政拘留十二日为罚款五百元。")
    assert v["review"]["result"] == "变更" and "罚款500元" in v["review"]["changed_outcome"]


def test_judgment_no_facts_flags():
    """MCP 对部分记录只返回节选：事实段为空时必须告警，不能当作可用金标。"""
    rec = build_judgment_record(dict(JUDGMENT, Ascertain="", Identified="", RefereeResult=""),
                                harvest_date="2026-10-16")
    assert rec["quality"]["parse_warnings"] and "facts_missing" in rec["quality"]["parse_warnings"]
    assert rec["outcome"]["type"] == ""
    # 判决结论缺失时按"无"处理，不臆断为维持
    assert rec["review"]["result"] == "无"


# 复刻「正文塞在表格"处罚结果"栏」形态（实测 d2 嵊泗 / d6 咸丰）：
# 换行把词拆进不同单元格、续行标签列为空，且长文里含前科等干扰信息
TABLE_WRAPPED_TEXT = """   柴某某为赌博提供条件案(某公(某)行罚决字[2025]00311号)
    主题分类： 公安
    处罚种类： 罚款、没收违法所得、没收非法财物 行政拘留
    行政相对人： 柴某某
    执法机关：某某县公安局某派出所
    执法地域： 某县
    公布日期：2025.12.30
    发文案号：某公(某)行罚决字[2025]00311号
    罚没情况：对柴某某为赌博提供条件罚款五百元
    执法依据： 中华人民共和国治安管理处罚法(2012修正)第70条
   |行政处罚决定书文号                      |某公(某)行罚决字[2025]00311号           |
|被处罚对象                              |柴某某                                  |
|处罚结果                                |主要违法事实： 2025年12月17日20时许，在 |
|                                        |本县某镇某弄*号，违法行为人柴某实施为赌 |
|                                        |博提供条件的违法行为。                  |
|                                        |违法经历：2019年3月，因赌博被处以行政拘 |
|                                        |留五日的行政处罚。                      |
|                                        |行政处罚的种类和依据：根据《中华人民共和 |
|                                        |国治安管理处罚法》第七十条之规定，决定给 |
|                                        |予违法行为人柴某行政拘留十二日并处罚款五 |
|                                        |百元的行政处罚，并收缴赌具"牌九"牌一副。 |
|                                        |由于柴某已满七十周岁，根据《中华人民共和国|
|                                        |治安管理处罚法》第二十一条第（三）项的规定 |
|                                        |，对其不送拘留所执行。                  |
|处罚决定日期                            |2025-12-30                              |
|处罚机关                                |某某县公安局某派出所                    |
"""


def test_table_wrapped_narrative_form():
    """正文在"处罚结果"栏：要抽出事实段，且拘留天数不能被前科的"五日"带偏。"""
    p = parse_any_doc(TABLE_WRAPPED_TEXT, filename="柴某某赌博案(FBM-CLI.ALE.60000001).doc")
    assert p["form"] == "叙述式-结果栏内"
    assert "为赌博提供条件" in p["facts"]
    assert p["pkulaw_id"] == "CLI.ALE.60000001"

    rec = build_record(p, harvest_date="2026-10-16")
    assert rec["source_type"] == "处罚决定书"           # 有事实 → A 类
    oc = rec["outcome"]
    assert oc["detention_days"] == 12                   # 不是前科的 5 日
    assert oc["fine"] == 500
    assert oc["detention_not_executed"] == "是"         # 已满七十周岁、不送拘留所执行
    assert rec["quality"]["outcome_only"] is False
    assert rec["gambling_hint"] if "gambling_hint" in rec else rec["quality"]["form"].startswith("叙述式")


def test_bare_article_numbers_and_new_law():
    """裸条号（实测 d4："第十一条、第八十二条"）+ 新法版本判定。"""
    p = parse_any_doc(DOC_TEXT.replace("《中华人民共和国治安管理处罚法》第七十条", "第十一条、第八十二条")
                                 .replace("中华人民共和国治安管理处罚法(2012修正)第70条", ""),
                      filename="某赌博案(FBM-CLI.ALE.70000001).doc")
    rec = build_record(p, harvest_date="2026-10-16")
    assert "治安管理处罚法第八十二条" in rec["outcome"]["articles"]
    assert rec["outcome"]["law_version"] == "新法"


def test_gambling_hint_from_title_only():
    """事实段为空时，靠标题判赌博（实测 d5：上海记录只有字段表）。"""
    p = parse_any_doc(DOC_TEXT, filename=DOC_NAME)
    assert p["gambling_hint"] is True                   # 标题"陈*英赌博案"
    assert build_record(p)["quality"]["outcome_only"] is True


# 复刻「司法案例批量导出」的判决书 .doc（结构化头 + 小节标题；人名等全部虚构）
JUDGMENT_DOC = """   某甲赌博一案
    案由： 刑事> 妨害社会管理秩序罪> 扰乱公共秩序罪> 赌博罪
    案 号：(2026)湘1224刑初264号
    审理法官： 某某某
    文书类型： 判决书
    公开类型： 文书公开
    审理法院： 湖南省某县人民法院
    审结日期：2026.09.30
    案件类型： 刑事一审
    审理程序： 简易程序
    权责关键词： 主犯 自首 缓刑 罚金 追缴
    刑罚：被告人某甲犯赌博罪，判处被告人某甲拘役三个月，缓刑三个月，并处罚金人民币四千元；
   //
                                 某甲赌博案
                            湖南省某县人民法院
                                 刑事判决书
                                                       (2026)湘1224刑初264号
   公诉机关某县人民检察院。
   当事人
   被告人某甲。因涉嫌犯赌博罪，于2025年8月15日被某县公安局取保候审。
   审理经过
   某县人民检察院于2026年9月20日以某检刑诉[2026]237号起诉书指控被告人某甲犯赌博罪，向本院提起公诉。
   检察院指控
   2025年6月份，某甲受雇监管赌博场子，每天保底给付2-3百元工资。累计收取赌博人员兑换的赌资21万余元，非法获利6千余元。
   本院认为
   被告人某甲以营利为目的伙同他人聚众赌博，从中抽头渔利，其行为构成赌博罪；系自首，可以从轻处罚。
   裁判结果
   被告人某甲犯赌博罪，判处拘役三个月，缓刑三个月，并处罚金人民币四千元；追缴违法所得六千元。
   落款
   审 判 员 某某某
   二〇二六年九月三十日
"""


def test_judgment_doc_form_and_fields():
    """判决书导出件：结构化头（案号/案由/法院/审结日期/刑罚）+ 小节切分（指控→事实、本院认为、裁判结果）。"""
    p = parse_any_doc(JUDGMENT_DOC, filename="某甲赌博一案(FBMCLI.C.580711741).doc")
    assert p["form"] == "判决书"
    assert p["pkulaw_id"] == "CLI.C.580711741"           # 司法案例的引证码写法（无短横线）
    assert p["doc_no"] == "(2026)湘1224刑初264号"
    assert p["authority"] == "湖南省某县人民法院"
    assert "赌资21万余元" in p["facts"]                    # 简易程序只有"检察院指控"，取作事实段
    assert "构成赌博罪" in p["reasoning"]
    assert "拘役三个月" in p["decision"]

    rec = build_record(p, harvest_date="2026-10-16")
    assert rec["source_type"] == "刑事判决书"
    assert rec["region"] == "湖南省"
    assert rec["decision_date"] == "2026-09-30"
    assert rec["outcome"]["type"] == "刑事判决"
    assert rec["criminal"] == {"main": "拘役", "months": 3, "suspended": True, "fine": 4000}
    assert rec["quality"]["in_scope"] is True
    assert rec["quality"]["form"] == "判决书"
    assert rec["quality"]["has_amount"] is True


def test_civil_judgment_marked_out_of_scope():
    """民事判决（全文检索噪声）标 in_scope=False，交付时会被跳过。"""
    civil = JUDGMENT_DOC.replace("刑事> 妨害社会管理秩序罪> 扰乱公共秩序罪> 赌博罪", "民事>合同纠纷")
    civil = civil.replace("案件类型： 刑事一审", "案件类型： 民事一审").replace("刑事判决书", "民事判决书")
    rec = build_record(parse_any_doc(civil, filename="某民事案(FBMCLI.C.1).doc"))
    assert rec["source_type"] == "民事判决书"
    assert rec["quality"]["in_scope"] is False


def test_worklist_from_mcp_response(tmp_path):
    """MCP 检索结果 → 工作清单：同文号两个标题变体去重，标「叙述式=是」。"""
    import json as _json
    resp = {"structured": {"total": 2, "data": [
        {"title": "某甲赌博案(某公(某)行罚决字[2025]001号)", "documentNo": "某公(某)行罚决字[2025]001号",
         "punishOrgan": "某某县公安局", "punishmentDate": "2025.01.02",
         "punishmentType": ["行政拘留"], "accordingLaw": ["中华人民共和国治安管理处罚法(2012修正)第70条"],
         "url": "https://www.pkulaw.com/apy/xbdfb.html?way=mcp"},
        {"title": "某某县公安局行政处罚决定书某公(某)行罚决字[2025]001号", "documentNo": "某公(某)行罚决字[2025]001号",
         "punishOrgan": "某某县公安局", "punishmentDate": "2025.01.02"},
    ]}}
    src = tmp_path / "r.json"
    src.write_text(_json.dumps(resp, ensure_ascii=False), encoding="utf-8")
    from pkulaw_ingest import cmd_worklist
    class A:  # 模拟 argparse 命名空间
        pass
    a = A(); a.src, a.out = str(src), str(tmp_path / "out")
    cmd_worklist(a)
    import csv as _csv
    rows = list(_csv.DictReader(open(tmp_path / "out" / "worklist.csv", encoding="utf-8")))
    assert len(rows) == 1                                   # 同文号去重
    assert rows[0]["发文案号"] == "某公(某)行罚决字[2025]001号"
    assert rows[0]["叙述式"] == "是" and "?way=mcp" not in rows[0]["原文链接"]
