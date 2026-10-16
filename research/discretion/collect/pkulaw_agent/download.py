"""下载文件（M3）：把"勾选 → 下载"这一步自动化；不确定时可退化为"人工点一次，文件自动收"。

三种入口（都支持 --manual 兜底）：
  1) download --run <run_dir>       对检索结果逐条开详情页 → 点下载 → 收文件（同你手工的 Word 流）
  2) download --ui-search --term X  库页检索 → 当页勾选 → 点下载（可 --pages N 自动翻页）
  3) download --url <结果页URL>     对已有结果页执行勾选 → 下载

机制：Playwright 的 download 事件（context 级，任何页面/新标签都接得住）→ 自动保存到批次目录。
自动化找不到按钮/勾选框时**不瞎试**：把页面上所有候选按钮文本打出来，然后提示用 --manual。

红线：下载会消耗订阅配额——调用方必须给 --cap；出现风控/未登录立即停。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from pkulaw_agent.fetch import safe_filename
from pkulaw_agent.session import BASE, LIB_ENTRY

DOWNLOAD_TEXT = re.compile(r"下载|导出")
NEXT_PAGE_TEXT = re.compile(r"下一页|下页|后一页")

# 下载格式偏好（实测菜单：下载PDF / 下载WORD）。auto = Word 优先、失败回退 PDF。
_WORD_PATTERNS = [re.compile(r"下载\s*WORD|下载\s*Word|Word\s*文档"),
                  re.compile(r"^\s*(WORD|Word|word)\s*$")]
_PDF_PATTERNS = [re.compile(r"下载\s*PDF|PDF\s*下载"), re.compile(r"^\s*(PDF|pdf)\s*$")]


def download_patterns(fmt: str = "auto") -> list[re.Pattern]:
    """点击顺序：先"下载"展开菜单，再按格式偏好点菜单项，最后兜底泛化模式。"""
    head = [re.compile(r"^\s*下载\s*$"), re.compile(r"批量下载|下载选中")]
    if fmt == "word":
        mid = list(_WORD_PATTERNS)
    elif fmt == "pdf":
        mid = list(_PDF_PATTERNS)
    else:
        mid = _WORD_PATTERNS + _PDF_PATTERNS
    tail = [re.compile(r"^\s*导出\s*$"), re.compile(r"^\s*(TXT|文本)\s*$"), DOWNLOAD_TEXT]
    return head + mid + tail


class DownloadSink:
    """context 级下载收集器：文件一落地就改名保存到 out_dir，并记账。"""

    def __init__(self, context, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.saved: list[dict] = []
        self._context = context
        context.on("download", self._on_download)

    def _on_download(self, download) -> None:  # noqa: ANN001 —— Playwright Download
        try:
            suggested = download.suggested_filename or f"download-{len(self.saved)}"
            name = safe_filename(Path(suggested).stem) + Path(suggested).suffix
            dst = self.out_dir / name
            n = 1
            while dst.exists():
                dst = self.out_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            download.save_as(str(dst))
            self.saved.append({"file": str(dst), "suggested": suggested,
                               "ts": time.strftime("%H:%M:%S")})
            print(f"  [下载] 已保存 {dst.name}（{download.suggested_filename}）")
        except Exception as exc:  # noqa: BLE001
            print(f"  [下载] 保存失败：{exc}")

    def count(self) -> int:
        return len(self.saved)

    def stop(self) -> None:
        try:
            self._context.remove_listener("download", self._on_download)
        except Exception:  # noqa: BLE001
            pass

    def write_manifest(self, path: Path) -> None:
        path.write_text(json.dumps(self.saved, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- UI 操作（全部防御式：找不到就报告，不猜不试） ----------------
def ui_search(page, term: str, *, lib: str = "apy", settle_s: int = 6) -> bool:
    """库页检索：优先全局搜索框 #txtSearch（首页实测存在），回车触发；返回是否疑似出结果。"""
    entry = LIB_ENTRY.get(lib, LIB_ENTRY["apy"])
    page.goto(entry, wait_until="commit", timeout=120_000)
    for _ in range(max(1, settle_s)):
        page.wait_for_timeout(1000)
    box = None
    for loc in (page.locator("#txtSearch"), page.get_by_placeholder(re.compile("法典|检索|搜索|关键词"))):
        try:
            if loc.count() > 0 and loc.first.is_visible():
                box = loc.first
                break
        except Exception:  # noqa: BLE001
            continue
    if box is None:
        print("  [UI] 未找到搜索框（#txtSearch / 占位符）——请用 --url 或 --manual 模式")
        return False
    box.fill(term)
    box.press("Enter")
    for _ in range(12):
        page.wait_for_timeout(1000)
        try:
            if page.get_by_text(re.compile("共.*条|检索结果|全选")).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    print("  [UI] 检索后未识别到结果区标志（仍继续，后续步骤会按实际页面判断）")
    return True


