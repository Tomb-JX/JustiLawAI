"""A raw HTML row is the source boundary, even when flattened text runs into next row."""

from __future__ import annotations

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parse import parse_page  # noqa: E402
from to_parsed1 import repair_table_batch  # noqa: E402


def _page(tmp_path, monkeypatch, html):
    root = tmp_path / "data"
    raw = root / "harvest" / "raw" / "table.html"
    raw.parent.mkdir(parents=True)
    raw.write_text(html, encoding="utf-8")
    monkeypatch.setenv("JUSTILAW_DATA_DIR", str(root))
    return {"page_id": "table1", "manifest_id": "W-990001", "url": "https://example.gov/table",
            "fetched_at": "2026-10-18T00:00:00", "site": "example.gov", "title": "行政处罚结果",
            "publisher": "某县公安局", "raw_path": "raw/table.html"}


def test_table_row_recovery_prevents_next_row_bleed(tmp_path, monkeypatch):
    html = """<table><tr><th>编号</th><th>案由</th><th>处罚决定书文号</th><th>法律依据</th><th>被处罚人</th><th>裁决时间</th><th>处罚结果</th><th>其它</th></tr>
    <tr><th>拘留</th><th>罚款</th></tr>
    <tr><td>1</td><td>赌博</td><td>某公（行）行罚决字〔2024〕1号</td><td>《中华人民共和国治安管理处罚法》第七十条</td><td>王*甲</td><td>2024-01-01</td><td>2日</td><td>770元</td><td></td></tr>
    <tr><td>2</td><td>赌博</td><td>某公（行）行罚决字〔2024〕2号</td><td>《中华人民共和国治安管理处罚法》第七十条</td><td>王*乙</td><td>2024-01-02</td><td>3日</td><td>800元</td><td></td></tr></table>"""
    page = _page(tmp_path, monkeypatch, html)
    cases = parse_page(page, "赌博\n某公（行）行罚决字〔2024〕1号\n王*甲\n2日\n770元\n2\n赌博")
    assert len(cases) == 2
    assert "王*乙" not in cases[0]["text_full"] and "800元" not in cases[0]["text_full"]
    assert cases[0]["outcome"]["detention_days"] == 2 and cases[0]["outcome"]["fine"] == 770
    assert cases[0]["text_facts"] == ""  # 案由不是行为事实


def test_sparse_table_keeps_unknown_numeric_penalty(tmp_path, monkeypatch):
    html = """<table><tr><th>序号</th><th>姓名</th><th>案由</th><th>依据</th><th>处罚结果</th><th>文号</th></tr>
    <tr><td>1</td><td>李*</td><td>赌博</td><td>《中华人民共和国治安管理处罚法》第七十条</td><td>行政拘留、罚款</td><td>某公（行）行罚决字〔2024〕3号</td></tr></table>"""
    case = parse_page(_page(tmp_path, monkeypatch, html), "赌博 行政拘留、罚款")[0]
    assert case["outcome"]["detention_days"] == 0 and case["outcome"]["fine"] == 0
    assert case["text_facts"] == ""


def test_repair_batch_replaces_only_table_page(tmp_path, monkeypatch):
    html = """<table><tr><th>编号</th><th>案由</th><th>处罚决定书文号</th><th>法律依据</th><th>被处罚人</th><th>裁决时间</th><th>处罚结果</th><th>其它</th></tr>
    <tr><td>1</td><td>赌博</td><td>某公（行）行罚决字〔2024〕1号</td><td>《中华人民共和国治安管理处罚法》第七十条</td><td>王*甲</td><td>2024-01-01</td><td>2日</td><td>770元</td><td></td></tr></table>"""
    page = _page(tmp_path, monkeypatch, html)
    root = tmp_path / "data"
    (root / "harvest" / "pages.jsonl").write_text(json.dumps({**page, "status": "ok"}) + "\n", encoding="utf-8")
    source = root / "parsed" / "web" / "old" / "records.jsonl"
    source.parent.mkdir(parents=True)
    old = [{"id": "W-990001-d1", "source_ref": page["url"], "quality": {"tier": "L2-只有结果"}},
           {"id": "W-990002", "source_ref": "https://example.gov/other", "quality": {"tier": "L1-金标候选"}}]
    source.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in old), encoding="utf-8")
    target = root / "parsed" / "web" / "new"
    stats = repair_table_batch(source, target, {})
    rows = [json.loads(line) for line in (target / "records.jsonl").open(encoding="utf-8")]
    assert stats["old_table_records_removed"] == 1 and stats["table_records_added"] == 1
    assert {row["id"] for row in rows} == {"W-990002", "W-990001-t1"}
    assert rows[1]["outcome"]["fine"] == 770
