from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gold_candidate_audit import source_page  # noqa: E402


def test_derived_record_ids_share_original_page():
    assert source_page("W-000350-28") == "W-000350"
    assert source_page("W-000798-d4") == "W-000798"
    assert source_page("W-000374-r1") == "W-000374"
    assert source_page("W-000350") == "W-000350"
