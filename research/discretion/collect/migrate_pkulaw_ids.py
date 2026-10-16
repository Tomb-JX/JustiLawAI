"""一次性迁移：法宝台账 id 前缀 C- → P-（对齐数据记录契约 records.py 的 id 约定）。

背景（合规核查 2026-10-16）：
  - 数据记录契约 `justilaw-api/app/discretion/records.py` 约定 id 前缀：W- 公开网页 / B- 复议专栏 /
    **P- 法宝** / C- 采购；
  - 本台账（collect/manifest.csv）法宝批次入库时沿用了"渠道 C（法宝）"的字面，登记为 C-001…C-346；
    而 `ingest_wenshu.py`（裁判文书采购）写的也是 channel=C（C′=采购）→ 两个来源将共用 C 前缀，歧义；
  - 处理：法宝行 channel 与 id 前缀一并改为 P（采购行保持 C）。复用同一字母表，与契约一致。

同时把已产出的 legacy 解析输出（$JUSTILAW_DATA_DIR/ingest/*）里的 `id` 字段从 C- 改成 P- 同步迁移，
避免两套 id 并存；media 其他字段不动。

用法：
  python migrate_pkulaw_ids.py --dry-run   # 只打印将要改动的行数
  python migrate_pkulaw_ids.py             # 执行（manifest 与 legacy JSONL 就地更新，先备份 .bak）
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import DATA_DIR, MANIFEST, report  # noqa: E402

LEGACY_GLOB = "ingest/*/admin_*.jsonl"
JSONL_FIELDS = ("admin_cases.jsonl", "admin_outcomes_only.jsonl", "admin_needs_review.jsonl",
                "pkulaw_out_of_scope.jsonl")


def migrate_manifest(dry: bool) -> tuple[int, dict[str, str]]:
    """法宝行（ref 以 FBM 开头的 C 行）→ channel/id 前缀改 P；按原行序重排 P 号。"""
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8-sig")))
    fields = list(rows[0].keys()) if rows else []
    targets = [r for r in rows if r.get("channel") == "C"
               and str(r.get("source_url_or_ref", "")).startswith("FBM")]
    mapping: dict[str, str] = {}
    for i, r in enumerate(targets, 1):
        new_id = f"P-{i:03d}"
        mapping[r["id"]] = new_id
        r["channel"] = "P"
        r["id"] = new_id
    report(f"台账：将迁移 {len(targets)} 行（C-* → P-*）")
    if not dry and targets:
        backup = MANIFEST.with_suffix(".csv.bak")
        shutil.copy2(MANIFEST, backup)
        with MANIFEST.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        report(f"  已写回（备份 {backup.name}）")
    return len(targets), mapping


def migrate_legacy_jsonl(mapping: dict[str, str], dry: bool) -> int:
    """legacy 解析输出里的 id（C-*→P-*），其他字段不动。"""
    n = 0
    for d in sorted(DATA_DIR.glob("ingest/*")):
        if not d.is_dir() or d.name.startswith("merged"):
            continue
        for fname in JSONL_FIELDS:
            p = d / fname
            if not p.exists():
                continue
            lines = []
            changed = 0
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                old = rec.get("id", "")
                if old in mapping:
                    rec["id"] = mapping[old]
                    changed += 1
                lines.append(json.dumps(rec, ensure_ascii=False))
            if changed:
                n += changed
                report(f"  {p.relative_to(DATA_DIR)}：{changed} 条 id 迁移")
                if not dry:
                    shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
                    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    n_rows, mapping = migrate_manifest(args.dry_run)
    n_recs = migrate_legacy_jsonl(mapping, args.dry_run)
    report(f"{'（dry-run）' if args.dry_run else ''}合计：台账 {n_rows} 行、legacy 记录 {n_recs} 条")
    report("提示：merged-* 目录请用 `pkulaw_ingest merge --force` 重新生成（保持单一事实源）。")


if __name__ == "__main__":
    main()
