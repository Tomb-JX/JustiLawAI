"""发现层 L4 栏目扩展：从富矿主机的样例文书找到所在栏目，识别 CMS 家族、估算规模，生成 columns.csv（设计 §3.6、§6）。

做法与具体 CMS 无关：
  1. 候选栏目页来自三路——面包屑链接、样例 URL 的上级目录、文书页上带"处罚/公示/复议"字样的导航链接；
  2. 抓每个候选页，统计其中与样例文书 URL「同形」（数字归一后路径形状相同）的链接数，最多者即栏目列表页；
  3. 从列表页读翻页信息（index_N / 共N页 / createPageHTML / page=N）估算总量，标题含赌博词的占比估算密度；
  4. CMS 指纹（jpaas / gkmlpt / 大汉 jcms / TRS / 安徽政务公开 public / 动态 .do/.php）写进 cms_family，
     jpaas、gkmlpt 两家再抽出栏目参数（数据链路可直接喂家族适配器）。
礼貌抓取：只读公开页；每主机最多 --per-host 次请求、间隔 ≥1.5s；遇到验证码/JS 盾/非 200 跳过并记录。
只抓文书页和栏目第一页，不下载正文、不保存页面（设计 §5）。

用法（仓库根目录）：python research/discretion/discover/expand.py [--min-target 5] [--hosts a.gov.cn,b.gov.cn]
输入：$JUSTILAW_DATA_DIR/discover/out/<最新>/candidates.jsonl，本目录 domains.csv
产出：$JUSTILAW_DATA_DIR/discover/out/<同一日期>/columns.csv（并更新该目录 SHA256SUMS）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from search import data_root

HERE = Path(__file__).resolve().parent
DOMAINS_CSV = HERE / "domains.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
ID_PARAMS = re.compile(r"^(id|rid|aid|docid|infoid|articleid|newsid|contentid)$", re.I)
NAV_WORDS = re.compile(r"行政处罚|处罚|执法公示|执法信息|事后公开|双随机|复议|强制|法定主动公开|政府信息公开目录")
GAMBLING_WORDS = re.compile(r"赌|麻将|行罚决字")
COLUMN_FIELDS = ["column_id", "domain", "publisher", "cms_family", "entry_url", "params_json", "items_on_page",
                 "est_pages", "est_items", "gambling_titles", "penalty_purity", "strict_items", "known_targets", "status", "sample_urls", "found_from"]

FAMILIES = [  # (家族, 判定正则)，按特异性从高到低
    ("hanweb_jpaas", re.compile(r"jpaas-publish-server")),
    ("gkmlpt", re.compile(r"/gkmlpt/")),
    ("hanweb_jcms", re.compile(r"/module/web/jpage/dataproxy|/col/col\d+/|jcms_files|/jcms/")),
    ("anhui_public", re.compile(r"/zfxxgk/public/\d+/\d+\.html")),
    ("trs", re.compile(r"createPageHTML|/t20\d{6}_\d+\.s?html")),
    ("dynamic_do", re.compile(r"\.do\?")),
    ("dynamic_php", re.compile(r"\.php\?")),
    ("static_shtml", re.compile(r"\.shtml")),
]


# ---------- 纯函数（有单测） ----------

def url_shape(url: str) -> str:
    """把 URL 归一成形状：主机 + 路径里的数字串→#、32 位十六进制 id→H；查询参数只留键名。"""
    p = urlparse(url)
    path = re.sub(r"[0-9a-f]{32}", "H", p.path.lower())
    path = re.sub(r"\d+", "#", path)
    keys = ",".join(sorted(k.split("=")[0] for k in p.query.split("&") if k))
    return f"{p.hostname}{path}?{keys}" if keys else f"{p.hostname}{path}"


