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

from common import DATA_DIR, NO_EC_CIPHERS, get_with_retry, manifest_add, manifest_load, report, session, sha256_bytes, sha256_path

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
        except RuntimeError:
            # 翻页失败按存档末尾处理（站点返回 404 或 WAF 拦截均可能；
            # RuntimeError 消息不含状态码，不能按 "404" 字样判断）
            if page > 1:
                break
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


def iter_bjmtg(max_pages: int) -> list[dict]:
    base = "https://www.bjmtg.gov.cn/mtg11J023/c104083/"
    pat = re.compile(r'href="(/mtg11J023/c104083/20\d{4}/[0-9a-f]{32}\.shtml)"[^>]*>\s*([^<]{4,80})')
    seen, items, page = set(), [], 1
    while True:
        url = base + ("mtgqbm_yjlist.shtml" if page == 1 else f"mtgqbm_yjlist_{page}.shtml")  # 该站翻页文件名从 _2 起
        try:
            html = decode_html(get_with_retry(url, verify=False))
        except RuntimeError:
            if page > 1:
                break
            raise
        found = pat.findall(html)
        if not found:
            break
        new = 0
        for href, title in found:
            full = "https://www.bjmtg.gov.cn" + href
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


def iter_bjshi(max_pages: int) -> list[dict]:
    """北京市司法局「通知公告」（ff08cf81-N 翻页，共 109 页）：送达公告附复议决定全文 PDF。"""
    host = "https://sfj.beijing.gov.cn"
    base = f"{host}/sfj/zwgk/tzgg75/"
    pat = re.compile(r'href="(/sfj/zwgk/tzgg75/\d+/index\.html)"[^>]*>\s*([^<]{6,90})')
    seen, items, page = set(), [], 1
    while True:
        url = base if page == 1 else f"{base}ff08cf81-{page}.html"
        try:
            html = decode_html(get_with_retry(url, verify=False))
        except RuntimeError:
            if page > 1:
                break
            raise
        found = [
            (host + u, t.strip())
            for u, t in pat.findall(html)
            if re.search(r"复议|京政复", t)  # 栏目混有法考/采购通知，只留复议公告
        ]
        new = 0
        for full, title in found:
            if full not in seen:
                seen.add(full)
                items.append({"title": title, "url": full, "page": page})
                new += 1
        report(f"  第 {page} 页：复议 {len(found)} 条（新 {new}）")
        if new == 0 or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(1.2)
    return items


_SZ_SESSION = None


def _sz_session():
    """深圳 sf.sz.gov.cn 服务端 ECC 握手与 Python OpenSSL 不兼容，走非 EC 套件会话。"""
    global _SZ_SESSION
    if _SZ_SESSION is None:
        _SZ_SESSION = session(ciphers=NO_EC_CIPHERS)
    return _SZ_SESSION


def iter_sz(max_pages: int) -> list[dict]:
    """深圳市行政复议网上服务平台「公告送达」：深府行复公告（文号/申请人/案由）。"""
    base = "https://sf.sz.gov.cn/szsxzfywsfwpt/ggsd/"
    pat = re.compile(r'href="([^"]*ggsd/content/post_[0-9]+[.]html)"[^>]*>([^<]{4,60})')
    sess = _sz_session()
    seen, items, page = set(), [], 1
    while True:
        url = base if page == 1 else f"{base}index_{page}.html"  # 该站翻页从 index_2 起
        try:
            html = decode_html(get_with_retry(url, sess=sess, verify=False))
        except RuntimeError:
            if page > 2:
                break
            raise
        found = pat.findall(html)
        if not found:
            break
        new = 0
        for href, title in found:
            full = href if href.startswith("http") else "https://sf.sz.gov.cn" + href
            if full not in seen:
                seen.add(full)
                items.append({"title": title.strip(), "url": full, "page": page})
                new += 1
        report(f"  第 {page} 页：{len(found)} 条（新 {new}）")
        if new == 0 or (max_pages and page >= max_pages):
            break
        page += 1
        time.sleep(1.2)
    return items


def download_sz(items: list[dict]) -> None:
    out_dir = DATA_DIR / SUBDIR / "sz"
    out_dir.mkdir(parents=True, exist_ok=True)
    sess = _sz_session()
    bad = chr(92) + '/:*?"<>|' + chr(92) + "s"  # 与其他下载器相同的文件名字符类
    for i, it in enumerate(items, 1):
        # 60 条公告标题完全相同，必须用 URL 里的 post id 区分文件
        post_id = it["url"].rsplit("post_", 1)[-1].split(".", 1)[0]
        stem = re.sub("[" + bad + "]+", "_", it["title"])[:50] + "_" + post_id
        raw = out_dir / f"{stem}.html"
        try:
            if not (raw.exists() and raw.stat().st_size > 0):
                resp = get_with_retry(it["url"], sess=sess, verify=False)
                raw.write_bytes(resp.content)
            html = decode_html_content(raw.read_bytes())
            text = extract_html_text(html)
            # 只留公告正文：起点"人工智能朗读："，终点页脚标记
            a = text.find("人工智能朗读")
            if a > 0:
                text = text[a + len("人工智能朗读：") :]
            for endmark in ("扫一扫在手机打开", "【打印】", "相关文章", "分享到", "责任编辑"):
                b = text.find(endmark)
                if b > 100:
                    text = text[:b]
            (out_dir / f"{stem}.txt").write_text(text.strip(), encoding="utf-8")
            if "复议" in text or "深府行复" in text or "深府复" in text:
                manifest_add(
                    {
                        "channel": "B",
                        "source_type": "复议送达公告",
                        "source_url_or_ref": it["url"],
                        "region": "深圳市",
                        "title": it["title"][:120],
                        "sha256": sha256_bytes(html.encode("utf-8")),
                        "status": "待筛选",
                        "notes": f"深圳公告送达（第{it['page']}页）",
                    }
                )
        except Exception as e:  # noqa: BLE001
            it["error"] = str(e)[:120]
            report(f"  [{i}/{len(items)}] 失败：{it['title'][:30]} {it['error']}")
        time.sleep(1.5)
        if i % 20 == 0:
            report(f"  进度 {i}/{len(items)}")




