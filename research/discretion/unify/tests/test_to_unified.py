"""to_unified 转换器端到端单测：合成 parsed-1 记录（姓名虚构）→ unified_raw 三件产物核验。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from to_unified import convert  # noqa: E402
from cleanse import replay_edits  # noqa: E402

WEB_REC = {
    "id": "W-000001", "source": "公开网页", "source_type": "处罚决定书",
    "text_full": "首页 > 专题专栏 > 警务公开\n2023年5月，张某某在某棋牌室赌博，赌资2023．5。8日累计五千元。\n发布时间：2023-06-01\n",
    "text_facts": "", "text_decision": "", "text_review": "",
    "doc_no_hash": "abc12345def67890", "authority": "某某县公安局",
    "behavior_date": "2023-05", "decision_date": "2023-06-01", "harvest_date": "2026-10-17",
    "quality": {"tier": "L1-金标候选", "gambling": "是", "in_scope": True, "form": "处罚决定书"},
    "extra": {"page_id": "p1", "site": "s", "title": "t", "publisher": "pub",
              "outcome": {"detention_items": ["罚款并执行"]}},
}

PKU_REC = {
    "id": "P-000001", "source": "法宝执法库", "source_type": "处罚决定书",
    "text_full": "经查，李某伙同他人赌博。\n|处罚种类|行政拘留|\n根据《治安管理处罚法》第七十条之规定，决定给予李某行政拘留十日。",
    "text_facts": "经查，李某伙同他人赌博。",
    "text_decision": "根据《治安管理处罚法》第七十条之规定，决定给予李某行政拘留十日。",
    "text_review": "",
    "doc_no_hash": "ffff0000ffff0000", "authority": "某市公安局某分局",
    "behavior_date": "2022-07-31", "decision_date": "2022-08-01", "harvest_date": "2026-10-16",
    "quality": {"tier": "L1-金标候选", "gambling": "是", "in_scope": True, "form": "叙述式-独立成篇"},
    "extra": {"legacy": {"pkulaw_id": "x1", "event_hint": {"authority": "某分局", "doc_seq": "123"}},
              "outcome": {"detention_items": ["拘留十日"]}, "quality": {"dup": 1}},
}


def _write(tmp: Path, recs) -> str:
    p = tmp / "records.jsonl"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def test_convert_end_to_end():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "unified_raw" / "web" / "test-batch"
        stats = convert(_write(tmp, [WEB_REC, PKU_REC]), None, str(out))
        assert stats["replay_failures"] == 0
        assert stats["n"] == 2

        rows = [json.loads(l) for l in open(out / "records.jsonl", encoding="utf-8")]
        assert [r["id"] for r in rows] == ["W-000001", "P-000001"]
        by = {r["id"]: r for r in rows}

        # web 记录：channel 推导、导航行已清、form、信封
        w = by["W-000001"]
        assert w["channel"] == "web" and w["clean_version"] == "clean:v1.1"
        assert "首页" not in w["cleaned_text"] and "2023.5.8" in w["cleaned_text"]
        assert w["form"] == "叙述式-独立成篇"          # web 的 quality.form=source_type 被真值判别覆盖
        assert w["prefilter"]["release"] is True and w["prefilter"]["release_reason"] == "gamb:是"
        assert w["extra"]["page_id"] == "p1" and w["extra"]["detention_items"] == ["罚款并执行"]
        assert w["text_orig_sha256"] and w["orig_len"] == len(WEB_REC["text_full"])

        # pkulaw 记录：管道→换行、pku_form 复用、legacy 拆平、extra.quality 丢弃
        p = by["P-000001"]
        assert p["channel"] == "pkulaw" and "处罚种类：行政拘留" in p["cleaned_text"]
        assert p["form"] == "叙述式-独立成篇"
        assert p["extra"]["pkulaw_id"] == "x1" and p["extra"]["detention_items"] == ["拘留十日"]
        assert "quality" not in p["extra"]

        # 编辑日志：脱离规则册独立回放必须逐字一致
        edits = [json.loads(l) for l in open(out / "edits.rle.jsonl", encoding="utf-8")]
        for e, r in zip(edits, rows):
            orig = WEB_REC["text_full"] if e["id"] == "W-000001" else PKU_REC["text_full"]
            assert replay_edits(orig, e) == r["cleaned_text"]

        assert (out / "stats.json").exists()


def test_convert_no_pool_sampled_zero():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "u"
        stats = convert(_write(Path(td), [WEB_REC, PKU_REC]), None, str(out))
        # WEB_REC 正文无治安法全称 → cite_abbrev 边缘标记（信息位，不影响放行）
        assert stats["sampled"] == 0 and stats["borderline"] == 1