def url_shape_strict(url: str) -> str:
    """严格形状：只把路径里最后一段数字和 id 类参数值归一，类目号保留。
    M3 实测：定兴 xzzfcon-467-* 是公安、xzzflist-426 是审计局，宽松形状会把两者混为一谈。"""
    p = urlparse(url)
    path = re.sub(r"[0-9a-f]{32}", "H", p.path.lower())
    head, _, last = path.rpartition("/")
    head = re.sub(r"/(?:\d{4}|\d{6}|\d{8})(?=/|$)", "/#", head)  # 日期目录（/2024/、/202504/、/20211227/）
    if re.search(r"\d{4,}", last):
        last = re.sub(r"\d{4,}", "#", last)        # 文件名里的日期、编号（TRS t20240909_2404394；xzzfcon-467-33736 的 33736）
    else:
        last = re.sub(r"\d+(?=\D*$)", "#", last)   # 没有长编号时归一最后一段数字；短类目号（467）不受影响
    path = f"{head}/{last}"
    q = "&".join(sorted(kv.split("=")[0] + ("=#" if ID_PARAMS.match(kv.split("=")[0]) else "=" + kv.partition("=")[2])
                        for kv in p.query.split("&") if kv))
    return f"{p.hostname}{path}?{q}" if q else f"{p.hostname}{path}"


PENALTY_TITLE = re.compile(r"处罚|罚决|罚字|赌|违法|拘留|罚款|某某|^[一-龥]{1,2}[某*xX×]+$")


def dominant_seeds(urls: list[str], k: int = 3) -> list[str]:
    """从同一主机的赌博文书里挑样例：取严格形状里最常见的那一类（多数文书所在的栏目），再取前 k 条。"""
    if not urls:
        return []
    top = Counter(url_shape_strict(u) for u in urls).most_common(1)[0][0]
    return [u for u in urls if url_shape_strict(u) == top][:k]