ITERATORS = {"zhejiang": iter_zhejiang, "bjdch": iter_bjdch, "bjmtg": iter_bjmtg, "bjshi": iter_bjshi, "sz": iter_sz}
REGIONS = {"zhejiang": "浙江", "bjdch": "北京市东城区", "bjmtg": "北京市门头沟区", "bjshi": "北京市"}


def decode_html(resp) -> str:
    """部分站点不返回 charset，requests 会按 latin-1 误读 UTF-8；统一嗅探。"""
    raw = resp.content
    head = raw[:2048].lower()
    if b'charset="gb' in head or b"charset='gb" in head or b'charset=gb' in head:
        return raw.decode("gbk", errors="replace")
    return raw.decode("utf-8", errors="replace")


# ---------- 正文抽取（存 .txt 旁文件，供筛选与后续标注） ----------

def extract_html_text(html: str) -> str:
    # TRS 站（东城）正文在 id="zoom"；easysite 站（北京司法局）正文在 class="Pub" id="content"
    # （注意：easysite 页首的搜索组件也叫 id="content"，必须带上 class 才不会抓错）
    m = re.search(r'<div[^>]+id="zoom"[^>]*>(.*?)</div>\s*(?:<div|<!--)', html, re.S)
    if m:
        body = m.group(1)
    else:
        m = re.search(r'<div[^>]+class="Pub"[^>]*id="content"[^>]*>(.*)', html, re.S)
        if not m:
            body = html
        else:
            seg = m.group(1)
            for closer in ("相关附件", "版权所有", "【打印】", "【关闭】"):
                i = seg.find(closer)
                if i > 300:
                    seg = seg[:i]
                    break
            body = seg
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


def download_bjshi(items: list[dict]) -> None:
    out_dir = DATA_DIR / SUBDIR / "bjshi"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_pat = re.compile(r'href="(/sfj/zwgk/tzgg75/[^"]+\.pdf)"[^>]*>([^<]{0,60})', re.I)
    for i, it in enumerate(items, 1):
        stem = re.sub(r'[\/:*?"<>|\s]+', "_", it["title"])[:70]
        txt = out_dir / f"{stem}.txt"
        html_raw = out_dir / f"{stem}.html"
        try:
            if not (html_raw.exists() and html_raw.stat().st_size > 0):
                resp = get_with_retry(it["url"], verify=False)
                html_raw.write_bytes(resp.content)
            html = decode_html_content(html_raw.read_bytes())
            text = extract_html_text(html)
            txt.write_text(text, encoding="utf-8")
            pdfs = pdf_pat.findall(html)
            if pdfs:
                for pdf_url, _cap in pdfs:
                    full = "https://sfj.beijing.gov.cn" + pdf_url
                    pdf_name = re.sub(r"[\/:*?\"<>|\s]+", "_", (_cap or stem)[:40]) or stem
                    dest = out_dir / f"{pdf_name}.pdf"
                    if not (dest.exists() and dest.stat().st_size > 0):
                        dest.write_bytes(get_with_retry(full, verify=False).content)
                    manifest_add(
                        {
                            "channel": "B",
                            "source_type": "复议决定书",
                            "source_url_or_ref": full,
                            "region": REGIONS["bjshi"],
                            "title": (it["title"][:80] + "｜附件:" + (_cap or ""))[:120],
                            "sha256": sha256_path(dest),
                            "status": "待筛选",
                            "notes": f"公告页 {it['url']}（bjshi 第{it['page']}页）",
                        }
                    )
            else:
                # 无附件：公告正文通常载明文号与送达事项，作为补充语料登记
                manifest_add(
                    {
                        "channel": "B",
                        "source_type": "复议送达公告",
                        "source_url_or_ref": it["url"],
                        "region": REGIONS["bjshi"],
                        "title": it["title"][:120],
                        "sha256": sha256_bytes(html.encode("utf-8")),
                        "status": "待筛选",
                        "notes": f"无附件，正文txt已存（bjshi 第{it['page']}页）",
                    }
                )
        except Exception as e:  # noqa: BLE001
            it["error"] = str(e)[:120]
            report(f"  [{i}/{len(items)}] 失败：{it['title'][:30]} {it['error']}")
        time.sleep(1.5)
        if i % 20 == 0:
            report(f"  进度 {i}/{len(items)}")


def decode_html_content(raw: bytes) -> str:
    head = raw[:2048].lower()
    if b'charset="gb' in head or b"charset='gb" in head or b'charset=gb' in head:
        return raw.decode("gbk", errors="replace")
    return raw.decode("utf-8", errors="replace")



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
        if args.site == "bjshi":
            download_bjshi(items)
        elif args.site == "sz":
            download_sz(items)
        else:
            download(args.site, items)


if __name__ == "__main__":
    main()
