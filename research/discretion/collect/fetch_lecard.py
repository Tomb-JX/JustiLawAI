"""渠道 D：下载 LeCaRDv2（门禁锚点 A3，检索评测数据）。

query 与 label 文件可直接从 GitHub 仓库拉取；55,192 个候选案例只发布在
Google Drive（国内不直连），脚本只检查本地是否已放置，不会也无法自动下载——
需要时用浏览器（或代理）从 candidate/README.md 中的链接手动下载，
解压后放到 research/data/lecard/candidates/ 再运行一次即可核验。

用法（任意目录）：python fetch_lecard.py
产出：research/data/lecard/{query,label,others}/ + checksums.tsv
"""

from __future__ import annotations

import time
from pathlib import Path

from common import DATA_DIR, get_with_retry, manifest_add, manifest_load, report, sha256_path

LECARD_DIR = DATA_DIR / "lecard"
BASE = "https://raw.githubusercontent.com/THUIR/LeCaRDv2/main"

FILES = {
    "query/query.json": 800,
    "query/test_query.json": 160,
    "query/train_query.json": 640,
    "query/common_query.json": None,
    "query/controversial_query.json": None,
    "query/procedural_query.json": None,
    "query/query_allcontext.json": None,
    "label/relevence.trec": None,
    "label/relevence_gold.trec": None,
    "label/test_relevence.trec": None,
    "label/test_relevence_gold.trec": None,
    "others/criminal charges.txt": None,
    "others/stopword.txt": None,
}


def main() -> None:
    manc_rows = []
    checksums = []
    for rel, expect_lines in FILES.items():
        dest = LECARD_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            report(f"下载 {rel} ...")
            data = get_with_retry(f"{BASE}/{rel.replace(' ', '%20')}").content
            dest.write_bytes(data)
            time.sleep(1)
        digest = sha256_path(dest)
        checksums.append(f"{digest}  {rel}")
        if expect_lines is not None:
            n = sum(1 for _ in open(dest, encoding="utf-8"))
            ok = "OK" if n == expect_lines else f"异常（期望 {expect_lines}）"
            report(f"  {rel}: {n} 行 [{ok}]")
        manc_rows.append((rel, digest))

    (LECARD_DIR / "checksums.tsv").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    cand_dir = LECARD_DIR / "candidates"
    if cand_dir.is_dir() and any(cand_dir.iterdir()):
        report(f"候选集已就位：{cand_dir}")
    else:
        report(
            "\n候选集（55,192 份候选案例）未就位——只在 Google Drive 发布：\n"
            "  https://drive.google.com/file/d/1CqQ0ID5_9-qxaZm9TGLh38dVhLfYnl_C/view\n"
            f"  请手动下载解压到 {cand_dir}/ 后重跑本脚本核验。\n"
            "  A3 锚点评测（P4 前）才需要候选集；query/label 已可直接开发。"
        )

    if not any(r["source_url_or_ref"].endswith("THUIR/LeCaRDv2") for r in manifest_load()):
        manifest_add(
            {
                "channel": "D",
                "source_type": "数据集",
                "source_url_or_ref": "https://github.com/THUIR/LeCaRDv2",
                "title": "LeCaRDv2 检索评测集（query+label 自动下载；候选集待手动）",
                "sha256": sha256_path(LECARD_DIR / "checksums.tsv"),
                "status": "纳入",
                "notes": "A3 锚点；候选集 5.5 万件需从 Google Drive 手动获取，见脚本输出",
            }
        )
    report("\n完成。")


if __name__ == "__main__":
    main()