def extract_links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for href, text in re.findall(r'<a\b[^>]*?href\s*=\s*["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        if href.lower().startswith(("javascript", "mailto")):
            continue
        title = re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", text)))
        out.append((urljoin(base, unescape(href.strip())), title))
    return out


def breadcrumb_links(html: str, base: str) -> list[str]:
    m = re.search(r"(当前位置|您的位置|您现在的位置|所在位置|crumb|position|location)", html, re.I)
    if not m:
        return []
    links = extract_links(html[m.start(): m.start() + 1500], base)
    return [u for u, t in links if t and not re.search(r"首页|主页|打印|关闭", t)]


def parent_dirs(url: str, depth: int = 2) -> list[str]:
    """样例 URL 的上级目录，由近到远；每级给出"目录/"与常见首页文件名（不少站目录本身 403）。"""
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    out = []
    for k in range(1, depth + 2):
        if len(parts) - k < 1:
            break
        last = parts[len(parts) - k - 1] if len(parts) - k - 1 >= 0 else ""
        # 日期目录（如 /202604/、/20211227/、/2024/）不是栏目，跳过但继续往上
        if re.fullmatch(r"\d{4}|\d{6,8}", last):
            continue
        d = f"{p.scheme}://{p.netloc}/" + "/".join(parts[: len(parts) - k]) + "/"
        out += [d, d + "index.html", d + "index.shtml"]
    return out


def list_variants(url: str) -> list[str]:
    """从详情页 URL 推列表页：去掉 show/detail/info/con 一类后缀、去掉 id 类参数、详情编号换成第 1 页。"""
    p = urlparse(url)
    head, _, name = p.path.rpartition("/")
    stem, dot, ext = name.partition(".")
    keep = "&".join(kv for kv in p.query.split("&") if kv and not ID_PARAMS.match(kv.split("=")[0]))
    out = []
    for pat, rep in ((r"_?show$", ""), (r"_?detail$", ""), (r"Info$", ""), (r"con$", ""), (r"_?content$", "")):
        new = re.sub(pat, rep, stem, flags=re.I) if not re.search(r"-\d+-\d+$", stem) else stem
        if new != stem:
            out.append(f"{p.scheme}://{p.netloc}{head}/{new}{dot}{ext}" + (f"?{keep}" if keep else ""))
    m = re.fullmatch(r"([a-z]+?)con-(\d+)-\d+", stem, re.I)  # 如 xzzfcon-467-33736 → xzzf-467-1
    if m:
        out += [f"{p.scheme}://{p.netloc}{head}/{m.group(1)}list-{m.group(2)}-more.{ext}",
                f"{p.scheme}://{p.netloc}{head}/{m.group(1)}list-{m.group(2)}-1.{ext}",
                f"{p.scheme}://{p.netloc}{head}/{m.group(1)}-{m.group(2)}-1.{ext}"]
    if re.search(r"Info\.do$|Info$", stem + dot + ext):  # 如 getXzzfIndexInfo.do → listXzzfIndex.do
        out.append(f"{p.scheme}://{p.netloc}{head}/" + re.sub(r"^get(.*)Info", r"list\1", stem) + dot + ext)
    return list(dict.fromkeys(out))


def path_tokens(url: str) -> set[str]:
    """样例 URL 路径里的字母词（去掉 con/show/detail/info 一类后缀），用来跟踪同栏目的导航链接。
    如 xzzfcon-467-1.html → {xzzf}；/htqzfxxgk/xzcf2/… → {htqzfxxgk, xzcf}；zhifa_show.php → {zhifa}。"""
    toks = set()
    for seg in urlparse(url).path.split("/"):
        for w in re.findall(r"[a-z_]{3,}", seg.lower()):
            w = re.sub(r"(con|_?show|_?detail|info|_?content|html|shtml|php)$", "", w).strip("_")
            if len(w) >= 3 and w not in {"index", "www", "art", "col", "content", "public", "app", "news"}:
                toks.add(w)
    return toks


def page_count(html: str) -> int:
    nums = [int(x) for x in re.findall(r"createPageHTML\(\s*['\"]?(\d+)", html)]
    nums += [int(x) for x in re.findall(r"共\s*(\d+)\s*页", html)]
    nums += [int(x) for x in re.findall(r"第?\s*\d+\s*/\s*(\d+)\s*页", re.sub(r"<[^>]+>", "", html))]  # 当前第 1 / 26 页
    nums += [int(x) for x in re.findall(r"(?:pageCount|totalPage|pagecount|totalpage|countPage)[\"'\s:=]+(\d+)", html)]
    nums += [int(x) for x in re.findall(r"createPageHTML\(\s*['\"][\w-]+['\"]\s*,\s*(\d+)", html)]  # createPageHTML('page_div',67,…)
    nums += [int(x) + 1 for x in re.findall(r"index_(\d+)\.s?html", html)]  # TRS：index_1 是第 2 页
    nums += [int(x) for x in re.findall(r"[?&](?:page|pageNo|pageIndex|curpage|p)=(\d+)", html, re.I)]
    nums += [int(x) for x in re.findall(r"_(\d+)\.s?html\"[^>]*>\s*(?:尾页|末页)", html)]
    return max([n for n in nums if n < 5000] or [1])


def total_items(html: str) -> int:
    """列表页上写明的总条数（"共 123 条"），没有则 0。"""
    nums = [int(x) for x in re.findall(r"共计?\s*(\d+)\s*(?:条|篇|项|个)", re.sub(r"<[^>]+>", "", html))]
    return max([n for n in nums if n < 200000] or [0])


def cms_family(html: str, url: str) -> str:
    blob = html + " " + url
    for name, pat in FAMILIES:
        if pat.search(blob):
            return name
    return "unknown"


def family_params(html: str, family: str, url: str) -> dict:
    if family == "hanweb_jpaas":
        got = {k: (re.search(k + r"[\"'\s:=]+[\"']?([\w-]+)", html) or [None, None])[1]
               for k in ("webId", "tplSetId", "pageId")}
        return {k: v for k, v in got.items() if v}
    if family == "gkmlpt":
        sid = re.search(r"SID[\"'\s:=]+[\"']?(\d+)", html)
        base = re.match(r"(https?://[^?#]*?/gkmlpt)", url)
        return {k: v for k, v in (("base", base and base.group(1)), ("sid", sid and sid.group(1))) if v}
    if family == "hanweb_jcms":
        col = re.search(r"/col/col(\d+)/", url) or re.search(r"columnid[\"'\s:=]+[\"']?(\d+)", html, re.I)
        return {"columnid": col.group(1)} if col else {}
    return {}


def score_list_page(html: str, base: str, seed_shapes: set[str],
                    strict_shapes: set[str] | None = None) -> tuple[float, int, list[tuple[str, str]]]:
    """返回 (得分, 同形条目数, 条目)。得分 = 同形条目数 × 同形占全部链接的比例：
    栏目列表页同形链接集中，首页虽然也有一些同形链接但占比很低（M3 实测清河首页被误选）。
    给了严格形状时，有严格同形条目的页面得分 ×3（同类目优先，避免跨部门的同构列表）。"""
    links = extract_links(html, base)
    items = list(dict.fromkeys((u, t) for u, t in links if url_shape(u) in seed_shapes))
    n = len({u for u, _ in items})
    share = n / max(1, len({u for u, _ in links}))
    strict = sum(url_shape_strict(u) in strict_shapes for u, _ in items) if strict_shapes else 0
    return n * share * (3 if strict else 1), n, items


# ---------- 抓取 ----------

class Fetcher:
    def __init__(self, per_host: int, interval: float = 1.5):
        import requests

        self.s = requests.Session()
        self.s.trust_env = False
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                               "Accept-Language": "zh-CN,zh;q=0.9"})
        self.per_host, self.interval = per_host, interval
        self.used: Counter = Counter()
        self._last = 0.0

    def get(self, url: str) -> tuple[int, str]:
        host = urlparse(url).hostname or ""
        if self.used[host] >= self.per_host:
            return -1, ""
        self.used[host] += 1
        gap = self.interval - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()
        try:
            r = self.s.get(url, timeout=20, verify=False)
        except Exception:  # noqa: BLE001 - 单站失败不阻断
            return 0, ""
        enc = r.apparent_encoding if (not r.encoding or r.encoding.lower() == "iso-8859-1") else r.encoding
        return r.status_code, r.content.decode(enc or "utf-8", errors="ignore")


