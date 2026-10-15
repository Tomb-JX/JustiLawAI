"""公开网页收割（设计 docs/04-plan/web-harvest-design.md §2）：把发现层交付的单篇 URL 与可收割栏目抓成原文存档 + 正文。

  单篇   读发现层 urls.tsv（赌博=是/待定），逐篇抓取
  整栏   读发现层栏目主表里 status=ok 的栏目，自动识别翻页（下一页链接 / TRS index_N / _N 后缀 /
         JS goPage 拼参数 / ?page=N），用第 2 页验证模板后逐页列出条目，再逐篇抓取
  存档   原始 HTML → $JUSTILAW_DATA_DIR/harvest/raw/<站点>/<页面id>.html；正文 → harvest/text/<页面id>.txt
  台账   每个页面一行：数据目录 harvest/pages.jsonl（含路径与哈希）+ 本目录 manifest_web.csv（入库，
         字段与数据链路 manifest 相同，id 前缀 W-，只记来源与哈希，不含正文）
礼貌抓取：只读公开页；同一主机两次请求间隔 ≥1.5s；遇到验证码/JS 盾/非 200 记录后跳过，不绕过。已抓过的 URL 不重抓。

用法（仓库根目录）：
  python research/discretion/harvest/harvest.py urls --limit 100            # 发现层单篇 URL
  python research/discretion/harvest/harvest.py column dingxing.gov.cn --max-pages 3
  python research/discretion/harvest/harvest.py columns --max-pages 5       # 全部 ok 栏目
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discover"))

from expand import blocked, extract_links, url_shape, url_shape_strict  # noqa: E402
from search import data_root  # noqa: E402
from weekly import read_csv, registrable_site  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MANIFEST_WEB = HERE / "manifest_web.csv"
MANIFEST_FIELDS = ["id", "channel", "source_type", "source_url_or_ref", "region", "behavior_date", "decision_date",
                   "law_version", "title", "sha256", "harvest_date", "harvest_by", "status", "notes"]
START = re.compile(r"行政处罚决定书|行政复议决定书|不予行政处罚决定书|违法行为人|被处罚人|申请人[:：]|现查明|决定书[（(]通知书[)）]文号"
                   r"|行政处罚机关|行政相对人|案件名称|处罚事由|违法事实")
END = re.compile(r"关于本站|网站地图|主办单位|主办：|版权所有|Copyright|打印本页|关闭窗口|【打印】|相关链接|分享到|上一篇|下一篇")
SOURCE_TYPE = {"处罚决定": "处罚决定书", "不予处罚": "处罚决定书", "处罚汇总": "执法公示", "执法结果表": "执法公示",
               "复议": "行政复议决定书"}


# ---------- 纯函数（有单测） ----------

def html_to_text(html: str) -> str:
    """去脚本样式，块级标签换行，保留表格单元间隔。"""
    h = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</(p|div|tr|li|h\d|table|section|article)>", "\n", h, flags=re.I)
    h = re.sub(r"</t[dh]>", " ", h, flags=re.I)
    t = unescape(re.sub(r"<[^>]+>", "", h))
    lines = [re.sub(r"[ \t　\xa0]+", " ", x).strip() for x in t.splitlines()]
    return "\n".join(x for x in lines if x)


def main_text(html: str) -> str:
    """正文 = 第一个起始锚点到其后第一个页脚锚点之间；找不到起点时返回全文（由解析阶段标 segmented=false）。"""
    text = html_to_text(html)
    m = START.search(text)
    if not m:
        return text
    start = text.rfind("\n", 0, m.start()) + 1
    e = END.search(text, m.end())
    return text[start: e.start() if e else len(text)].strip()


def page_templates(html: str, base: str) -> list[str]:
    """候选翻页模板（含 {n}）。多种写法都给出，由调用方用第 2 页实测哪一个有效。"""
    out: list[str] = []
    for u, t in extract_links(html, base):
        if t in ("2", "下一页", "[2]") and re.search(r"\d", urlparse(u).path + urlparse(u).query):
            if re.search(r"(?<=[_=/-])2(?=\D*$)", u):
                out.append(re.sub(r"(?<=[_=/-])2(?=\D*$)", "{n}", u))
    m = re.search(r"createPageHTML\([^)]*?['\"](\w+)['\"]\s*,\s*['\"](s?html)['\"]", html)
    if m:  # TRS：第 n 页 = index_{n-1}.html
        out.append(urljoin(base, f"{m.group(1)}_{{n-1}}.{m.group(2)}"))
    m = re.search(r"strHref\s*=\s*['\"]([^'\"]+)['\"]", html)
    if m:  # JS goPage：strHref + &page=n
        href = m.group(1)
        sep = "&" if "?" in href else "?"
        out += [urljoin(base, href) + f"{sep}page={{n}}", urljoin(base, "/" + href.lstrip("/")) + f"{sep}page={{n}}"]
    p = urlparse(base)
    stem = re.sub(r"(index)?\.s?html?$", "", p.path.rstrip("/"))
    if p.path.endswith("/") or not re.search(r"\.\w+$", p.path):
        out.append(f"{p.scheme}://{p.netloc}{stem}_{{n}}" + ("" if not p.path.endswith("/") else ""))
    sep = "&" if p.query else "?"
    out.append(base + f"{sep}page={{n}}")
    return list(dict.fromkeys(out))


ATTACH = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+?\.(?:jpe?g|png|pdf|docx?|wps)(?:[?&][^"']*)?)["']""", re.I)
ATTACH_DYNAMIC = re.compile(r"""(?:href|src)\s*=\s*["']([^"']*(?:viewFile|download|attach)[^"']*?\.(?:jpe?g|png|pdf|docx?)[^"']*)["']""", re.I)
MIN_ATTACHMENT_BYTES = 20_000
# 混合栏目（各部门处罚混在一起）按条目标题预筛：只抓公安/赌博相关；标题不含信息（如只写人名）时全抓
POLICE_TITLE = re.compile(r"公安|公[（(][^）)]{1,6}[）)]|行罚决字|赌|治安|派出所")
UNINFORMATIVE_TITLE = re.compile(r"^[一-龥]{1,3}[某*xX×]+$|^行政处罚决定书$|^详情|^政府信息公开$")
SKIP_IMG = re.compile(r"logo|banner|icon|qrcode|ewm|erweima|share|wza|jiucuo|dzjg|gh\.png|police|bg\.|button", re.I)


