"""生成台账复核表：docs/06-algorithm/ledgers/<省>.md（python scripts/ledger_report.py）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.discretion import ledger as L  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "docs/06-algorithm/ledgers"

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, led in L.all_ledgers().items():
        (OUT / f"{name}.md").write_text(L.to_markdown(led), encoding="utf-8")
        print(name, L.summary(led))
