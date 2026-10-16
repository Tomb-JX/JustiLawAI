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
