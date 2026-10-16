"""渠道 C：手动导出文件的统一导入工具。

裁判文书网（需登录+验证码）与商用库（北大法宝/威科，需校内账号）不做自动抓取——
在浏览器里按检索式人工导出（docx / html / pdf / csv / txt），
把文件丢进 research/data/inbox/ 后运行本脚本完成：挪入 raw/、算哈希、登记台账。
文件名即标题（可含文号）；文件名里的法宝引证码（FBM-CLI.AP.…）直接作 source_url_or_ref，
同一条记录重复导出（跨批次）自动去重不重复登记。

用法（任意目录）：
  python import_manual.py [--channel C] [--region 浙江]
  # 按批次导入（推荐）：递归收集、跳过 Word 锁文件 ~$…，归位 raw/<批次>/
  python import_manual.py --src "$JUSTILAW_DATA_DIR/inbox/pkulaw/20261016-南京50篇" \\
      --dest-sub pkulaw/20261016-南京50篇 --source-type 处罚决定书 \\
      --ref 法宝-行政执法库-南京50篇 --harvest-date 2026-10-16
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

from common import DATA_DIR, RAW_DIR, manifest_add, registry_add, report, sha256_path

INBOX = DATA_DIR / "inbox"
DEST = RAW_DIR / "manual"

ALLOWED = {".pdf", ".docx", ".doc", ".html", ".htm", ".csv", ".txt", ".json"}


def guess_title(stem: str) -> str:
    return re.sub(r"[_\s]+", " ", stem).strip()


def pkulaw_id_from_stem(stem: str) -> str:
    """文件名里的法宝引证码（FBM-CLI.AP.… / FBMCLI.C.…）→ 作 source_url_or_ref。"""
    m = re.search(r"\(((?:FBM)?-?CLI(?:[.\-][A-Z]+)*\.\d+)\)", stem)
    return m.group(1) if m else ""


def check_pkulaw_channel(files: list[Path], channel: str) -> str:
    """护栏：带法宝引证码的文件应登 channel=P（契约 W/B/P/C；C=采购、P=法宝）。

    返回提示语（空串表示无提示）；实测 2026-10-16 漏传 --channel P 把 47 行登成了 C-*。
    """
    hit = sum(1 for p in files if pkulaw_id_from_stem(p.stem))
    if hit and channel != "P":
        return (f"注意：{hit}/{len(files)} 个文件名含法宝引证码，但 channel={channel}"
                f"（契约里 P=法宝、C=采购）——法宝导出请用 --channel P")
    return ""


def collect_files(src: Path) -> list[Path]:
    """收集可导入文件：递归；跳过 Word 锁文件（~$…）与隐藏文件（实测导出目录里常有）。
    另跳过作业台自动产出的元数据文件（downloads.json/downloaded.jsonl 等，不是文书）。"""
    skip_names = {"downloads.json", "downloaded.jsonl", "fetch.json", "extract.jsonl",
                  "run.json", "run.jsonl", "jobs.jsonl", "run_report.md"}
    out: list[Path] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in ALLOWED:
            continue
        if p.name.startswith("~$") or p.name.startswith("."):
            continue
        if p.name in skip_names:
            continue
        out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="C")
    ap.add_argument("--region", default="")
    ap.add_argument("--source-type", default="判决书")
    ap.add_argument("--ref", default="", help="检索式或来源说明，写入 notes")
    ap.add_argument("--src", default="", help="来源目录（默认 $DATA/inbox 顶层；给了就递归）")
    ap.add_argument("--dest-sub", default="", help="raw/ 下目标子目录（可含批次名，如 pkulaw/南京50篇）")
    ap.add_argument("--harvest-date", default="", help="下载日期（缺省用今天）")
    ap.add_argument("--copy", action="store_true",
                    help="复制而非移动（来源是用户自己的资料夹时用，保留原件）")
    args = ap.parse_args()

    src = Path(args.src) if args.src else INBOX
    if not src.is_dir():
        raise SystemExit(f"来源目录不存在：{src}")
    dest_dir = (RAW_DIR / args.dest_sub) if args.dest_sub else DEST
    dest_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(src)
    if not files:
        raise SystemExit(f"{src} 里没有可导入的文件（支持 {'/'.join(sorted(ALLOWED))}）")
    hint = check_pkulaw_channel(files, args.channel)
    if hint:
        report(hint)

    hdate = args.harvest_date or datetime.now().strftime("%Y-%m-%d")
    n = moved = 0
    for p in files:
        dest = dest_dir / p.name
        if dest.exists():
            report(f"  跳过（已存在同名）：{p.name}")
            continue
        if args.copy:
            shutil.copy2(str(p), dest)
        else:
            shutil.move(str(p), dest)
        moved += 1
        ref = pkulaw_id_from_stem(p.stem) or args.ref or "manual-export"
        manifest_add(
            {
                "channel": args.channel,
                "source_type": args.source_type,
                "source_url_or_ref": ref,
                "region": args.region,
                "title": guess_title(p.stem),
                "sha256": sha256_path(dest),
                "harvest_date": hdate,
                "harvest_by": "manual",
                "status": "待筛选",
                "notes": f"浏览器手动导出；批次 {args.dest_sub or 'manual'}；导入于 {datetime.now():%Y-%m-%d %H:%M}",
            }
        )
        n += 1
    if n:
        registry_add("L0", dest_dir, records=sum(1 for p in dest_dir.rglob("*") if p.is_file()),
                     producer="collect/import_manual.py", status="现行",
                     note=f"channel={args.channel}；批次 {args.dest_sub or 'manual'}")
    report(f"导入完成：登记 {n} 个文件（{"复制" if args.copy else "移动"} {moved}）→ {dest_dir}")


if __name__ == "__main__":
    main()