def attachments(html: str, base: str) -> list[str]:
    """正文附件（决定书扫描件、PDF、Word）；排除站点装饰图。只看正文区附近：页脚之后的不要。"""
    cut = END.search(html)
    body = html[: cut.start()] if cut else html
    urls = [urljoin(base, unescape(u)) for u in ATTACH.findall(body) + ATTACH_DYNAMIC.findall(body)]
    return [u for u in dict.fromkeys(urls) if not SKIP_IMG.search(u)]


def filter_titles(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """标题有信息量的栏目（≥半数标题能看出部门或案由）只留公安/赌博条目；标题多为人名或空泛时全留。"""
    if not items:
        return items
    informative = [t for _, t in items if t and not UNINFORMATIVE_TITLE.search(t)]
    if len(informative) < len(items) / 2:
        return items
    return [(u, t) for u, t in items if POLICE_TITLE.search(t or "") or UNINFORMATIVE_TITLE.search(t or "")]


def safe_title(title: str) -> str:
    """入库台账的标题只留文号：政府页面标题可能直接带当事人真名（如"关于违法行为人××行政罚款催告书的送达公告"）。"""
    from triage import DOC_NO

    m = DOC_NO.findall(title or "")
    return m[0][0] if m else ""


def fill(template: str, n: int) -> str:
    return template.replace("{n-1}", str(n - 1)).replace("{n}", str(n))


def page_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# ---------- 抓取 ----------

class Fetcher:
    def __init__(self, interval: float = 1.5):
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.s = requests.Session()
        self.s.trust_env = False
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                               "Accept-Language": "zh-CN,zh;q=0.9"})
        self.interval = interval
        self.last: dict[str, float] = defaultdict(float)

    def get(self, url: str) -> tuple[int, str, bytes]:
        host = urlparse(url).hostname or ""
        gap = self.interval - (time.monotonic() - self.last[host])
        if gap > 0:
            time.sleep(gap)
        for attempt in range(2):
            self.last[host] = time.monotonic()
            try:
                r = self.s.get(url, timeout=25, verify=False)
                enc = r.apparent_encoding if (not r.encoding or r.encoding.lower() == "iso-8859-1") else r.encoding
                return r.status_code, r.content.decode(enc or "utf-8", errors="ignore"), r.content
            except Exception:  # noqa: BLE001 - 网络抖动重试一次
                time.sleep(3)
        return 0, "", b""


