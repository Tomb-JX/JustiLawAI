"""parsed-1 落地单测：映射、枚举排除、段子串规则、契约自检（不联网）。

运行（仓库根目录）：python -m pytest research/discretion/collect/tests/test_parsed1.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pkulaw_ingest as ing  # noqa: E402

REPO = next(p for p in Path(__file__).resolve().parents if (p / "justilaw-api").is_dir())
sys.path.insert(0, str(REPO / "justilaw-api"))
from app.discretion.records import check_parsed  # noqa: E402


def _legacy_record(**over) -> dict:
    """一条合成的 legacy（旧格式）记录：叙述式金标候选。"""
    base = {
        "id": "P-001", "source_type": "处罚决定书", "doc_no": "某公（天）行罚决字〔2024〕0325号",
        "harvest_date": "2026-10-16", "deidentified": False,
        "behavior_date": "2024-04-18", "decision_date": "2024-04-19",
        "authority": "某县公安局", "region": "江苏",
        "pkulaw_id": "CLI.ALE.50000001",
        "source_ref": "文号哈希待生成（D3）｜原文链接见台账",
        "text_full": "某县公安局公安行政处罚决定书\n某公（天）行罚决字〔2024〕0325号\n违法行为人张某某，男。\n"
                     "现查明：2024年4月18日，张某某同王某某等人以打麻将方式赌博，现场查获赌资3078元。\n"
                     "根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定对张某某行政拘留十日。\n",
        "segmented": True,
        "text_facts": "2024年4月18日，张某某同王某某等人以打麻将方式赌博，现场查获赌资3078元。",
        "text_evidence": "", "text_reasoning": "",
        "text_decision": "对张某某行政拘留十日。",
        "text_review": "",
        "outcome": {"type": "拘留", "detention_days": 10, "fine": 0,
                    "detention_not_executed": "否", "confiscation": "",
                    "articles": ["治安管理处罚法第七十条"], "stated_circumstances": [],
                    "law_version": "旧法", "detention_items": [10]},
        "review": {"result": "无", "changed_outcome": {}},
        "quality": {"tier": "L1-金标候选", "form": "叙述式-独立成篇", "has_amount": True,
                    "has_outcome": True, "parse_warnings": [], "tier_reason": "有事实段且结果可解析",
                    "outcome_only": False, "text_source": "antiword", "law_version_raw": "2012修正"},
        "event_key": "某县公安局|2024年4月18日|3078",
        "event_hint": {"authority": "某县公安局", "decision_date": "2024-04-19", "doc_seq": "0325"},
    }
    base.update(over)
    return base


def test_doc_no_hash_matches_deid_rule():
    """规范化文号哈希与发现层 deid.py 同规则（用该规则算出的真实值做锚）。"""
    assert ing.doc_no_hash("沪公长(长新)行罚决字〔2025〕00289号") == "557b6da23f34f023"
    assert ing.doc_no_hash("浦公（乌）行罚决字〔2019〕10号") == "89c856a5921ffcad"
    assert ing.doc_no_norm("苏公[2022]第1号") == "苏公〔2022〕第1号"


def test_to_parsed1_passes_contract_check():
    """映射后的记录必须过契约自检（零 error），且关键字段就位。"""
    rec, why = ing.to_parsed1(_legacy_record(), batch="20261016-测试", source="法宝执法库")
    assert why == "" and rec is not None
    assert rec["record_version"] == "parsed-1"
    assert rec["id"] == "P-001" and rec["batch"] == "20261016-测试"
    assert rec["source"] == "法宝执法库" and rec["parser"] == ing.PARSER_ID
    assert rec["source_ref"] == "法宝引证码 CLI.ALE.50000001"
    assert rec["doc_no_hash"] == ing.doc_no_hash(rec["doc_no"])
    assert rec["province"] == "江苏" and rec["region"] == ""      # region 留给构建补代码
    assert rec["law_version"] == "旧法"
    assert "张某某" in rec["subject_mention"]                     # 供脱敏替换为"甲"
    assert rec["quality"]["completeness"] == {"has_amount": True, "has_outcome": True}
    assert rec["quality"]["gambling"] == "是"
    assert "pkulaw_id" in rec["extra"]["legacy"]                  # 来源字段进 extra
    assert rec["extra"]["quality"]["tier_reason"]
    assert rec["extra"]["outcome"]["detention_items"] == [10]
    issues = [i for i in check_parsed(rec) if i.level == "error"]
    assert issues == [], issues


def test_to_parsed1_excludes_out_of_enum():
    rec, why = ing.to_parsed1(_legacy_record(source_type="刑事判决书"), batch="b", source="法宝案例库")
    assert rec is None and "不在契约枚举" in why
    bad = _legacy_record(outcome={"type": "刑事判决", "detention_days": 0, "fine": 0,
                                  "detention_not_executed": "否", "articles": []})
    rec2, why2 = ing.to_parsed1(bad, batch="b", source="法宝执法库")
    assert rec2 is None and "outcome.type" in why2


def test_to_parsed1_drops_non_substring_segments():
    """字段式公示的"决定段"是拼出来的、不是原文子串 → 不写该段、原文进 extra。"""
    legacy = _legacy_record(segmented=False, text_facts="", text_decision="依据《治安管理处罚法》第七十条；"
                           "罚款三百元（拼接段不是原文子串）", quality={
                               "tier": "L2-结果only", "form": "字段式公示", "has_amount": False,
                               "has_outcome": True, "parse_warnings": ["facts_missing"],
                               "tier_reason": "无事实段"})
    rec, why = ing.to_parsed1(legacy, batch="b", source="法宝执法库")
    assert why == "" and rec["text_decision"] == ""
    assert "text_decision" in rec["extra"]["segments_not_in_full"]
    assert rec["extra"]["segments_raw"]["text_decision"].startswith("依据")
    errors = [i for i in check_parsed(rec) if i.level == "error"]
    assert errors == [], errors


def test_cmd_parsed1_end_to_end(tmp_path, monkeypatch):
    """端到端：legacy 目录 → parsed/pkulaw/<批次>/records.jsonl；stats 含排除明细与自检。"""
    from types import SimpleNamespace

    legacy = tmp_path / "ingest" / "批A"
    legacy.mkdir(parents=True)
    ok = _legacy_record()
    bad = _legacy_record(id="P-002", source_type="民事判决书", doc_no="（2026）民终1号")
    (legacy / "admin_cases.jsonl").write_text(
        json.dumps(ok, ensure_ascii=False) + "\n" + json.dumps(bad, ensure_ascii=False) + "\n",
        encoding="utf-8")

    monkeypatch.setattr(ing, "DATA_DIR", tmp_path / "data")
    import common
    monkeypatch.setattr(common, "REGISTRY", tmp_path / "REGISTRY.csv")
    args = SimpleNamespace(sources=[str(legacy)], out="", batch="批A", force=False)
    ing.cmd_parsed1(args)
    out = tmp_path / "data" / "parsed" / "pkulaw" / "批A"
    recs = [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["id"] == "P-001"
    stats = json.loads((out / "stats.json").read_text(encoding="utf-8"))
    assert stats["input"] == 2 and stats["records"] == 1
    assert stats["excluded"][0]["id"] == "P-002"
    assert stats["self_check"].get("error", {}).get("count", 0) == 0

def test_relocate_segment_recovers_whitespace():
    """拍平文本上抽出的段要回定位成原文连续子串（保留换行），否则契约判 segment_not_substring。"""
    full = "现查明：2024年4月18日，\n张某某同王某某等人以打麻将方式赌博，\n现场查获赌资3078元。"
    flat_seg = "2024年4月18日，张某某同王某某等人以打麻将方式赌博，现场查获赌资3078元。"
    got, ok = ing._relocate_segment(flat_seg, full)
    assert ok and got in full and "打麻将" in got and "\n" in got


def test_last_date_hardened():
    """加固后的 last_date：门牌/编号不当日期；○/0 中文落款可识别。"""
    assert ing.last_date("门牌2058/2059/2060号") == ""
    assert ing.last_date("编号1342-05号") == ""
    assert ing.last_date("落款二○二三年十月十日") == "2023-10-10"
    assert ing.last_date("落款二0二三年十月十日") == "2023-10-10"
    assert ing.last_date("2058/2059 与 2023-10-10 并存") == "2023-10-10"
    assert ing.last_date("门前2023.10.10 之后又写 2023年10月7日") == "2023-10-07"
    assert ing.last_date("二○二三年十三月十日") == ""          # 月越界 → 弃


def test_subject_mention_trim_l2_20261025():
    """L2 缺陷回归（协调 2026-10-25 移交）：正文贪婪捕获把整句片段当人名（canonical 12 条）。"""
    T = ing.trim_person_name
    # 12 条实测缺陷样本 → 截回姓名本体
    assert T("汪慧甜在其开设的义乌市江") == "汪慧甜"
    assert T("黄某召集违法行为人陶某等") == "黄某"
    assert T("刘爱香在义乌市苏溪镇") == "刘爱香"
    assert T("熊金元以营利为目的") == "熊金元"
    assert T("王剑华接受聘请参与赌场抽") == "王剑华"
    assert T("许宇凡的行为构成了吸毒") == "许宇凡"
    assert T("钱书清年龄达七十周岁") == "钱书清"
    for x in "韦钊 兰利珍 兰广磊 覃若电 韦汉农".split():
        assert T(x + "伙同韦佩成等人在绍兴" if x != "韦钊" else x + "伙同韦佩成等人在绍兴") == x
    # ≤6 字真名/掩码不得误伤
    for keep in ("赵本现", "谢和平", "向吕肖", "王*乙", "于某某", "迪丽热巴", "黄某", "张三"):
        assert T(keep) == keep
    # 三路兜底：正文正则路径应返回截断后的姓名
    rec = {"text_full": "主要违法事实：2021年12月12日，违法行为人汪慧甜在其开设的义乌市江东街道某超市地下室内，提供麻将桌。"}
    assert ing.subject_mention_of(rec) == "汪慧甜"


def test_gambling_hint_excludes_prior_and_venue_l2_20261025():
    """L2 修复②回归：整篇兜底不再把前科句式/场所名当本案赌博（not_gambling 9 件）。"""
    T = ing.gambling_hint_of
    # 前科句式：殴打/吸毒文书里的"曾因赌博被行政拘留"（标题行干净，赌字只在经历句）
    raw1 = ("张**殴打案行政处罚决定书\n现查明：2024年3月，张**在公园因琐事殴打李**。\n"
            "违法犯罪经历：2013年1月因赌博被行政拘留。\n根据治安法第四十三条现决定对张**行政拘留五日。")
    assert T(raw1, "", "2024年3月，张**在公园因琐事殴打李**。", {}, {}) is False
    # 场所名：寻衅滋事案发现场"麻将室内"
    raw2 = ("李**故意伤害案行政处罚决定书\n现查明：2023年8月5日，李**在长堤街244号附近麻将室内持刀将王**打伤。\n"
            "现决定对李**行政拘留十日。")
    assert T(raw2, "", "2023年8月5日，李**在长堤街244号附近", {}, {}) is False
    # 本案真赌博：facts 命中走 primary，不受兜底剔除影响
    raw3 = ("汪慧甜案行政处罚决定书\n现查明：2021年12月12日，汪慧甜在其开设的超市地下室内提供麻将桌供他人赌博并抽取台费。\n"
            "现决定对汪慧甜罚款五百元。")
    assert T(raw3, "", "2021年12月12日，汪慧甜以麻将方式聚众赌博，抽取台费获利。", {}, {}) is True
    # 兜底层前科+本案赌博并存：本案句仍在整篇中 → 仍判是（防过杀）
    raw4 = ("张*处罚决定书（facts 未抽出，标题不含赌）\n现查明：2025年5月1日，张*打转转麻将进行赌博活动，带赌资1000元。\n"
            "张*曾因赌博于2023年被罚款。\n现决定对张*罚款伍佰圆整。")
    assert T(raw4, "", "", {}, {}) is True


def test_subject_field_chain_and_org_05_20261026():
    """@0.5 回归（协调 10-26 移交 9 条）：多人串联取首、单位名原样、无停靠词不盲截。"""
    F = ing.subject_from_field
    assert F("张**李**陈*赵*") == "张**"
    assert F("许xx赵xx柏xx沙xx郑xx徐xx高xx阚xx黄xx周xx") == "许xx"
    assert F("俞xx顾xx王xx祝xx") == "俞xx"
    assert F("任*刘*万*田**") == "任*"
    assert F("邢**何**周**王**") == "邢**"
    # 单位/场所被处罚件：原样，不截
    assert F("保靖县松月湾电竞馆") == "保靖县松月湾电竞馆"
    assert F("金华市婺城区山乐电玩城") == "金华市婺城区山乐电玩城"
    assert F("ch5566.com网站投资人") == "ch5566.com网站投资人"
    # 单人掩码不误拆
    assert F("王*乙") == "王*乙"
    assert F("黄某") == "黄某"
    # 无停靠词长值不再 [:6] 盲切
    assert ing.trim_person_name("欧阳娜娜娜") == "欧阳娜娜娜"
    # 三路兜底：元数据栏多人链 → 首人
    rec = {"text_full": "决定书\n行政相对人：张** 李** 陈* 赵*\n执法级别：区/县级\n现查明：……"}
    assert ing.subject_mention_of(rec) == "张**"


def test_event_key_fallback_chain_05_20261026():
    """@0.5 回归（协调 10-26 移交 72 件）：facts 无锚时按 正文日期→决定日期→主体 降级，杜绝 机关|-|-。"""
    E = ing.event_key_of
    # 主路径不变
    assert E("如皋市公安局", "2022年9月27日查获，赌资1130元") == "如皋市公安局|2022年9月27日|1130"
    # t2 正文日期（并剥机关名【区域】前缀）
    assert E("【浙江省绍兴市诸暨市】浙江省诸暨市公安局璜山派出所", "",
             full="经查2023年5月10日聚赌，赌资40元已收缴") == "浙江省诸暨市公安局璜山派出所|2023年5月10日|40"
    # t3 决定日期+正文金额
    assert E("高邮市公安局", "", full="现场查获赌资225元、365元", decision_date="2023-08-11") == "高邮市公安局|2023-08-11|225"
    # t4 无金额 → 决定日期+主体（异案不并）
    assert E("余杭区公安分局", "", full="在棋牌室聚众赌博", decision_date="2023-06-01", subject="张**") == "余杭区公安分局|2023-06-01|张**"
    # t5 真无锚保留退化（可识别、不假装）
    assert E("某局", "", full="参与赌博") == "某局|-|-"