def blocked(status: int, html: str) -> str:
    """非 200，或是挑战页（短页面 + 验证/盾特征）。正常页面里也会出现"验证码"字样（登录框），只看短页。"""
    if status != 200:
        return f"http_{status}"
    if len(html) < 300 or re.search(r"__jsluid|acw_sc__|jsl_clearance", html) or (
            len(html) < 5000 and re.search(r"验证码|滑动验证|安全验证|访问过于频繁", html)):
        return "blocked_or_js"
    return ""


def expand_host(host: str, cands: list[dict], publisher: str, known: int, fetch: Fetcher) -> list[dict]:
    seeds = dominant_seeds([c["url"] for c in cands if c["host"] == host and c["gambling"] == "是"])
    if not seeds:
        return []
    seed_shapes = {url_shape(u) for u in seeds}
    strict_shapes = {url_shape_strict(u) for u in seeds}
    st, doc = fetch.get(seeds[0])
    why = blocked(st, doc)
    base_row = {"domain": host, "publisher": publisher, "known_targets": known, "sample_urls": " ".join(seeds[:2])}
    if why:
        return [{**base_row, "column_id": host, "status": f"doc_{why}", "cms_family": "unknown"}]

    base_host = re.sub(r"^(www|zwfw)\.", "", host)
    same_host = lambda u: re.sub(r"^(www|zwfw)\.", "", urlparse(u).hostname or "") == base_host  # noqa: E731
    tokens = set().union(*(path_tokens(s) for s in seeds))

    def follow(html: str, base: str, src: str, cap: int = 5) -> list[tuple[str, str]]:
        """页面上值得一试的链接：栏目名像处罚/公示，或 URL 含样例路径词（图片链接没有文字也能跟上）。"""
        out = [(u, src) for u, t in extract_links(html, base)
               if same_host(u) and url_shape(u) not in seed_shapes
               and (NAV_WORDS.search(t) or any(k in u.lower() for k in tokens))]
        return list(dict.fromkeys(out))[:cap]

    candidates: list[tuple[str, str]] = [(u, "breadcrumb") for u in reversed(breadcrumb_links(doc, seeds[0])) if same_host(u)]
    candidates += [(u, "list_variant") for u in list_variants(seeds[0])]
    candidates += follow(doc, seeds[0], "doc_link", cap=4)
    candidates += [(u, "parent_dir") for u in parent_dirs(seeds[0])]
    seen, best, home_done, tried = set(), None, False, []
    while candidates:
        url, src = candidates.pop(0)
        if url in seen or url in seeds:
            continue
        seen.add(url)
        st, html = fetch.get(url)
        if st == -1:
            break  # 本主机请求额度用完
        tried.append(url)
        if blocked(st, html):
            continue
        score, n, items = score_list_page(html, url, seed_shapes, strict_shapes)
        if n and (best is None or score > best[0]):
            best = (score, url, src, html, items)
        if n >= 8 and score >= 2:
            break  # 已经足够像列表页
        if src in ("home_nav", "doc_link") and n == 0:
            candidates += follow(html, url, "drill", cap=3)  # 入口页（如 xzzfindex.html）再跳一层
        if not candidates and not home_done and (best is None or best[0] < 2):
            home_done = True  # 兜底：首页导航
            hp = f"{urlparse(seeds[0]).scheme}://{urlparse(seeds[0]).netloc}/"
            st, home = fetch.get(hp)
            if not blocked(st, home):
                candidates += follow(home, hp, "home_nav")
    family = cms_family(doc, seeds[0])
    if best is None:
        status = "js_shell" if family in ("hanweb_jpaas", "gkmlpt") or doc.count("<script") > 15 else "list_not_found"
        return [{**base_row, "column_id": host, "cms_family": family, "status": status,
                 "params_json": json.dumps(family_params(doc, family, seeds[0]), ensure_ascii=False),
                 "found_from": "tried: " + " ".join(tried[:6])}]
    score, url, src, html, items = best
    n = len({u for u, _ in items})
    fam = cms_family(html, url) if family == "unknown" else family
    pages = page_count(html)
    total = total_items(html)
    g = sum(bool(GAMBLING_WORDS.search(t)) for _, t in items)
    purity = sum(bool(PENALTY_TITLE.search(t)) for _, t in items) / max(1, n)
    strict = sum(url_shape_strict(u) in strict_shapes for u, _ in items)
    status = "ok" if score >= 2 and purity >= 0.5 and strict else ("mixed" if score >= 2 else "weak_match")
    return [{
        **base_row,
        "column_id": hashlib.sha1(url.encode()).hexdigest()[:10],
        "cms_family": fam, "entry_url": url,
        "params_json": json.dumps(family_params(html, fam, url) or family_params(doc, fam, seeds[0]), ensure_ascii=False),
        "items_on_page": n, "est_pages": pages, "est_items": total or n * pages,
        "gambling_titles": f"{g}/{n}", "penalty_purity": f"{purity:.2f}", "strict_items": strict,
        "status": status, "found_from": src,
    }]


