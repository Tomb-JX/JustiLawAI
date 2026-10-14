"""渠道 B：行政复议决定书公开专栏采集器（多站点）。

已适配站点：
  zhejiang  浙江省司法厅「行政复议结果公开」——汉网 jpaas 接口，PDF 附件，已脱敏。
            实测 58 条全为信息公开/建设用地类，赌博案 0（见 collect/README）。
  bjdch     北京市东城区政府「行政复议决定公开」——TRS 静态页，index_N 翻页，
            正文为 HTML（含治安处罚类复议，赌博案命中率待正文筛选）。

礼貌抓取：请求间 ≥1.5s；只抓公开专栏。

用法（任意目录）：
  python crawl_reconsider.py --site zhejiang            # 全量
  python crawl_reconsider.py --site bjdch --pages 3     # 试点前 3 页
产出：
  research/data/reconsider/<site>/   原文（pdf/html）+ index.json 索引
  manifest.csv                        每个下载文件一行台账（channel=B）
"""

from __future__ import annotations

import argparse
import json
import re
import time
from html import unescape
from pathlib import Path

from common import DATA_DIR, get_with_retry, manifest_add, manifest_load, report, sha256_path

SUBDIR = "reconsider"


# ---------- 站点适配器：每个返回 [{title, url, page}] ----------

def iter_zhejiang(max_pages: int) -> list[dict]:
    unit = "https://sft.zj.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
    base_params = {
        "parseType": "bulidstatic", "webId": "2747", "tplSetId": "O0OkO4sDR0gF86WgyE4s5",
        "pageType": "column", "tagId": "文章正文", "editType": "null", "pageId": "1228964155",
    }
    pat = re.compile(r'href="(/cms_files/filemanager[^"]+\.pdf)"[^>]*>\s*([^<]{4,120})')
    seen, items, page = set(), [], 1
    while True:
        pj = json.dumps({"pageNo": page, "pageSize": 15, "search": ""}, ensure_ascii=False)
        resp = get_with_retry(unit, params={**base_params, "paramJson": pj})
        html = (resp.json().get("data") or {}).get("html") or ""
        found = pat.findall(html)
        if not found:
            break
        new = 0
        for url, title in found:
            full = "https://sft.zj.gov.cn" + url
            if full not in seen:
                seen.add(full)
                items.append({"title": title.strip(), "url": full, "page": page})
                new += 1
        report(f"  第 {page} 页：{len(found)} 条（新 {new}）")
        if new == 0 or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(1.5)
    return items


def iter_bjdch(max_pages: int) -> list[dict]:
    base = "https://www.bjdch.gov.cn/zwgk/jgdh/qzfzcbmdh/qsfj/xzfygk/xzfyjdgk/"
    pat = re.compile(r'href="(\./20\d{4}/t\d+_\d+\.html)"[^>]*>\s*([^<]{4,60})')
    seen, items, page = set(), [], 1
    while True:
        url = base if page == 1 else f"{base}index_{page - 1}.html"
        try:
            html = get_with_retry(url, verify=False).text
        except RuntimeError as e:
            if page > 1 and "404" in str(e):
                break  # 翻过存档末尾，正常结束
            raise
        found = pat.findall(html)
        if not found:
            break
        new = 0
        for href, title in found:
            full = base + href.removeprefix("./")
            if full not in seen:
                seen.add(full)
                items.append({"title": title.strip(), "url": full, "page": page})
                new += 1
        report(f"  第 {page} 页：{len(found)} 条（新 {new}）")
        if new == 0 or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(1.5)
    return items


ITERATORS = {"zhejiang": iter_zhejiang, "bjdch": iter_bjdch}
REGIONS = {"zhejiang": "浙江", "bjdch": "北京市东城区"}


# ---------- 正文抽取（存 .txt 旁文件，供筛选与后续标注） ----------

def extract_html_text(html: str) -> str:
    m = re.search(r'<div[^>]+id="zoom"[^>]*>(.*?)</div>\s*(?:<div|<!--)', html, re.S)
    body = m.group(1) if m else html
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"[ \t\u3000]+", " ", unescape(body)).strip()


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:
        return ""


# ---------- 下载 ----------

def download(site: str, items: list[dict]) -> None:
    out_dir = DATA_DIR / SUBDIR / site
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, it in enumerate(items, 1):
        stem = re.sub(r'[\\/:*?"<>|\s]+', "_", it["title"])[:60]
        raw = out_dir / f"{stem}{Path(it['url']).suffix or '.html'}"
        if not (raw.exists() and raw.stat().st_size > 0):
            try:
                resp = get_with_retry(it["url"], timeout=60, verify=False)
                raw.write_bytes(resp.content)
                manifest_add(
                    {
                        "channel": "B",
                        "source_type": "复议决定书",
                        "source_url_or_ref": it["url"],
                        "region": REGIONS[site],
                        "title": it["title"],
                        "sha256": sha256_path(raw),
                        "status": "待筛选",
                        "notes": f"采集自 {site} 专栏第{it['page']}页",
                    }
                )
            except Exception as e:  # noqa: BLE001 - 单条失败不阻断批次
                it["error"] = str(e)[:120]
                report(f"  [{i}/{len(items)}] 失败：{it['title'][:30]} {it['error']}")
        txt = out_dir / f"{stem}.txt"
        if not txt.exists() and raw.exists():
            text = (
                extract_pdf_text(raw)
                if raw.suffix.lower() == ".pdf"
                else extract_html_text(raw.read_text(encoding="utf-8", errors="ignore"))
            )
            txt.write_text(text, encoding="utf-8")
        ok += 1 if it.get("error") is None else 0
        time.sleep(1.5)
        if i % 20 == 0:
            report(f"  进度 {i}/{len(items)}")
    report(f"下载完成：{ok}/{len(items)}（失败 {len(items) - ok}）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, choices=sorted(ITERATORS))
    ap.add_argument("--pages", type=int, default=0, help="0 = 全量（以空页为止）")
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    idx_path = DATA_DIR / SUBDIR / args.site / "index.json"
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    report(f"[{args.site}] 建索引 ...")
    if idx_path.exists() and args.pages:
        items = json.loads(idx_path.read_text(encoding="utf-8"))
        report(f"  已有索引 {len(items)} 条，跳过建索引（全量重跑会自动重建）")
    else:
        items = ITERATORS[args.site](args.pages)
        idx_path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    report(f"索引共 {len(items)} 条 → {idx_path}")

    if not args.list_only:
        download(args.site, items)


if __name__ == "__main__":
    main()