def report_candidates(page) -> list[str]:
    """把页面上像"下载/导出"的按钮文本列出来（诊断用，也是 --manual 的向导）。"""
    texts: list[str] = []
    try:
        found = page.evaluate(
            """() => [...document.querySelectorAll('a,button,span,div[role=button]')]
                 .map(e => (e.innerText || '').trim())
                 .filter(t => t && t.length <= 12 && /下载|导出|批量/.test(t))
                 .filter((t, i, a) => a.indexOf(t) === i).slice(0, 12)"""
        )
        texts = list(found or [])
    except Exception:  # noqa: BLE001
        pass
    return texts


def select_all_records(page) -> int:
    """勾选当页记录：优先 #choose-all（首页实测存在），退回"全选"文本，退回列表内复选框。"""
    for attempt in ("#choose-all", None):
        try:
            if attempt:
                loc = page.locator("#choose-all")
            else:
                loc = page.get_by_text(re.compile(r"^\s*全选\s*$"))
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=5000)  # 用 click 而非 check：全选常非真实 checkbox
                page.wait_for_timeout(800)
                checked = page.evaluate("() => document.querySelectorAll('input[type=checkbox]:checked').length")
                print(f"  [UI] 已勾选（{attempt or '全选文本'}），复选框选中 {checked} 个")
                return int(checked)
        except Exception:  # noqa: BLE001
            continue
    try:
        n = page.evaluate(
            """() => {
                const boxes = [...document.querySelectorAll('input[type=checkbox]')]
                    .filter(b => b.offsetParent !== null);
                let k = 0;
                for (const b of boxes) { if (!b.checked) { b.click(); k++; } if (k >= 60) break; }
                return k;
            }"""
        )
        print(f"  [UI] 勾选框逐个点选 {n} 个（未找到全选控件）")
        return int(n or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"  [UI] 勾选出错：{exc}")
        return 0


def _fmt_patterns(fmt: str) -> list[re.Pattern]:
    if fmt == "word":
        return list(_WORD_PATTERNS)
    if fmt == "pdf":
        return list(_PDF_PATTERNS)
    return _WORD_PATTERNS + _PDF_PATTERNS


_OPENER_PATTERNS = [re.compile(r"^\s*下载\s*$"), re.compile(r"批量下载|下载选中")]
_TAIL_PATTERNS = [re.compile(r"^\s*导出\s*$"), re.compile(r"^\s*(TXT|文本)\s*$")]


def _visible_clicks(page, pat, *, limit: int = 6) -> list:
    """pattern 的可见元素列表（防御式；找不到/不可见都静默）。"""
    try:
        loc = page.get_by_text(pat)
    except Exception:  # noqa: BLE001
        return []
    els = []
    for i in range(min(loc.count(), limit)):
        try:
            el = loc.nth(i)
            if el.is_visible():
                els.append(el)
        except Exception:  # noqa: BLE001
            continue
    return els


def _distinct_clicks(page, pat, *, limit: int = 6) -> list:
    """同 _visible_clicks，但按包围盒去重（实测菜单项常有嵌套同名节点，重复点击会各空等一轮）。"""
    els = _visible_clicks(page, pat, limit=limit)
    if len(els) <= 1:
        return els
    boxes: set = set()
    out: list = []
    for el in els:
        try:
            bb = el.bounding_box()
        except Exception:  # noqa: BLE001
            bb = None
        key = (round(bb["x"]), round(bb["y"]), round(bb["width"]), round(bb["height"])) \
            if bb else None
        if key is not None and key in boxes:
            continue
        if key is not None:
            boxes.add(key)
        out.append(el)
    return out


def _prefer_tail(els: list) -> list:
    """多元素时优先点**后一个**（实测 2026-10-16：详情页同名元素成对出现时，第一个常是
    死元素、第二个才是真下载入口；先点后者可省一轮短探）。纯函数，便于单测。"""
    if len(els) >= 2:
        return els[1:] + els[:1]
    return els


def _ordered_candidates(page, pat, *, limit: int = 6) -> list:
    return _prefer_tail(_distinct_clicks(page, pat, limit=limit))


def _wait_for_file(page, sink: DownloadSink, before: int, timeout_s: float) -> bool:
    for _ in range(int(timeout_s * 2)):
        page.wait_for_timeout(500)
        if sink.count() > before:
            return True
    return False