def latest_out(root: Path) -> Path:
    outs = sorted(p for p in (root / "out").iterdir() if (p / "candidates.jsonl").exists())
    if not outs:
        raise SystemExit("没有 candidates.jsonl，请先运行 triage.py")
    return outs[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description="栏目扩展：生成 columns.csv")
    ap.add_argument("--min-target", type=int, default=5, help="只扩展 domains.csv 里 n_target ≥ 该值的主机")
    ap.add_argument("--hosts", default="", help="逗号分隔，指定主机（覆盖 --min-target）")
    ap.add_argument("--per-host", type=int, default=12, help="每主机最多请求数")
    args = ap.parse_args()

    out_dir = latest_out(data_root())
    cands = [json.loads(x) for x in (out_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    with open(DOMAINS_CSV, encoding="utf-8", newline="") as f:
        doms = {r["host"]: r for r in csv.DictReader(f)}
    hosts = [h for h in args.hosts.split(",") if h] or [h for h, r in doms.items() if int(r["n_target"]) >= args.min_target]
    # 同一县的 www. / 裸域名 / zwfw. 归为一组：依次尝试，第一个定位成功的为准（M3 实测魏县 www. 失败、裸域名成功）
    groups: dict[str, list[str]] = defaultdict(list)
    for h in hosts:
        groups[re.sub(r"^(www|zwfw)\.", "", h)].append(h)

    fetch = Fetcher(args.per_host)
    rows = []
    for members in groups.values():
        got = []
        for h in members:
            d = doms.get(h, {})
            got = expand_host(h, cands, d.get("publisher", ""), int(d.get("n_target", 0) or 0), fetch)
            if got and got[0]["status"] == "ok":
                break
        for r in got:
            print(f"{r['status']:<16} {r.get('cms_family',''):<13} {r['domain']:<28} {r.get('est_items','')!s:>6} "
                  f"{r.get('gambling_titles','')!s:>7}  {r.get('entry_url','')}", flush=True)
        rows += got
    picked = list(groups)

    path = out_dir / "columns.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMN_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    sums = out_dir / "SHA256SUMS"
    lines = [l for l in sums.read_text(encoding="utf-8").splitlines() if not l.endswith("columns.csv")] if sums.exists() else []
    lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  columns.csv")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\n主机 {len(picked)} 个 → 定位到栏目 {len(ok)} 个，估算条目合计 {sum(int(r['est_items']) for r in ok)} → {path}")


if __name__ == "__main__":
    main()
