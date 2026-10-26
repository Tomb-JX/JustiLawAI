"""2026-10-16 r2 网页内容抽检（docs/04-plan/r2-web-content-audit.md）的回归测试：强语境真名漏网、遮挡写法残字、
"相对人名称"本人，以及 parse.py 的证据段边界、繁体大写、拘留不执行、合并执行罚款、复议结果句、"二0二四"落款。
合成样例，姓名为虚构。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import deidentify  # noqa: E402
from parse import build_case, last_date, outcome_from, reviewed_outcome, segment_decision  # noqa: E402
from r6_scan import scan_text  # noqa: E402


# ---------- 脱敏 ----------

def test_strong_context_real_names():
    t = deidentify("违法行为人覃**，男。现查明将覃**、陶明*等9人抓获，缴获赌资二千元（其中陶明远持有赌资一千元、"
                   "柯连秀持有赌资一千元）。在甘友福位于某镇的家中，范支兰提供的赌具，龚小川坐庄。").text
    for name in ("陶明远", "柯连秀", "甘友福", "范支兰", "龚小川"):
        assert name not in t
    assert "其中丙持有" in t or "其中乙持有" in t


def test_result_table_names_with_func_chars():
    # 名字用字是"其""均""月""机"：GIVEN_REAL 不收，结果表语境里也要认
    t = deidentify("违法嫌疑人何某某罚款四百元；邹其廷罚款四百元；莫皓月行政拘留十二日；杜万机行政拘留十二日；齐均行政拘留五日。").text
    for name in ("其廷", "皓月", "万机", "齐均"):
        assert name not in t


def test_list_and_suffix_cue_names():
    t = deidentify("违法行为人甲某某。高正谊、管佩莲、刘巧娣等人提供麻将，耿先洲等人的陈诉和申辩；"
                   "刘小岳、邓万程等人在某市赌博。\n闻启元提供虚假证言").text
    for name in ("高正谊", "管佩莲", "刘巧娣", "耿先洲", "刘小岳", "邓万程", "闻启元"):
        assert name not in t


def test_cue_stop_words_untouched():
    t = deidentify("违法行为人王某，男。王某利用手机赌博，向其提供场所，房东提供房屋，现场查获赌资，符合赌资较大情形，"
                   "全场赌资四万元，并处罚款五百元；单处罚款二百元。").text
    for w in ("向其提供", "房东提供", "符合赌资", "全场赌资", "单处罚款"):
        assert w in t


def test_masked_given_char_residue():
    t = deidentify("违法行为人翟某军，男。翟某军与张某舵、张某前、张某学三人赌博，另有徐某枝四人。").text
    assert "学" not in t and "枝" not in t
    t = deidentify("被处罚人刘xx,男。以上事实有刘xx询问笔录、曹x权询问笔录、吕x弄询问笔录、戴x询问笔录。"
                   "韦**又向蒙*、韦*秋、蒙*利等人收售；韦*利用微信。").text
    assert "权" not in t and "弄" not in t and "利等人" not in t and "x" not in t
    assert "利用微信" in t                                   # "x*利用"仍不是名字


def test_surname_surname_mask_after_qizhong():
    # "其中谭金*持有"：旧版只认出"金*"，留下"谭"成了"谭庚"
    t = deidentify("违法行为人莫**，男。将谭金*、莫向*等6人抓获（其中谭金*持有赌资五十元，莫向*持有赌资两百元）。").text
    assert "谭" not in t and "金" not in t


def test_unlisted_surname_masked_in_list():
    t = deidentify("违法行为人覃**，女。行为人覃**、谭**、崖**、陆**在某地赌博。丁某、也**四人；汲某参与。").text
    assert "崖" not in t and "也*" not in t and "汲" not in t and "*" not in t


def test_relative_person_field_is_subject():
    d = deidentify("相对人名称\n韩**\n主要违法事实\n韩**多次支桌子，供范**、张**、马*等人赌博。")
    assert d.subject == "韩**"
    assert d.text.startswith("相对人名称\n甲")


def test_r6_person_cue_hard_hit():
    hits = [h for h in scan_text("其中陶明远持有赌资一千元；邹其廷罚款四百元。") if h.hard]
    assert {h.cat for h in hits} == {"person_cue"} and len(hits) == 2
    assert not [h for h in scan_text("甲持有赌资一千元；乙罚款四百元，符合赌资较大情形，全场赌资四万元。") if h.hard]


# ---------- 解析 ----------

def test_traditional_numerals_and_missing_kuan():
    oc = outcome_from("现决定对甲行政拘留十五日，并处罚款貳仟元整。")
    assert (oc["type"], oc["detention_days"], oc["fine"]) == ("拘留并处罚款", 15, 2000)
    oc = outcome_from("现决定对甲以赌博行政拘留十一日，并处罚壹仟元。")
    assert oc["fine"] == 1000
    assert outcome_from("对申请人作出了行政拘留13日并处1000元的处罚决定")["fine"] == 1000
    # 法条原文"并处五百元以上三千元以下罚款"不是罚款数
    assert outcome_from("情节严重的，处十日以上十五日以下拘留，并处五百元以上三千元以下罚款")["fine"] == 0


def test_merged_execution_fine():
    d = ("现决定对甲行政拘留十日，并处罚款伍佰元整。根据《中华人民共和国治安管理处罚法》第十六条之规定，"
         "现决定对甲合并执行行政拘留二十日，并处罚款壹仟元整。")
    oc = outcome_from(d)
    assert (oc["detention_days"], oc["fine"]) == (20, 1000)


def test_double_bracket_article():
    oc = outcome_from("根据《《中华人民共和国治安管理处罚法》第七十条之规定，现决定对甲行政拘留十日并处罚款五百元")
    assert oc["articles"] == ["治安管理处罚法第七十条"]


def test_detention_not_executed_after_decision():
    full = ("甲等人涉嫌开设赌场案\n甲\n2022年10月下午，甲在某村提供赌博场地供十人赌博\n"
            "《中华人民共和国治安管理处罚法》第七十条之规定，现决定给予行政拘留十日并处罚款500元的处罚\n"
            "行政拘留不执行,罚款自收到本决定书之日起15日内自行交至财政专户")
    dec = "《中华人民共和国治安管理处罚法》第七十条之规定，现决定给予行政拘留十日并处罚款500元的处罚"
    c = build_case({"id": "W-x", "title": "", "publisher": ""}, facts=full.split("\n")[2], decision=dec, full=full,
                   segmented=True, doc_type="处罚决定")
    assert c["outcome"]["detention_not_executed"] == "是"


def test_evidence_sentence_kept_out_of_facts():
    t = ("违法行为人甲，男。\n现查明2021年6月，甲等人在某镇利用扑克进行赌博。\n等证据证实。 以上事实有甲与同案人乙的陈述和申辩、物证\n"
         "根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对甲处以行政拘留十日，并处罚款伍佰元。\n被处罚人如不服本决定")
    sg = segment_decision(t)
    assert sg["text_facts"] == "2021年6月，甲等人在某镇利用扑克进行赌博。"
    assert sg["text_evidence"].startswith("等证据证实。")
    t2 = ("违法行为人甲，男。\n现查明2025年10月，甲伙同他人在某路旁赌博。\n以上事实由违法嫌疑人甲的陈述和申辩、监控视频等证据证实。\n"
          "根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对甲处以罚款五百元的处罚。")
    assert segment_decision(t2)["text_facts"] == "2025年10月，甲伙同他人在某路旁赌博。"


def test_reviewed_outcome_skips_codefendant_and_prior():
    t = ("行政复议决定书\n申请人：甲某。\n被申请人：某市公安局某分局。\n申请人甲某不服被申请人2023年7月作出的某公（机）行罚决字[2023]00048号"
         "《行政处罚决定书》，于2023年7月向本机关申请行政复议。\n经审理查明：2023年7月，被申请人作出某公（机）行罚决字[2023]00048号"
         "《行政处罚决定书》，认定申请人参与赌博。根据《中华人民共和国治安管理处罚法》第七十条之规定，决定给予申请人行政拘留十日并处罚款五百元的行政处罚。"
         "另查明，对涉案的乙某，被申请人作出某公（机）行罚决字[2023]00049号《行政处罚决定书》，处以行政拘留十日。\n本机关认为：……")
    oc = outcome_from(reviewed_outcome(t))
    assert (oc["detention_days"], oc["fine"]) == (10, 500)
    prior = ("申请人：丁某某\n申请人丁某某不服被申请人于2022年5月作出的某公（跨）行罚决字〔2022〕xxx号《行政处罚决定书》。\n"
             "经审理查明：2021年12月，被申请人作出某公（跨）行罚决字〔2021〕xxxx号《行政处罚决定书》，根据《中华人民共和国治安管理处罚法》第七十条之规定，"
             "决定对丁某某罚款叁佰元。2022年5月，被申请人作出某公（跨）行罚决字〔2022〕xxx号《行政处罚决定书》，"
             "根据《中华人民共和国治安管理处罚法》第七十条、第二十条第四项之规定，决定对丁某某行政拘留四日。\n本机关认为：……")
    oc = outcome_from(reviewed_outcome(prior))
    assert (oc["type"], oc["detention_days"]) == ("拘留", 4)


def test_reviewed_outcome_not_for_other_offence():
    t = ("申请人：戊某\n申请人不服被申请人作出的某公行罚决字〔2024〕12号《行政处罚决定书》。\n"
         "申请人称：其不满某家中经常赌博。\n被申请人对申请人作出行政拘留十二日的行政处罚符合法律规定。\n"
         "根据《中华人民共和国治安管理处罚法》第二十六条之规定，决定给予申请人行政拘留十二日。")
    assert reviewed_outcome(t) == ""


def test_signature_year_with_zero_digit():
    assert last_date("……\n塔城市公安局\n二0二四年十月十六日\n") == "2024-10-16"
