"""渠道 C：手动导出文件的统一导入工具。

裁判文书网（需登录+验证码）与商用库（北大法宝/威科，需校内账号）不做自动抓取——
在浏览器里按检索式人工导出（docx / html / pdf / csv / txt），
把文件丢进 research/data/inbox/ 后运行本脚本完成：挪入 raw/manual/、
算哈希、登记台账。文件名即标题（可含文号）。

用法（任意目录）：python import_manual.py [--channel C] [--region 浙江]
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

from common import DATA_DIR, RAW_DIR, manifest_add, report, sha256_path

INBOX = DATA_DIR / "inbox"
DEST = RAW_DIR / "manual"

ALLOWED = {".pdf", ".docx", ".doc", ".html", ".htm", ".csv", ".txt", ".json"}


def guess_title(stem: str) -> str:
    return re.sub(r"[_\s]+", " ", stem).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="C")
    ap.add_argument("--region", default="")
    ap.add_argument("--source-type", default="判决书")
    ap.add_argument("--ref", default="", help="检索式或来源说明，写入 notes")
    args = ap.parse_args()

    if not INBOX.is_dir():
        raise SystemExit(f"收件目录不存在：{INBOX}（请先创建并放入导出文件）")
    DEST.mkdir(parents=True, exist_ok=True)

    files = [p for p in sorted(INBOX.iterdir()) if p.suffix.lower() in ALLOWED and p.is_file()]
    if not files:
        raise SystemExit(f"收件目录里没有可导入的文件（支持 {'/'.join(sorted(ALLOWED))}）")

    n = 0
    for p in files:
        dest = DEST / p.name
        if dest.exists():
            report(f"  跳过（已存在同名）：{p.name}")
            continue
        shutil.move(str(p), dest)
        manifest_add(
            {
                "channel": args.channel,
                "source_type": args.source_type,
                "source_url_or_ref": args.ref or "manual-export",
                "region": args.region,
                "title": guess_title(p.stem),
                "sha256": sha256_path(dest),
                "harvest_by": "manual",
                "status": "待筛选",
                "notes": f"浏览器手动导出，导入于 {datetime.now():%Y-%m-%d %H:%M}",
            }
        )
        n += 1
    report(f"导入完成：{n} 个文件 → {DEST}")


if __name__ == "__main__":
    main()