def click_download(page, sink: DownloadSink, *, wait_s: int = 20, fmt: str = "auto",
                   menu_wait_s: float = 4.0, probe_wait_s: float = 3.0,
                   grace_s: float = 15.0, budget_s: float = 20.0) -> bool:
    """点击"下载"直到收到文件；菜单项按 fmt 偏好（auto=Word 优先回退 PDF）。

    实测修正轨迹（2026-10-16，分步计时定位）：
    ① 旧逻辑对**每次点击空等满 25s** → 详情页两个"下载"展开器各白等 25s（download_s 恒 55–57s）；
    ② 展开器短等后仍 ~28s：**[计时] 显示格式项也先撞到一个"死元素"（点了不出文件）再撞真元素**，
       而真元素点击后 **0.5s 文件即到**（导出本身极快，n≈14 全部 ≤1s）。
    现逻辑：展开器只点一次短等；格式/兜底点击一律**短探 probe_wait_s 秒 → 没文件立刻换下一个元素**；
    全部试完仍无文件才做一次 grace_s 宽限（慢导出兜底）。probe_wait_s=3s 对实测 0.5s 留 6 倍余量
    （2026-10-16 晚从 6s 收紧；再往下压需活体证据支持）。每步打 [计时] 供效率分析。
    """
    import time as _t

    before = sink.count()
    deadline = _t.monotonic() + budget_s  # 总预算：防"每个候选都点一遍仍无文件"的病态件拖长（实测 47s→预算 20s）

    def _click(el, tag: str, wait: float) -> bool:
        if _t.monotonic() >= deadline:
            print(f"  [计时] {tag}: 预算用尽，跳过")
            return False
        tc = _t.monotonic()
        try:
            el.click(timeout=5000)
        except Exception:  # noqa: BLE001
            return False
        click_s = _t.monotonic() - tc
        w0 = _t.monotonic()
        got = _wait_for_file(page, sink, before, min(wait, max(0.5, deadline - _t.monotonic())))
        print(f"  [计时] {tag}: click={click_s:.1f}s wait={_t.monotonic() - w0:.1f}s got={got}")
        return got

    cands = report_candidates(page)
    print(f"  [UI] 页面上的下载类按钮候选：{cands or '（未识别到）'}")
    fmts = _fmt_patterns(fmt)

    # ① 格式项已可见（菜单本来就开着）→ 短探；多元素先点后一个（实测后者常是真入口）
    for pat in fmts:
        for el in _ordered_candidates(page, pat):
            if _click(el, f"格式①{pat.pattern[:12]}", probe_wait_s):
                return True
    # ② 展开菜单：只点第一个可见的"下载"，短等（菜单出现即走，不等满）
    for pat in _OPENER_PATTERNS:
        els = _distinct_clicks(page, pat, limit=2)
        if not els:
            continue
        if _click(els[0], "展开", menu_wait_s):
            return True
        break  # 只试一个展开器一次（旧逻辑在这里空等 25s×按钮数）
    # ③ 菜单已开 → 逐个格式项短探（auto 时 Word 死元素/无响应自动轮到 PDF）
    for pat in fmts:
        for el in _ordered_candidates(page, pat):
            if _click(el, f"格式③{pat.pattern[:12]}", probe_wait_s):
                return True
    # ④ 兜底：导出 / TXT（短探）
    for pat in _TAIL_PATTERNS:
        for el in _ordered_candidates(page, pat):
            if _click(el, f"兜底{pat.pattern[:12]}", probe_wait_s):
                return True
    # ⑤ 宽限：所有点击都没文件——等一次长超时（慢导出兜底；预算内才等）
    if _t.monotonic() < deadline:
        w0 = _t.monotonic()
        got = _wait_for_file(page, sink, before, min(grace_s, max(0.5, deadline - _t.monotonic())))
        print(f"  [计时] 宽限: wait={_t.monotonic() - w0:.1f}s got={got}")
        return got
    return False


def manual_capture(session, sink: DownloadSink, *, prompt: str, timeout_s: int = 600,
                   extra_s: int = 8) -> int:
    """人工兜底：页面铺好后由你点下载，文件由监听器自动保存。

    收到第一个文件后再多等 extra_s 秒，把同一批的其余文件也收齐。
    """
    before = sink.count()
    print(f"\n[人工下载] {prompt}")
    print(f"  文件会自动保存到：{sink.out_dir}")
    waited = 0
    while waited < timeout_s and sink.count() == before:
        session.page.wait_for_timeout(1000)
        waited += 1
    if sink.count() == before:
        print("  超时仍未收到文件。")
        return 0
    for _ in range(extra_s):
        session.page.wait_for_timeout(1000)
    got = sink.count() - before
    print(f"  本批收到 {got} 个文件。")
    return got