class Store:
    """收割存档与台账；pages.jsonl 是"已抓过"的依据，保证重跑不重抓。"""

    def __init__(self, root: Path, manifest: Path = MANIFEST_WEB):
        self.dir = root / "harvest"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pages_path = self.dir / "pages.jsonl"
        self.manifest = manifest
        self.pages = {}
        if self.pages_path.exists():
            for line in self.pages_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.pages[rec["url"]] = rec
        rows = read_csv(manifest)
        self.next_seq = 1 + max([int(r["id"].split("-")[1]) for r in rows if r.get("id", "").startswith("W-")] or [0])

    def done(self, url: str) -> bool:
        return url in self.pages and self.pages[url]["status"] == "ok"

    def save(self, url: str, status: str, html: str, raw: bytes, meta: dict) -> dict:
        pid = page_id(url)
        site = registrable_site(urlparse(url).hostname or "") or (urlparse(url).hostname or "unknown")
        rec = {"page_id": pid, "url": url, "site": site, "status": status, "fetched_at": datetime.now().isoformat(timespec="seconds"),
               **meta}
        if status == "ok":
            raw_path = self.dir / "raw" / site / f"{pid}.html"
            text_path = self.dir / "text" / f"{pid}.txt"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw)
            text_path.write_text(main_text(html), encoding="utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            prev = self.pages.get(url, {})
            rec.update(raw_path=str(raw_path.relative_to(self.dir)), text_path=str(text_path.relative_to(self.dir)),
                       sha256=sha, manifest_id=prev.get("manifest_id") or self._manifest_add(url, sha, meta),
                       attachments=attachments(html, url))
        self.pages[url] = rec
        with open(self.pages_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def update(self, rec: dict) -> None:
        self.pages[rec["url"]] = rec
        with open(self.pages_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _manifest_add(self, url: str, sha: str, meta: dict) -> str:
        mid = f"W-{self.next_seq:06d}"
        self.next_seq += 1
        new = not self.manifest.exists()
        with open(self.manifest, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if new:
                w.writeheader()
            w.writerow({
                "id": mid, "channel": "B" if meta.get("doc_type") == "复议" else "E",
                "source_type": SOURCE_TYPE.get(meta.get("doc_type", ""), "执法公示"), "source_url_or_ref": url,
                "region": meta.get("publisher", ""), "title": safe_title(meta.get("title") or ""), "sha256": sha,
                "harvest_date": datetime.now().strftime("%Y-%m-%d"), "harvest_by": "harvest-script",
                "status": "待解析", "notes": meta.get("source", ""),
            })
        return mid


def fetch_attachments(rec: dict, fetch: Fetcher, store: Store, max_n: int = 3) -> int:
    """下载页面附件到 raw/<站点>/<页面id>_att<k>.<扩展名>，返回新下载数；正文太短（只有附件）的页面才下。"""
    text = (store.dir / rec["text_path"]).read_text(encoding="utf-8") if rec.get("text_path") else ""
    if len(re.sub(r"\s", "", text)) > 300 or not rec.get("attachments"):
        return 0
    got = 0
    files = rec.setdefault("attachment_files", [])
    for k, u in enumerate(rec["attachments"][:max_n], 1):
        ext = (re.search(r"\.(jpe?g|png|pdf|docx?|wps)", u, re.I) or ["", "bin"])[1].lower()
        path = store.dir / "raw" / rec["site"] / f"{rec['page_id']}_att{k}.{ext}"
        if path.exists():
            continue
        st, _, data = fetch.get(u)
        if st == 200 and len(data) >= MIN_ATTACHMENT_BYTES:  # 小于 20KB 的是站点装饰图（定兴每页重复两张 3KB 图标）
            path.write_bytes(data)
            files.append(str(path.relative_to(store.dir)))
            got += 1
    return got


def harvest_url(url: str, meta: dict, fetch: Fetcher, store: Store) -> dict:
    if store.done(url):
        return store.pages[url]
    st, html, raw = fetch.get(url)
    why = blocked(st, html)
    rec = store.save(url, "ok" if not why else why, html, raw, meta)
    if rec["status"] == "ok" and fetch_attachments(rec, fetch, store):
        store.update(rec)
    return rec


def enumerate_column(entry: str, samples: list[str], fetch: Fetcher, max_pages: int) -> tuple[list[tuple[str, str]], str]:
    """列出栏目条目 (url, 标题)。返回 (条目, 采用的翻页模板或说明)。"""
    loose = {url_shape(s) for s in samples}
    strict = {url_shape_strict(s) for s in samples}

    def items_of(html: str, base: str) -> list[tuple[str, str]]:
        its = [(u, t) for u, t in extract_links(html, base) if url_shape(u) in loose]
        prefer = [(u, t) for u, t in its if url_shape_strict(u) in strict]
        return list(dict.fromkeys(prefer or its))

    st, html, _ = fetch.get(entry)
    if blocked(st, html):
        return [], f"entry_{blocked(st, html)}"
    first = items_of(html, entry)
    seen = {u for u, _ in first}
    items = list(first)
    if max_pages <= 1:
        return items, "page1_only"
    for tpl in page_templates(html, entry):
        st2, h2, _ = fetch.get(fill(tpl, 2))
        if blocked(st2, h2):
            continue
        p2 = [x for x in items_of(h2, fill(tpl, 2)) if x[0] not in seen]
        if not p2:
            continue
        items += p2
        seen |= {u for u, _ in p2}
        for n in range(3, max_pages + 1):
            stn, hn, _ = fetch.get(fill(tpl, n))
            pn = [x for x in items_of(hn, fill(tpl, n)) if x[0] not in seen] if not blocked(stn, hn) else []
            if not pn:
                break
            items += pn
            seen |= {u for u, _ in pn}
        return items, tpl
    return items, "no_pagination_found"


# ---------- 编排 ----------

def latest_out(root: Path) -> Path:
    return sorted(p for p in (root / "discover" / "out").iterdir() if (p / "urls.tsv").exists())[-1]


def run_urls(root: Path, limit: int, fetch: Fetcher, store: Store) -> dict:
    rows = [r for r in read_csv(latest_out(root) / "urls.tsv", delimiter="\t") if r["gambling"] in ("是", "待定")]
    rows.sort(key=lambda r: -int(r.get("priority") or 0))
    todo = [r for r in rows if not store.done(r["url"])][:limit]
    stats = defaultdict(int)
    for i, r in enumerate(todo, 1):
        rec = harvest_url(r["url"], {"source": "discover_url", **{k: r[k] for k in ("doc_type", "title", "publisher", "gambling")}},
                          fetch, store)
        stats[rec["status"]] += 1
        if i % 20 == 0:
            print(f"  {i}/{len(todo)} {dict(stats)}", flush=True)
    return dict(stats)


def run_column(root: Path, site: str, max_pages: int, fetch: Fetcher, store: Store) -> dict:
    cols = read_csv(root / "discover" / "state" / "columns_master.csv")
    col = next((c for c in cols if (registrable_site(c["domain"]) or c["domain"]) == site and c["status"] == "ok"), None)
    if not col:
        return {"error": f"栏目主表里没有 {site} 的 ok 栏目"}
    items, how = enumerate_column(col["entry_url"], col["sample_urls"].split(), fetch, max_pages)
    listed = len(items)
    items = filter_titles(items)
    print(f"  [{site}] 列出 {listed} 条，标题预筛后 {len(items)} 条（翻页：{how}）", flush=True)
    stats = defaultdict(int)
    for u, t in items:
        rec = harvest_url(u, {"source": f"column:{col['column_id']}", "title": t, "publisher": col.get("publisher", ""),
                              "doc_type": "", "column_entry": col["entry_url"]}, fetch, store)
        stats[rec["status"]] += 1
    return {"listed": len(items), "pagination": how, **stats}


def main() -> None:
    ap = argparse.ArgumentParser(description="公开网页收割")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("urls")
    u.add_argument("--limit", type=int, default=100)
    c = sub.add_parser("column")
    c.add_argument("site")
    c.add_argument("--max-pages", type=int, default=3)
    cs = sub.add_parser("columns")
    cs.add_argument("--max-pages", type=int, default=5)
    sub.add_parser("attachments", help="对已抓页面补识别、补下载附件（不重抓页面）")
    args = ap.parse_args()
    root, fetch = data_root().parent, Fetcher()
    store = Store(root)
    if args.cmd == "urls":
        print(run_urls(root, args.limit, fetch, store))
    elif args.cmd == "column":
        print(run_column(root, args.site, args.max_pages, fetch, store))
    elif args.cmd == "attachments":
        n = 0
        for rec in list(store.pages.values()):
            if rec["status"] != "ok":
                continue
            if "attachments" not in rec:
                html = (store.dir / rec["raw_path"]).read_bytes().decode("utf-8", errors="ignore")
                rec["attachments"] = attachments(html, rec["url"])
            for f in list(rec.get("attachment_files", [])):  # 清掉早先误下的装饰小图
                fp = store.dir / f
                if fp.exists() and fp.stat().st_size < MIN_ATTACHMENT_BYTES:
                    fp.unlink()
                    rec["attachment_files"].remove(f)
            k = fetch_attachments(rec, fetch, store)
            store.update(rec)
            n += k
        print({"downloaded": n})
    else:
        cols = [c for c in read_csv(root / "discover" / "state" / "columns_master.csv") if c["status"] == "ok"]
        for col in cols:
            print(run_column(root, registrable_site(col["domain"]) or col["domain"], args.max_pages, fetch, store))


if __name__ == "__main__":
    main()
