"""S2 定位层单测（合成样例，姓名虚构）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from locate import OffsetIndex, locate  # noqa: E402
from cleanse import cleanse  # noqa: E402


def _index_of(orig: str, channel: str = "web") -> tuple[str, OffsetIndex]:
    res = cleanse(orig, channel)
    return res.cleaned, OffsetIndex(res.to_edits())


def test_exact_unique_with_orig_mapping():
    cleaned, idx = _index_of("经查，张某某在某棋牌室赌博。\n决定给予行政拘留十日。")
    loc = locate(cleaned, "张某某在某棋牌室赌博", idx)
    assert loc.status == "exact_unique"
    assert cleaned[loc.clean_start:loc.clean_end] == "张某某在某棋牌室赌博"
    assert cleaned[loc.orig_start:loc.orig_end] == "张某某在某棋牌室赌博"  # 无删除段时 orig=clean 内容一致


def test_exact_multi():
    cleaned = "张某某赌博。另查明张某某赌博前科。"
    loc = locate(cleaned, "张某某赌博")
    assert loc.status == "exact_multi" and loc.occurrences == 2


def test_ws_tolerance():
    cleaned, idx = _index_of("张某某于2023年5月在某处赌博，赌资五千元。")
    # 模型引文带了一个多余空格（自发纠错形态）
    loc = locate(cleaned, "张某某于2023年5月 在某处赌博", idx)
    assert loc.status == "ws_unique"
    assert cleaned[loc.clean_start:loc.clean_end].startswith("张某某于2023年5月")


def test_deleted_content_fails_not_guesses():
    cleaned, idx = _index_of("首页 > 专题专栏 > 警务公开\n张某某在某地赌博被查获。")
    # 引文引用了已被 S0 删除的导航内容 → 必须失败，不回猜测坐标
    loc = locate(cleaned, "警务公开张某某在某地赌博被查获", idx)
    assert loc.status == "fail"


def test_fuzzy_partial_within_kept_run():
    cleaned = "违法行为人张某某伙同李某某王某某赵某钱某孙某周某吴某郑某在某茶楼内以牌九方式赌博。"
    # 引文漏抄了中间若干字（长文本部分改写形态）
    quote = "违法行为人张某某伙同李某某王某某赵某钱某孙某周某吴某郑某茶楼牌九"
    loc = locate(cleaned, quote)
    assert loc.status in ("fuzzy_unique", "ws_unique", "exact_unique")
    if loc.status == "fuzzy_unique":
        assert cleaned[loc.clean_start:loc.clean_end]  # 坐标有效
        assert loc.note.startswith("最长块")


def test_short_quote_no_fuzzy():
    cleaned = "赌博案件中张某某被处罚款。"
    loc = locate(cleaned, "张某某赌博")  # 短引文且不逐字存在
    assert loc.status == "fail"


def test_empty_quote():
    assert locate("任意", "").status == "empty"


def test_boundary_markers():
    cleaned, idx = _index_of("首页 > 专题专栏 > 警务公开\n张某某赌博。")
    # 导航行被删除，kept 从"张"开始 → clean0 对应原文位置 >0，且边界集合非空
    assert idx.origs[0] > 0
    assert idx.boundaries