def next_page(page) -> bool:
    try:
        loc = page.get_by_text(NEXT_PAGE_TEXT)
        for i in range(min(loc.count(), 8)):
            el = loc.nth(i)
            if el.is_visible():
                el.click(timeout=5000)
                page.wait_for_timeout(2500)
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


# ---------------- 三种入口 ----------------
def download_run(session, run_dir: Path, out_dir: Path, *, cap: int = 50,
                 min_interval_s: float = 2.0, manual: bool = False,
                 fmt: str = "auto", skip_downloaded: bool = True) -> dict:
    """入口 1：对 results.jsonl 逐条开详情页 → 点下载。"""
    from pkulaw_agent.api import Pacer
    from pkulaw_agent.search import iter_results

    sink = DownloadSink(session.context, out_dir)
    pacer = Pacer(min_interval_s)
    done_file = out_dir / "downloaded.jsonl"
    done: set[str] = set()
    if skip_downloaded and done_file.exists():
        for line in done_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line).get("gid", ""))
    records = [r for r in iter_results(run_dir) if r.get("gid") not in done]
    log = done_file.open("a", encoding="utf-8")
    got = 0
    for i, rec in enumerate(records, 1):
        if got >= cap:
            print(f"  达到本次上限 {cap}，停止（配额红线；改 --cap 后再跑会续下）")
            break
        url = rec.get("url") or ""
        if url.startswith("/"):
            url = BASE + url
        if not url:
            continue
        pacer.wait(session.page)
        print(f"  [{i}] {rec.get('doc_no') or rec.get('title') or rec.get('gid')}")
        try:
            session.page.goto(url, wait_until="commit", timeout=120_000)
            session.page.wait_for_timeout(3000)
        except Exception as exc:  # noqa: BLE001
            print(f"    打开失败：{exc}")
            continue
        before = sink.count()
        ok = click_download(session.page, sink, wait_s=25, fmt=fmt)
        if not ok and manual:
            before = sink.count()
            manual_capture(session, sink, prompt=f"请手动点开这条记录下方的下载按钮（{url}）", timeout_s=180)
            ok = sink.count() > before
        log.write(json.dumps({"gid": rec.get("gid"), "url": url, "ok": bool(ok),
                              "files": sink.count() - before}, ensure_ascii=False) + "\n")
        log.flush()
        got += 1 if ok else 0
        if not ok:
            print("    ✗ 自动点下载没收到文件（已把候选按钮列在上面）——可加 --manual 兜底")
    log.close()
    sink.write_manifest(out_dir / "downloads.json")
    sink.stop()
    summary = {"requested": len(records), "downloaded": sink.count(), "files": sink.saved}
    print(f"✓ 下载总结：收到 {sink.count()} 个文件 → {out_dir}")
    return summary


def download_results_page(session, url: str, out_dir: Path, *, pages: int = 1,
                          cap: int = 50, manual: bool = False, fmt: str = "auto") -> dict:
    """入口 2/3：打开（或先在库页检索出的）结果页 → 勾选 → 下载；可翻页。"""
    sink = DownloadSink(session.context, out_dir)
    session.page.goto(url if url.startswith("http") else BASE + url,
                      wait_until="commit", timeout=120_000)
    for _ in range(5):
        session.page.wait_for_timeout(1000)
    for page_no in range(1, pages + 1):
        print(f"  [第 {page_no} 页]")
        n = select_all_records(session.page)
        if n == 0 and not manual:
            print("    ✗ 没勾选到记录——用 --manual 兜底或检查页面")
            break
        before = sink.count()
        ok = click_download(session.page, sink, wait_s=30, fmt=fmt)
        if not ok and manual:
            manual_capture(session, sink,
                           prompt="请手动点【下载】（勾选保持不动），文件会自动收下", timeout_s=300)
            ok = sink.count() > before
        if sink.count() >= cap:
            print(f"  达到本次上限 {cap}，停止")
            break
        if not ok:
            print("    ✗ 本页未收到文件")
        if page_no < pages and not next_page(session.page):
            print("  未找到下一页控件，停止翻页")
            break
    sink.write_manifest(out_dir / "downloads.json")
    sink.stop()
    summary = {"page_url": url, "downloaded": sink.count(), "files": sink.saved}
    print(f"✓ 下载总结：收到 {sink.count()} 个文件 → {out_dir}")
    return summary
