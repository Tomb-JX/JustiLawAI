"""扫描件 OCR（设计 docs/04-plan/web-harvest-design.md §5 ③）：复用本机已有的 Windows 自带 OCR，Tesseract 作备用。

为什么选 Windows OCR：2026-10-16 用定兴扫描件对比，Windows OCR（zh-Hans-CN）全文几乎无误，约 1 秒一张；
Tesseract 5.5 chi_sim 把"拘留"认成"掏留"、"违法"认成"速法"，会直接破坏处罚结果抽取。两者都已装在本机，不需新装。
做法：收集正文只有附件的页面的图片 → 一个 Windows PowerShell 5.1 进程批量识别（winocr.ps1，写法沿用
astrbot-ops 的 vision_lib.ps1）→ Windows OCR 返回为空的图（单边超过 10000 像素的长图）改用 Tesseract →
每页合并、纠错、并回折行后写 harvest/ocr/<页面id>.txt；parse.py 发现该文件时改用它解析并标 ocr=true
（校正阶段重点核对）。已识别过的页面不重做。PDF 附件暂不处理（本轮没有）。

用法（仓库根目录）：python research/discretion/harvest/ocr.py [--limit N] [--engine windows|tesseract]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discover"))

from search import data_root  # noqa: E402

PS51 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
TESSERACT = Path(os.environ.get("TESSERACT_CMD", r"D:\01_Apps\Tools\Tesseract-OCR\tesseract.exe"))
IMAGE = re.compile(r"\.(jpe?g|png|bmp|tiff?)$", re.I)
# OCR 常见繁简混淆与形近字（只收实测见过、且不会误伤正常文本的）
FIXES = {"題": "题", "亘告": "宣告", "掏留": "拘留"}
# 段首锚点：这些词前面的换行保留，其余折行并回段落
KEEP_BREAK = re.compile(r"\n(?!(现查明|经查|以上事实|上述事实|根据|执行方式|逾期不|被处罚人|违法行为人|行政处罚决定书|一式))")


def normalize(text: str) -> str:
    """纠常见错字，并把扫描件的折行并回段落：OCR 按版面换行，"行政拘<换行>留十日"会让结果抽取失败。"""
    for a, b in FIXES.items():
        text = text.replace(a, b)
    text = re.sub(r"(\d)兀", r"\g<1>元", text)  # 实测"95000兀"
    return KEEP_BREAK.sub("", text)


def pending_pages(hdir: Path) -> list[dict]:
    pages: dict[str, dict] = {}
    for line in (hdir / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        pages[rec["url"]] = rec
    out = []
    for p in pages.values():
        files = [f for f in p.get("attachment_files", []) if IMAGE.search(f)]
        if p["status"] == "ok" and files and not (hdir / "ocr" / f"{p['page_id']}.txt").exists():
            out.append({**p, "images": files})
    return out


def ocr_windows(paths: list[Path], work: Path) -> dict[str, str]:
    lst, out = work / "ocr_list.txt", work / "ocr_out.jsonl"
    lst.write_text("\n".join(str(p) for p in paths), encoding="utf-8")
    env = {**os.environ, "OCR_LIST": str(lst), "OCR_OUT": str(out)}
    subprocess.run([str(PS51), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "winocr.ps1")],
                   env=env, check=False, capture_output=True, timeout=60 * 60)
    res = {}
    for line in out.read_text(encoding="utf-8").splitlines() if out.exists() else []:
        rec = json.loads(line)
        if not rec.get("error"):
            lines = rec["lines"] if isinstance(rec["lines"], list) else [rec["lines"]]
            res[rec["path"]] = "\n".join(lines)
    return res


def ocr_tesseract(paths: list[Path]) -> dict[str, str]:
    res = {}
    for p in paths:
        r = subprocess.run([str(TESSERACT), str(p), "stdout", "-l", "chi_sim", "--psm", "6"], capture_output=True, timeout=300)
        txt = r.stdout.decode("utf-8", errors="ignore")
        res[str(p)] = re.sub(r"(?<=[\u4e00-\u9fa5，。、：；（）〔〕《》])[ \t]+(?=[\u4e00-\u9fa5，。、：；（）〔〕《》\d])", "", txt)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="扫描件 OCR")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少个页面（0 = 全部）")
    ap.add_argument("--engine", choices=["windows", "tesseract"], default="windows")
    args = ap.parse_args()
    hdir = data_root().parent / "harvest"
    (hdir / "ocr").mkdir(parents=True, exist_ok=True)
    # 已有 OCR 文本按当前纠错规则重新规范化（幂等；纠错表更新后旧文件也能受益）
    for f in (hdir / "ocr").glob("*.txt"):
        old = f.read_text(encoding="utf-8")
        new = normalize(old)
        if new != old:
            f.write_text(new, encoding="utf-8")
    todo = pending_pages(hdir)[: args.limit or None]
    paths = [hdir / f for p in todo for f in p["images"]]
    if not paths:
        print({"pages": 0})
        return
    texts = ocr_windows(paths, hdir) if args.engine == "windows" else ocr_tesseract(paths)
    empty = [q for q in paths if not texts.get(str(q), "").strip()] if args.engine == "windows" else []
    if empty:
        # Windows OCR 单边上限 10000 像素，超长拼接图会返回空；这些改用 Tesseract 兜底
        texts.update(ocr_tesseract(empty))
    done = 0
    for p in todo:
        parts = [texts.get(str(hdir / f), "") for f in p["images"]]
        body = normalize("\n".join(x for x in parts if x).strip())
        if len(re.sub(r"\s", "", body)) >= 50:
            (hdir / "ocr" / f"{p['page_id']}.txt").write_text(body, encoding="utf-8")
            done += 1
    print({"pages": len(todo), "images": len(paths), "recognized_pages": done, "engine": args.engine,
           "tesseract_fallback_images": len(empty)})


if __name__ == "__main__":
    main()
