"""按 manifest.csv 下载论文 PDF 到 research/papers/pdf/（该目录不入库），并写出校验和。

用法（仓库根目录）：
  python research/papers/fetch_papers.py            # 只下缺失的
  python research/papers/fetch_papers.py --verify   # 不下载，只核对本地文件与 checksums.tsv

少数出版社页面会拦截脚本（如 Nature、SAGE），运行结束会列出未成功的条目，
这些请用浏览器打开 manifest 中的 url 手动下载，按 <key>.pdf 放进 pdf/ 后再运行一次以记录校验和。

PDF 不入库：arXiv 默认许可只授权 arXiv 分发。入库的是 manifest + 校验和，
任何人重新下载后都能核对拿到的是同一版本（arXiv 链接已固定版本号）。
"""
from __future__ import annotations

import csv
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdf"
MANIFEST = HERE / "manifest.csv"
CHECKSUMS = HERE / "checksums.tsv"
UA = "Mozilla/5.0"  # 部分出版社（如 Nature）拦截自定义 UA
ARXIV_DELAY_S = 3  # arXiv 要求批量抓取限速


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_checksums() -> dict[str, str]:
    if not CHECKSUMS.exists():
        return {}
    rows = csv.DictReader(CHECKSUMS.open(encoding="utf-8"), delimiter="\t")
    return {r["key"]: r["sha256"] for r in rows if r["status"] == "ok"}


def fetch(url: str, dest: Path) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF"):
        return "not_pdf"
    dest.write_bytes(data)
    return "ok"


def main():
    verify_only = "--verify" in sys.argv
    PDF_DIR.mkdir(exist_ok=True)
    known = load_checksums()
    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    out = []
    for r in rows:
        key, url = r["key"], r["pdf_url"].strip()
        dest = PDF_DIR / f"{key}.pdf"
        if not url:
            out.append((key, "", 0, "no_open_pdf"))
            continue
        status = "ok"
        if not dest.exists() and not verify_only:
            try:
                status = fetch(url, dest)
            except Exception as e:  # 网络/403 等：记录后继续
                status = f"fail:{type(e).__name__}"
            if "arxiv.org" in url:
                time.sleep(ARXIV_DELAY_S)
        if dest.exists() and status == "ok":
            digest = sha256(dest)
            if key in known and known[key] != digest:
                status = "checksum_mismatch"
            out.append((key, digest, dest.stat().st_size, status))
        else:
            out.append((key, "", 0, status if status != "ok" else "missing"))
        print(f"[{out[-1][3]}] {key}")
    if not verify_only:
        with CHECKSUMS.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["key", "sha256", "bytes", "status"])
            w.writerows(out)
    bad = [o for o in out if o[3] != "ok"]
    print(f"\n共 {len(out)} 条：成功 {len(out) - len(bad)}，未成功 {len(bad)}")
    for o in bad:
        print(f"  {o[0]}: {o[3]}")


if __name__ == "__main__":
    main()
