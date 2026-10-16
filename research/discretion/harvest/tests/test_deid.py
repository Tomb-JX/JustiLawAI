"""脱敏、R6、正本裁剪与拆页、区划、去重单测：合成样例复刻 2026-10-16 实测遇到的写法（姓名、号码均为虚构），不联网。

运行（仓库根目录）：python -m pytest research/discretion/harvest/tests -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import dates_close, dedupe_and_link, inclusion, jaccard_pairs, law_version_of, shingles, tag_articles  # noqa: E402
from deid import deidentify, doc_hash, doc_no_hash, find_subject  # noqa: E402
from parse import canonical, column_case, split_documents, split_items  # noqa: E402
from r6_scan import scan_text  # noqa: E402
from regions import Resolver  # noqa: E402

BEHAVIOR = date(2024, 4, 18)

DECISION = """某县公安局
行政处罚决定书
某公（固）行罚决字〔2024〕0123号
违法行为人赵xx，男，1980年05月06日出生，汉族，初中文化，居民身份证号码为130000198005060000，户籍所在地为河北省某市某县固城镇北庄村，现住某县城关镇幸福小区3号楼2单元501室，无违法犯罪经历。
现查明：2024年04月18日22时许，赵xx在定兴县固城镇北庄村朱xx家中伙同王xx、韦*林等人以推牌九的方式赌博，赵xx从中抽头渔利300元，现场查获赌资3078元。
以上事实有违法行为人赵xx的陈述和申辩、证人证言等证据证实。
根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对赵xx行政拘留十三日，并处罚款壹仟元整。
由定兴县公安局城东派出所民警张志强送定兴县拘留所执行。联系电话13912345678，罚款缴至账号6222020200000000000。
定兴县公安局
二〇二四年四月十九日"""


def test_subject_and_other_persons():
    d = deidentify(DECISION, behavior=BEHAVIOR)
    assert d.subject == "赵xx"
    t = d.text
    assert "违法行为人甲" in t and "对甲行政拘留十三日" in t
    assert "赵" not in t and "朱xx" not in t and "王xx" not in t and "韦*林" not in t
    # 其他人按首次出现编号，每人一个代号（人数数得出来）
    assert "某村乙家中伙同丙、丁等人" in t


def test_identifiers_removed_and_age_kept():
    t = deidentify(DECISION, behavior=BEHAVIOR).text
    for leak in ("1980", "130000198005060000", "汉族", "初中文化", "幸福小区", "501", "13912345678", "6222020200000000000",
                 "张志强", "城东派出所", "北庄村", "固城镇"):
        assert leak not in t, leak
    assert "男，行为时43周岁" in t                   # D1：按行为日算周岁
    assert "，，" not in t and "，。" not in t


def test_kept_information():
    t = deidentify(DECISION, behavior=BEHAVIOR).text
    for keep in ("定兴县", "某村", "家中", "推牌九", "抽头渔利300元", "赌资3078元", "第七十条", "行政拘留十三日",
                 "罚款壹仟元整", "定兴县公安局", "某派出所民警"):
        assert keep in t, keep


def test_dates_and_docno():
    d = deidentify(DECISION, behavior=BEHAVIOR)
    t = d.text
    assert "2024年4月" in t and "22时" not in t and "二〇二四年四月" in t and "十九日" not in t
    assert f"〔文号 h:{doc_hash('某公（固）行罚决字〔2024〕0123号')}〕" in t   # D3：文号换哈希
    assert "0123" not in t
    t2 = deidentify("执行期限：2024年7月7日至7月20日。同年5月9日，被申请人作出决定。", behavior=None).text
    assert t2 == "执行期限：2024年7月至7月。同年5月，被申请人作出决定。"


def test_masked_birth_and_masked_fields_deleted():
    t = deidentify("违法行为人张xxx,男,居民身份证号码:xxxxxxxxxxxxxxxxxx,xxxx年xx月xx日出生，xx族，xx文化，户籍所在地：x省x市xxxxxx村。"
                   "现查明：违法嫌疑人张xx通过名下银行卡（卡x：620xxxxxxxxxxxx9455）参与网络赌博。", behavior=None).text
    assert "xxxx年" not in t and "9455" not in t and "xx族" not in t
    assert "违法嫌疑人甲" in t                       # 同一人遮挡位数不同（张xxx / 张xx）仍为本人


def test_place_masks_are_not_persons():
    d = deidentify("违法行为人马*、袁**在五河县城关镇**小区丁**家中，与叶**等人在塔城市***乡**村**路*巷赌博。", behavior=None)
    assert d.persons.get("丁**") and "区丁**" not in d.persons
    assert "某小区" in d.text and "某村" in d.text and "**路" not in d.text


def test_floor_and_shop_masks():
    d = deidentify("被处罚人赵xx，男。现查明：在辛集市东华路xx饭店三楼xxx棋牌娱乐赵xx、曹xx利用麻将进行赌博，麻将由戴x提供。"
                   "以上事实有戴x询问笔录证实。", behavior=None)
    assert "楼xxx" not in d.persons and "乐赵xx" not in d.persons
    assert "某棋牌娱乐甲、乙利用麻将" in d.text and "由丙提供" in d.text and "丙询问笔录" in d.text


def test_masked_given_name_forms():
    d = deidentify("违法行为人李**和同案人谭明*、莫向*、张纪x在某村赌博。查明覃**于当日到案。", behavior=None)
    for tok in ("谭明*", "莫向*", "张纪x", "覃**"):
        assert tok in d.persons, tok
    assert "明覃**" not in d.persons


def test_real_names_in_lists_and_contexts():
    t = deidentify("违法行为人缪文远，因实施赌博的违法行为，于2026年6月16日被处罚。经查，缪文远伙同李大成、谢镇文等人赌博，"
                   "由房友明提供场所。", behavior=None).text
    for name in ("缪文远", "李大成", "谢镇文", "房友明"):
        assert name not in t, name
    assert t.startswith("违法行为人甲，")


def test_case_name_and_column_subject():
    text = "含公（环）行罚决字〔2023〕233号\n朱某平等人赌博案\n王某山\n2023年5月8日9时许，王某山和蔡某明在公园内赌博。"
    assert find_subject(text) == "王某山"
    t = deidentify(text, behavior=None).text
    assert "朱某平" not in t and "王某山" not in t and "蔡某明" not in t


def test_ambiguous_same_masks():
    d = deidentify("违法行为人韦**伙同覃**、蒙**、韦*林、蒙**等人赌博。", behavior=None)
    assert d.ambiguous_persons


def test_projection_keeps_segments_as_slices():
    facts = "2024年04月18日22时许，赵xx在定兴县固城镇北庄村朱xx家中伙同王xx、韦*林等人以推牌九的方式赌博"
    d = deidentify(DECISION, behavior=BEHAVIOR)
    s = DECISION.find(facts)
    a, b = d.project(s, is_end=False), d.project(s + len(facts), is_end=True)
    assert d.text[a:b] == "2024年4月，甲在定兴县某镇某村乙家中伙同丙、丁等人以推牌九的方式赌博"
    # 单独脱敏的段落沿用代号表
    seg = deidentify("对赵xx、王xx分别处罚", behavior=None, persons=d.persons).text
    assert seg == "对甲、丙分别处罚"


def test_r6_hits_and_clean_output():
    hard = {h.cat for h in scan_text("身份证130000198005060000，电话13912345678，住3号楼501室，李xx于2024年4月18日22时许") if h.hard}
    assert {"id", "phone", "house", "person_masked", "date_day", "time"} <= hard
    clean = deidentify(DECISION, behavior=BEHAVIOR).text
    assert not [h for h in scan_text(clean) if h.hard]
    assert not [h for h in scan_text("于宝安区某麻将馆，被申请人某派出所调查，县某村") if h.hard]


def test_canonical_strips_navigation():
    page = ("某县政府网\n首页\n政务公开\n当前位置：首页 >> 执法公示\n某县公安局\n行政处罚决定书\n某公行罚决字〔2024〕1号\n"
            "违法行为人李xx，男。\n现查明：李xx赌博。\n根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对李xx罚款五百元。\n"
            "某县公安局\n二〇二四年四月十九日\n打印本页\n关闭窗口\n版权所有：某县人民政府")
    c = canonical(page)
    assert c.startswith("某县公安局\n行政处罚决定书") and c.endswith("二〇二四年四月十九日")
    # 页头里有正文标记时不裁（起点判错的保护）
    assert canonical("现查明：张某赌博，处罚款。\n当事人张三，男，\n其他") .startswith("现查明")


def test_split_documents_and_lines():
    one = "某县公安局\n公安行政处罚决定书\n环公(治)行罚决[2022]{n}号\n违法行为人{p}，男，\n现查明{p}赌博。\n根据……决定对{p}罚款五百元。"
    page = "导航\n" + one.format(n=13, p="玉**") + "\n" + one.format(n=24, p="韦*")
    docs = split_documents(page)
    assert len(docs) == 2 and docs[1].startswith("某县公安局") and "24号" in docs[1]
    rows = ("违法行为人王一凡，因实施赌博的违法行为，于2025年4月14日，被某分局给予罚款四百元的处罚。\n"
            "违法行为人杨文华，因实施赌博的违法行为，于2025年4月15日，被某分局给予行政拘留七日的处罚。\n"
            "被处罚人如不服本决定，可以申请行政复议。")
    assert len(split_items(rows)) == 2


def test_column_case():
    chunk = ("含公（环）行罚决字〔2023〕234号\n朱某平等人赌博案\n吴某和\n/\n/\n"
             "2023年5月8日9时许，吴某和在小树林内为他人提供牌九进行赌博，抽头获利十元\n"
             "根据《中华人民共和国治安管理处罚法》第七十条之规定，决定给予吴某和行政罚款二百元的处罚\n2023.5.8")
    facts, decision = column_case(chunk)
    assert facts.startswith("2023年5月8日") and decision.startswith("根据《")


def test_region_resolver():
    rows = [
        {"code": "130000", "name": "河北省", "level": "省", "province_code": "130000", "city_code": ""},
        {"code": "130600", "name": "保定市", "level": "市", "province_code": "130000", "city_code": "130600"},
        {"code": "130626", "name": "定兴县", "level": "县", "province_code": "130000", "city_code": "130600"},
        {"code": "530000", "name": "云南省", "level": "省", "province_code": "530000", "city_code": ""},
        {"code": "530400", "name": "玉溪市", "level": "市", "province_code": "530000", "city_code": "530400"},
        {"code": "530427", "name": "新平彝族傣族自治县", "level": "县", "province_code": "530000", "city_code": "530400"},
        {"code": "330700", "name": "金华市", "level": "市", "province_code": "330000", "city_code": "330700"},
        {"code": "330000", "name": "浙江省", "level": "省", "province_code": "330000", "city_code": ""},
        {"code": "330723", "name": "武义县", "level": "县", "province_code": "330000", "city_code": "330700"},
        {"code": "210000", "name": "辽宁省", "level": "省", "province_code": "210000", "city_code": ""},
        {"code": "210700", "name": "锦州市", "level": "市", "province_code": "210000", "city_code": "210700"},
        {"code": "210727", "name": "义县", "level": "县", "province_code": "210000", "city_code": "210700"},
    ]
    r = Resolver(rows)
    assert r.resolve([("定兴县公安局", 3)])["region_code"] == "130626"
    assert r.resolve([("新平县公安局", 3)])["region_code"] == "530427"      # 自治县简称
    assert r.resolve([("武义县公安局", 3)])["region_code"] == "330723"      # 不被"义县"截胡
    assert r.resolve([("玉溪市公安局", 3)])["level"] == "市"


def _rec(i, facts, *, h="", site="a.gov.cn", day="2024-01-01", cited=()):
    return {"id": f"W-{i:06d}", "doc_no_hash": h, "source_type": "处罚决定书", "segmented": True, "text_facts": facts,
            "text_decision": "", "text_full": facts, "quality": {"ocr": False}, "behavior_date": day, "_site": site,
            "_cited": list(cited), "linked_ids": [], "event_id": ""}


def test_dedupe_events_and_links():
    base = "甲伙同乙、丙在某村以打麻将的方式赌博，现场查获赌资三千元，甲持有赌资五百元，被公安机关当场查获。"
    recs = [_rec(1, base, h="aaa111"), _rec(2, base + "另", h="aaa111"),        # 同文号：留一份
            _rec(3, base.replace("甲持有赌资五百元", "乙持有赌资八百元"), h="bbb222"),  # 同站同日、事实相似：同一事件
            _rec(4, "甲在家中通过手机参与网络赌博，累计充值一万元。", h="ccc333", day="2024-05-01"),
            _rec(5, "申请人不服处罚决定申请复议，复议机关维持原处罚。", h="ddd444", day="2024-06-01", cited=["ccc333"])]
    kept, dropped, stats = dedupe_and_link(recs)
    ids = {r["id"] for r in kept}
    assert len(dropped) == 1 and len(ids) == 4
    ev = {r["id"]: r["event_id"] for r in kept}
    survivor = next(i for i in ("W-000001", "W-000002") if i in ids)
    assert ev[survivor] == ev["W-000003"]
    assert ev["W-000004"] == ev["W-000005"] and ev["W-000004"] != ev["W-000003"]
    assert next(r for r in kept if r["id"] == "W-000005")["linked_ids"] == ["W-000004"]


def test_jaccard_and_inclusion():
    a, b = shingles("甲在某村以打麻将的方式赌博被查获", 5), shingles("甲在某村以打麻将的方式赌博被查获了", 5)
    assert jaccard_pairs({"x": a, "y": b}, 0.8)
    rec = {"text_facts": "甲在某村以打麻将的方式赌博，现场查获赌资三千元，甲持有赌资五百元。", "outcome": {"type": "罚款"},
           "province_code": "130000", "subject_alias": "甲", "review": {"result": "无"}}
    assert inclusion(rec) == []
    assert inclusion({**rec, "text_facts": "因赌博"}) == ["②事实不足", "本人未在事实段出现"]
    assert inclusion({**rec, "review": {"result": ""}}) == ["复议结论未解析"]


def test_spec_v02_fields():
    # 文号哈希：去空白、统一括号后 SHA-256 前 16 位；正文占位取前 6 位
    assert doc_no_hash("某公(治)行罚决[2022]13号") == doc_no_hash("某公（治）行罚决字〔2022〕13号".replace("决字", "决"))
    assert doc_no_hash("某公（固）行罚决字 〔2024〕 0123号") == doc_no_hash("某公（固）行罚决字〔2024〕0123号")
    assert len(doc_no_hash("x〔2024〕1号")) == 16 and doc_hash("x〔2024〕1号") == doc_no_hash("x〔2024〕1号")[:6]
    # 年龄：只有出生年月、行为在同月时算不准，取较小值并标 age_uncertain
    d = deidentify("违法行为人李xx，男，1980年4月出生。", behavior=date(2024, 4, 18))
    assert "行为时43周岁" in d.text and d.age_uncertain
    d = deidentify("违法行为人李xx，男，1980年5月6日出生。", behavior=date(2024, 4, 18))
    assert "行为时43周岁" in d.text and not d.age_uncertain
    # 法条统一写法、法律版本按行为日、复议"驳回"记"程序驳回"
    assert tag_articles(["治安管理处罚法第七十条", "第十一条第一款"], "旧法") == ["治安管理处罚法（2012修正）第七十条", "第十一条第一款"]
    # 法律版本以**实际引用的法条**为准（D8 / 2026-10-16 修 I-01）；未引用时退回行为日。
    # 引用与行为日冲突（如 2026 后仍引旧法）不再被构建覆盖，交由交付契约校验暴露。
    assert law_version_of("2024-01-05", "新法") == "新法"       # 从旧兼从轻
    assert law_version_of("2024-01-05", "旧法") == "旧法"
    assert law_version_of("", "旧法") == "旧法"
    assert law_version_of("2026-02-03", "") == "新法"
    assert law_version_of("2026-02-03", "旧法") == "旧法"
    assert dates_close("2024-01-01", "2024-01-20") and not dates_close("2024-01-01", "2024-05-01")
