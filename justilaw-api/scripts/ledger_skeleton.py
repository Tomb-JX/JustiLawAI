"""新规范建台账第一步：按原文切分，生成处置待填的骨架（python scripts/ledger_skeleton.py <省级区划代码>）。

骨架里 disposition 为空，check 会逐条报"处置缺失"——逐条填完、测试通过才算建成。已存在的台账不覆盖。
"""
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.discretion import ledger as L  # noqa: E402
from app.discretion.norm_store import NORMS_DIR  # noqa: E402

if __name__ == "__main__":
    code = sys.argv[1]
    out = L.LEDGER_DIR / f"{code}.yaml"
    if out.exists():
        raise SystemExit(f"{out} 已存在，不覆盖")
    prov = yaml.safe_load((NORMS_DIR / "provinces" / f"{code}.yaml").read_text(encoding="utf-8"))
    doc = prov["documents"][0]
    items = [{"path": s.path, "text": s.text, "disposition": None} for s in L.segment(doc["text"])]
    led = {"document": doc.get("number"), "title": doc.get("title"), "province": code,
           "province_rules": f"norms/provinces/{code}.yaml", "source_sha256": L.text_sha(doc["text"]),
           "segmenter": L.SEGMENTER_VERSION, "status": "骨架（待逐条处置）", "built": date.today().isoformat(),
           "reviewed_by": [], "items": items}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(led, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    print(f"{len(items)} 条 → {out}")
