"""详情提取（M2）：零配额抓正文 → .txt + 形态预探 → 交既有解析链（pkulaw_ingest.py）。

为什么先抓网页而不是下载 Word：查看详情是订阅内普通浏览，不占下载配额；
抓下来的文本按 `pkulaw_ingest.DOC_EXTS` 里的 `.txt` 形态直接进既有解析（零改动）。
下载 Word 仅在需要存档原件时用（download.py），或 recon 证明网页内容被阉割时回退。

形态预探（probe）复用 pkulaw_ingest 的实测判据：叙述式 / 字段式表格 / 其他。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from pkulaw_agent.api import Pacer
from pkulaw_agent.session import BASE

COLLECT_DIR = Path(__file__).resolve().parents[1]
if str(COLLECT_DIR) not in sys.path:
    sys.path.insert(0, str(COLLECT_DIR))

import pkulaw_ingest as ingest  # noqa: E402  —— 解析内核（单测与命令行同源）

# 正文块定位：优先法宝详情页正文容器 #divFullText（实测 2026-10-16：文档完整且带文号）；
# 无此容器（摘要/表格形态）时退回"文本多、链接少"的最大块通用启发式。
MAIN_TEXT_JS = r"""() => {
    const score = (el) => {
        const t = el.innerText || '';
        if (t.length < 200) return 0;
        const linkLen = [...el.querySelectorAll('a')]
            .reduce((s, a) => s + (a.innerText || '').length, 0);
        return t.length * (1 - Math.min(1, linkLen / Math.max(1, t.length)));
    };
    const ft = document.querySelector('#divFullText');
    const ftText = ft ? (ft.innerText || '') : '';
    let best = document.body, bestScore = score(document.body);
    if (!ftText || ftText.length < 200) {
        for (const el of document.querySelectorAll('div,article,section,main')) {
            const s = score(el);
            if (s > bestScore) { best = el; bestScore = s; }
        }
    }
    const useFt = ftText.length >= 200;
    const text = useFt ? ftText : (best.innerText || '');
    return {text, tag: useFt ? 'DIV#divFullText' : best.tagName,
            source: useFt ? 'divFullText' : 'heuristic',
            len: text.length, ft: ftText.length,
            bodyLen: (document.body ? document.body.innerText.length : 0),
            title: document.title || ''};
}"""

DOC_WAIT_JS = ("() => { const el = document.querySelector('#divFullText');"
               " const t = el ? (el.innerText || '') : '';"
               " return {ft: t.length,"
               " body: document.body ? document.body.innerText.length : 0}; }")


def safe_filename(name: str, fallback: str = "doc") -> str:
    """Windows/跨平台文件名清洗。"""
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", (name or "").strip())
    name = re.sub(r"_+", "_", name).strip("._")
    return (name or fallback)[:120]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def probe_text(text: str) -> dict:
    """形态预探：**直接复用 pkulaw_ingest.parse_any_doc**（与下游解析同源判定，不重复实现）。

    form：narrative（有事实段的叙述式，含"结果栏内"落位）/ table（字段式公示）/ other。
    判决书等其它形态归 other（走 fetch 存档 + cases 链处理）。
    """
    parsed = ingest.parse_any_doc(text, filename="")
    parsed_form = parsed.get("form", "")
    form = {"叙述式-独立成篇": "narrative", "叙述式-结果栏内": "narrative",
            "字段式公示": "table"}.get(parsed_form, "other")
    flat = ingest.flatten(text)
    table = ingest.table_cells(flat)
    rows_hit = sum(1 for label in ingest.TABLE_ROWS if table.get(label))
    if form == "table" and rows_hit < 3 and not parsed.get("doc_no"):
        form = "other"  # 解析器对"无事实"文本一律标注字段式；连文号都没有的按 other 处理
    facts = parsed.get("facts", "") or ""
    return {
        "form": form,
        "is_narrative": bool(facts),
        "facts_len": len(facts),
        "table_rows_hit": rows_hit,
        "has_amount": ingest.has_amount(facts),
        "pklaw_id": parsed.get("pkulaw_id", "") or ingest.pkulaw_id_from_text(text),
        "doc_no": parsed.get("doc_no", ""),
        "parsed_form": parsed_form,
        "gambling_hint": bool(parsed.get("gambling_hint")),
        "len": len(text),
    }


def wait_for_doc(page, *, timeout_s: float = 40) -> dict:
    """等正文渲染：优先等 #divFullText（法宝详情页正文容器）出现且有内容；
    摘要/表格形态页无此容器时，等 body 文本量稳定后放行。SPA 首跳会重建执行上下文，重试容忍。"""
    import time as _time
    t0 = _time.time()
    last_body = -1
    stable = 0
    st = {"ft": 0, "body": 0}
    while _time.time() - t0 < timeout_s:
        try:
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001
            pass
        try:
            st = page.evaluate(DOC_WAIT_JS)
        except Exception as exc:  # noqa: BLE001 —— 跳转中上下文销毁：重试
            if "Execution context" in str(exc):
                continue
            raise
        if st.get("ft", 0) >= 200:
            return st
        body = st.get("body", 0)
        if body > 1200 and body == last_body:
            stable += 1
            if stable >= 2:
                return st
        else:
            stable = 0
        last_body = body
    return st


def extract_detail_text(page) -> dict:
    for _ in range(3):
        try:
            data = page.evaluate(MAIN_TEXT_JS)
            data["text"] = dedup_page_text(data.get("text") or "")
            return data
        except Exception as exc:  # noqa: BLE001
            if "Execution context" in str(exc):
                try:
                    page.wait_for_timeout(800)
                except Exception:  # noqa: BLE001
                    pass
                continue
            raise
    return {"text": "", "tag": "", "source": "", "len": 0, "bodyLen": 0, "title": ""}


def doc_no_from_title(title: str) -> str:
    """页面标题兜底取文号（实测标题形如"王xx行政处罚(土公（沟）行罚决字〔2026〕527号)-北大法宝V6官网"）。"""
    import re as _re
    m = _re.search(ingest.DOC_NO_RE, title or "")
    if not m:
        return ""
    return m.group(0).lstrip("（()").strip()


def dedup_page_text(text: str) -> str:
    """清理页面自身伪影（实测详情页 divFullText 的站点高亮/复制组件产物，三类）：
    ① 整段精确重复（"…出生。…出生。"）；
    ② 段内"截断前缀+全文"（"…养猪院内，王2026年08月26日…"）；
    ③ 跨段碎片重复（全文之后又出现该句尾部、被拆成若干 <p>）。
    ①②按行清理（保留完整副本），③按"连续行拼接若是其它整行的子串"判定并丢弃。"""
    raw_lines = [l.strip() for l in (text or "").split("\n")]
    lines: list[str] = []
    for s in raw_lines:
        if len(s) >= 24 and len(s) % 2 == 0 and s[: len(s) // 2] == s[len(s) // 2:]:
            s = s[: len(s) // 2]  # ① 半段精确重复
        if len(s) >= 40:
            p = s.find(s[:20], 5)
            if p > 0 and len(s) - p >= 12:
                s = s[p:]  # ② 截断前缀：保留后一次完整副本
        if s:
            lines.append(s)
    keep = [True] * len(lines)
    for i in range(len(lines)):
        for span in (1, 2, 3):
            if i + span > len(lines) or not all(keep[i:i + span]):
                break
            seg = "".join(lines[i:i + span])
            if len(seg) < 12:
                continue
            hit = any(k != i and len(o) >= max(2 * len(seg), 40) and seg in o
                      for k, o in enumerate(lines) if not (i <= k < i + span))
            if hit:  # ③ 跨段碎片：是其它整行的子串
                for k in range(i, i + span):
                    keep[k] = False
                break
    return "\n".join(l for l, k in zip(lines, keep) if k)


def fetch_one(session, record: dict, docs_dir: Path, *, keep_other: bool = True) -> dict:
    """打开一条详情页 → 抓正文 → 预探 → 落 .txt。返回提取记录（不抛异常，错误入记录）。"""
    url = record.get("url") or ""
    if url.startswith("/"):
        url = BASE + url
    out = {"gid": record.get("gid", ""), "url": url, "title": record.get("title", ""),
           "doc_no": record.get("doc_no", ""), "txt": "", "sha256": "", "error": ""}
    if not url:
        out["error"] = "no_url"
        return out
    try:
        session.page.goto(url, wait_until="commit", timeout=120_000)
        wait_for_doc(session.page)
        detail = extract_detail_text(session.page)
        text = detail.get("text") or ""
        session._check_challenge()
        probe = probe_text(text)
        name = safe_filename(record.get("doc_no") or probe.get("pklaw_id")
                             or record.get("gid") or record.get("title") or "doc")
        keep = probe["form"] == "narrative" or keep_other
        if keep and text.strip():
            txt_path = docs_dir / f"{name}.txt"
            txt_path.write_text(text, encoding="utf-8")
            out["txt"] = str(txt_path)
            out["sha256"] = sha256_text(text)
        out["form"] = probe["form"]
        out["is_narrative"] = probe["is_narrative"]
        out["table_rows_hit"] = probe["table_rows_hit"]
        out["has_amount"] = probe["has_amount"]
        out["pklaw_id"] = probe["pklaw_id"]
        out["text_len"] = probe["len"]
        out["source"] = detail.get("source", "")
        if not out["doc_no"]:
            out["doc_no"] = probe["doc_no"] or doc_no_from_title(detail.get("title", ""))
        out["main_len"] = detail.get("len", 0)
        out["body_len"] = detail.get("bodyLen", 0)
    except Exception as exc:  # noqa: BLE001 —— 单条失败不拖垮批次
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def make_ingest_doc_text(record: dict, probe: dict, text: str) -> str:
    """补齐解析器需要的线索行：标题（含引证码/文号）在前，正文随后。

    既有解析器对"首行为空导致标题漏判"已有修复，但网页抓取的文本头部是导航噪声，
    所以这里显式构造一行标题（`<文号> <标题>`），保证 赌博特征/文号 判定稳定。
    """
    head_bits = [record.get("doc_no") or probe.get("doc_no") or "",
                 record.get("title") or ""]
    head = " ".join(b for b in head_bits if b).strip()
    if probe.get("pklaw_id"):
        head = f"{head} ({probe['pklaw_id']})"
    return f"{head}\n\n{text}" if head else text


def fetch_run(session, run_dir: Path, *, out_dir: Path | None = None, limit: int = 0,
              min_interval_s: float = 2.0, keep_other: bool = True,
              logger=print) -> dict:
    """对 run_dir/results.jsonl 逐条抓取（零配额）。产出 docs/*.txt 与 extract.jsonl。"""
    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir else run_dir / "fetch"
    docs_dir = out_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    results = [json.loads(x) for x in
               (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    if limit:
        results = results[:limit]
    pacer = Pacer(min_interval_s)
    records: list[dict] = []
    counters = {"narrative": 0, "table": 0, "other": 0, "error": 0}
    for i, rec in enumerate(results, 1):
        pacer.wait(session.page)
        got = fetch_one(session, rec, docs_dir, keep_other=keep_other)
        counters[got["error"] and "error" or got.get("form", "other")] += 1
        records.append(got)
        flag = got.get("form", "?") if not got["error"] else f"ERR {got['error'][:60]}"
        logger(f"  [{i}/{len(results)}] {(got.get('doc_no') or got.get('gid') or '')[:28]} → {flag}")
        if i % 20 == 0:  # 中途落盘，断点可续
            _save(out_dir, records)
    summary = _save(out_dir, records, counters=counters)
    logger(f"✓ 抓取完成：{counters} → {out_dir/'extract.jsonl'}")
    return summary


def _save(out_dir: Path, records: list[dict], counters: dict | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "extract.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"records": len(records), "counters": counters or {}}
    (out_dir / "fetch.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_ingest(fetch_dir: Path, out_dir: Path, *, harvest_date: str = "",
               worklist: str = "", batch: str = "", logger=print) -> int:
    """把 fetch 产物交给既有解析链（pkulaw_ingest docs），单源不重复实现。

    解析脚本默认拒写已有产物（防覆盖其他工作流）；此处 out_dir 是本 run 专属目录，
    重跑即刷新，所以带 --force；--batch 让产物标注批次并带上时间戳兜底。
    """
    docs_dir = Path(fetch_dir) / "docs"
    cmd = [sys.executable, str(COLLECT_DIR / "pkulaw_ingest.py"), "docs",
           "--docs", str(docs_dir), "--out", str(out_dir), "--manifest", "", "--force"]
    if batch:
        cmd += ["--batch", batch]
    if harvest_date:
        cmd += ["--harvest-date", harvest_date]
    if worklist:
        cmd += ["--worklist", worklist]
    logger(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False).returncode
