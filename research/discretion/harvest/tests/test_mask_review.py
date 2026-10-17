"""mask_review.py 的脱敏函数单测（离线、无正文内容）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mask_review import redact  # noqa: E402


def test_redact_person_keeps_surname_only():
    assert redact("陆厚琴家中") == "陆■■家中"


def test_redact_preserves_publisher_mask_markers():
    # 某村 / xx村 是已遮蔽标记，必须原样保留（区分"已遮蔽"与"真残留"全靠它）
    assert redact("在某村和xx县赌博") == "在某村和xx县赌博"


def test_redact_place_and_digits():
    w = redact("红旗村老五楼212室")
    assert "红旗" not in w and "212" not in w          # 村名专名与房间号都要遮
    assert "楼" in w and "室" in w
    assert redact("赌资8416元") == "赌资■■■■元"
