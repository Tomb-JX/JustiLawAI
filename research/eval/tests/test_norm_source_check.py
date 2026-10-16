"""规范库原文与北大法宝原文一致（回归保护：有人改了 YAML 里的条文，这里会报出来）。

只读本地缓存（$JUSTILAW_DATA_DIR/engine/pkulaw_mcp/cache），不连网、不花积分；没有缓存时跳过。
重新取原文：research/.venv/Scripts/python research/eval/pkulaw_mcp/verify_norms.py --budget <分>
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pkulaw_mcp import client  # noqa: E402
from pkulaw_mcp import verify_norms  # noqa: E402

pytestmark = pytest.mark.skipif(not (client.DATA_DIR / "cache").exists(), reason="没有法宝缓存")


def test_every_recorded_article_matches_pkulaw(capsys):
    verify_norms.main(["--offline"])
    report = __import__("json").loads((client.DATA_DIR / "norm_check" / "report.json").read_text("utf-8"))
    bad = [r for r in report["rows"] if r["result"] not in ("一致", "法宝未取到")]
    assert not bad, bad
    assert sum(r["result"] == "一致" for r in report["rows"]) >= 22
