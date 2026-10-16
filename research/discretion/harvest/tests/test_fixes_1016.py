"""2026-10-16 验收退回与问题清单（全景笔记 §8.1 I-03–I-07、I-12、I-13）的回归测试。合成样例，姓名为虚构。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT / "justilaw-api"))

from build import inclusion  # noqa: E402
from parse import behavior_and_punish, column_case, parse_date, parse_page, split_documents  # noqa: E402
from to_parsed1 import facts_sufficient, to_record  # noqa: E402

PAGE = {"page_id": "p1", "manifest_id": "W-000001", "url": "https://example.gov.cn/a.html", "fetched_at": "2026-10-16T10:00",
        "site": "example.gov.cn", "title": "某县公安局行政处罚决定书", "publisher": "某县人民政府"}


def test_dates_valid_and_concatenated_signature():
    assert parse_date("2023.3.92023.3.9") == "2023-03-09"          # I-05：落款粘连
    assert parse_date("2023年13月40日") == ""                       # 不合法的日期返回空
    assert parse_date("2023年12月20日") == "2023-12-20" and parse_date("2022/12/28") == "2022-12-28"


def test_behavior_end_date_and_punish_date():
    # 持续行为取结束日
    assert behavior_and_punish("违法行为人甲，于2025年10月末至2026年1月期间实施了赌博的违法行为，")[0] == "2026-01"
    # 红塔汇总"于××因赌博，被……处罚"：这个日期是处罚日期
    full = "违法行为人李某，于2026年2月1日因赌博，被某分局根据修订前的《治安管理处罚法》第七十条之规定给予罚款。"
    assert behavior_and_punish(full[: full.find("被")], full) == ("", "2026-02-01")
    # "，被申请人……"不是被动句
    assert behavior_and_punish("2023年6月15日，被申请人民警发现申请人涉嫌赌博")[0] == "2023-06-15"


def test_column_rows_without_an_suffix_are_split():
    row = "含公（林）行罚决字〔2023〕{n}号\n{case}\n{who}\n2023年02月01日20时许，{who}在某村用牌九赌博，现场查获赌资五百元\n" \
          "《中华人民共和国治安管理处罚法》第七十条之规定，决定给予行政拘留二日\n2023.2.2"
    text = row.format(n=65, case="孙某某、郭某某等人赌博案", who="黄某某") + "\n" + \
        row.format(n=66, case="李某某非法储存危险物质", who="李某某")
    docs = split_documents(text)
    assert len(docs) == 2 and docs[1].startswith("含公（林）行罚决字〔2023〕66号")
    facts, decision = column_case(docs[1])
    assert facts.startswith("2023年02月01日") and decision.startswith("《中华人民共和国")


def test_field_table_without_facts_has_empty_facts():
    # I-12：只有"案件名称"没有"违法事实"的字段表，事实段留空（不拿案件名充当事实），仍判为赌博案
    text = ("行政相对人名称\n王*\n执法主体名称\n某旗公安局某派出所\n案件名称\n孙某等人赌博案\n罚款金额\n200\n"
            "处罚决定日期\n2024-02-01 00:00:00\n违反的法律法规\n中华人民共和国治安管理处罚法\n处罚依据\n中华人民共和国治安管理处罚法")
    (c,) = parse_page(dict(PAGE), text)
    assert c["text_facts"] == "" and c["gambling"] == "是"


def test_conclusion_words_flagged():
    text = ("申请人：甲\n被申请人：某县公安局\n经审理查明：申请人参与赌博，被申请人认为其主动投案，对其减轻处罚。\n"
            "本机关认为，被申请人认定事实清楚。决定如下：维持被申请人作出的处罚决定。")
    (c,) = parse_page({**PAGE, "title": "行政复议决定书"}, text)
    assert "facts_contains_conclusion" in c["parse_warnings"] and c["review"]["result"] == "维持"


def test_review_result_program_rejection():
    text = ("申请人：甲\n被申请人：某县公安局\n申请人不服被申请人作出的行政处罚决定，申请行政复议。\n"
            "经审查，申请人的复议申请超过法定期限。决定如下：驳回申请人的行政复议申请。")
    (c,) = parse_page({**PAGE, "title": "行政复议决定书"}, text)
    assert c["review"]["result"] == "程序驳回"


def test_inclusion_rejects_boilerplate_summary_items():
    base = {"outcome": {"type": "罚款"}, "province_code": "530000", "subject_alias": "甲", "review": {"result": "无"}}
    summary = {**base, "text_facts": "违法行为人甲，于2025年10月至2026年1月期间实施了赌博的违法行为，"}
    assert "②事实不足" in inclusion(summary)                         # I-03
    real = {**base, "text_facts": "2023年1月，甲在某村家中以打麻将的方式赌博，现场查获赌资三千元，甲持有赌资五百元。"}
    assert inclusion(real) == []
    assert facts_sufficient(real["text_facts"]) and not facts_sufficient(summary["text_facts"])


def test_parsed1_record_passes_engine_contract():
    text = ("某县公安局\n行政处罚决定书\n某公（固）行罚决字〔2024〕0123号\n违法行为人赵xx，男，无违法犯罪经历。\n"
            "现查明：2024年04月18日22时许，赵xx在某村家中以推牌九的方式赌博，现场查获赌资3078元。\n"
            "以上事实有询问笔录等证据证实。\n根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对赵xx罚款伍佰元整。\n"
            "被处罚人如不服本决定，可以申请行政复议。\n某县公安局\n二〇二四年四月十九日")
    (c,) = parse_page(dict(PAGE), text)
    rec = to_record(c, {"example.gov.cn": {"region_code": "130626", "province": "河北省", "province_code": "130000",
                                           "level": "县"}}, "20261016-web")
    assert rec["quality"]["tier"].startswith("L1") and rec["subject_mention"] == "赵xx" and rec["region"] == "130626"
    assert "site" not in rec and rec["extra"]["site"] == "example.gov.cn"
    try:
        from app.discretion.records import check_parsed
    except Exception:  # 引擎依赖不可用时只做结构检查
        return
    errors = [i for i in check_parsed(json.loads(json.dumps(rec, ensure_ascii=False))) if i.level == "error"]
    assert not errors, errors
