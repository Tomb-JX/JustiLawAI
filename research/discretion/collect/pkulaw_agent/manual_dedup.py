"""手工批量导出（ZIP 解压后）入湖前全量去重。

背景（2026-10-27 批实测）：法宝库里同一份决定书常有两个引证码
（文件名同当事人+同案号、不同 FBMCLI.ALE.*），且浏览器翻页批量导出会与
已入湖批次（P8/P9/无锡等）重叠。import_manual 只按文件名去重，
pkulaw_ingest docs 只按引证码批内去重——跨批与同文号双引证码需要本脚本先筛。

去重键与口径（与 pkulaw_ingest 跨批合并一致：引证码 > 文号）：
  1. 引证码（FBMCLI.ALE.x → 归一 CLI.ALE.x）命中已入湖记录 → 重复导出；
  2. 文号（文件名尾部〔YYYY〕N号 → 归一半角 []，与 records.doc_no 同形）命中已入湖 → 同文异码；
  3. 暂存目录内部：同引证码 / 同文号 → 保留排序后首个。
幸存文件复制到 <src>/_keep/ 并落 dedup_report.json（全程只读已入湖数据，不改湖）。

用法（在 collect/ 下）：
  python -m pkulaw_agent.manual_dedup --src "$DATA/inbox/pkulaw/<批>-stage/all"
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import DATA_DIR  # noqa: E402

CLI_RE = re.compile(r"\((?P<cli>(?:FBM)?-?CLI(?:[.\-][A-Z]+)*\.\d+)\)")
DOCNO_RE = re.compile(r"(?P<no>[\u4e00-\u9fa5（）()]{0,24}〔\d{4}〕\d+号)\s*$")


def norm_cli(raw: str) -> str:
    return re.sub(r"^FBM", "", raw).upper()


def norm_docno(raw: str) -> str:
    return raw.replace("〔", "[").replace("〕", "]").replace("(", "（").replace(")", "）")


def parse_stem(path: Path) -> tuple[str, str]:
    stem = path.stem
    m = CLI_RE.search(stem)
    cli = norm_cli(m.group("cli")) if m else ""
    base = CLI_RE.sub("", stem).strip()
    m2 = DOCNO_RE.search(base)
    docno = norm_docno(m2.group("no")) if m2 else ""
    return cli, docno


def load_lake_keys() -> tuple[set[str], set[str]]:
    """已入湖 parsed 记录的 引证码/文号 集合（unified_raw 与 parsed 同源，读 parsed 全批）。"""
    cli_set: set[str] = set()
    docno_set: set[str] = set()
    for rf in sorted((DATA_DIR / "parsed" / "pkulaw").glob("*/records.jsonl")):
        with rf.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ref = r.get("source_ref", "")
                m = re.search(r"CLI(?:[.\-][A-Z]+)*\.\d+", ref)
                if m:
                    cli_set.add(norm_cli(m.group(0)))
                if r.get("doc_no"):
                    docno_set.add(r["doc_no"])
    return cli_set, docno_set


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="解压后的文件目录")
    ap.add_argument("--keep", default="", help="幸存文件输出目录（默认 <src>/../_keep）")
    ap.add_argument("--report", default="", help="报告 JSON 路径（默认 <src>/../dedup_report.json）")
    args = ap.parse_args()

    src = Path(args.src)
    keep = Path(args.keep) if args.keep else src.parent / "_keep"
    report_path = Path(args.report) if args.report else src.parent / "dedup_report.json"
    keep.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.iterdir() if p.is_file() and not p.name.startswith("~$"))
    lake_cli, lake_docno = load_lake_keys()

    report: dict = {"src": str(src), "files_in": len(files), "kept": 0,
                    "drop_lake_cli": [], "drop_lake_docno": [], "drop_stage_dup": [],
                    "no_cli": [], "no_docno": []}

    seen_cli: dict[str, str] = {}
    seen_docno: dict[str, str] = {}
    for p in files:
        cli, docno = parse_stem(p)
        if not cli:
            report["no_cli"].append(p.name)
        if not docno:
            report["no_docno"].append(p.name)
        if cli and cli in lake_cli:
            report["drop_lake_cli"].append({"file": p.name, "cli": cli})
            continue
        if docno and docno in lake_docno:
            report["drop_lake_docno"].append({"file": p.name, "cli": cli, "docno": docno})
            continue
        if cli and cli in seen_cli:
            report["drop_stage_dup"].append({"file": p.name, "cli": cli, "kept": seen_cli[cli],
                                             "why": "stage-cli"})
            continue
        if docno and docno in seen_docno:
            report["drop_stage_dup"].append({"file": p.name, "cli": cli, "docno": docno,
                                             "kept": seen_docno[docno], "why": "stage-docno"})
            continue
        if cli:
            seen_cli[cli] = p.name
        if docno:
            seen_docno[docno] = p.name
        shutil.copy2(p, keep / p.name)
        report["kept"] += 1

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"输入 {report['files_in']} → 保留 {report['kept']}；"
          f"湖内引证码重复 {len(report['drop_lake_cli'])}；湖内同文号 {len(report['drop_lake_docno'])}；"
          f"暂存内部重复 {len(report['drop_stage_dup'])}；无引证码 {len(report['no_cli'])}；无文号 {len(report['no_docno'])}")
    print(f"幸存目录：{keep}\n报告：{report_path}")


if __name__ == "__main__":
    main()
