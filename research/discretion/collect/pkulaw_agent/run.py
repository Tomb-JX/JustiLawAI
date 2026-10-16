"""run：作业单 → 开详情 → 抓正文 → 六项校验 → （通过才）限额下载 → 断点/报告。

设计见 pkulaw-agent-design.md §10.4–10.5。要点：
- 一切正文读取零配额；只有"六校验通过"的件才点下载；`--cap` 强制本次上限；
- 逐件状态写 run.jsonl（追加即刷盘），`--resume` 跳过已完成，`--force` 全重做；
- 遇安全验证页（SecurityChallenge）立即停整批（红线），已完成的件保留；
- 产物：fetch/docs/*.txt（全部抓到的正文）、downloads/（通过件的原件）、
  run.jsonl、run_report.md、run.json —— 可直接接 import_manual → ingest 链。
"""

from __future__ import annotations

import csv as _csv
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

COLLECT_DIR = Path(__file__).resolve().parents[1]
if str(COLLECT_DIR) not in sys.path:
    sys.path.insert(0, str(COLLECT_DIR))

import pkulaw_ingest as ingest  # noqa: E402

from pkulaw_agent.api import Pacer  # noqa: E402
from pkulaw_agent.fetch import (doc_no_from_title, extract_detail_text, probe_text,  # noqa: E402
                                safe_filename, sha256_text, wait_for_doc)
from pkulaw_agent.session import BASE, SecurityChallenge  # noqa: E402
from pkulaw_agent.validators import parse_window, validate_article  # noqa: E402

TERMINAL = {"downloaded", "skipped", "validated"}
ALLOWED_SUFFIX = {".doc", ".docx", ".pdf", ".txt", ".wps", ".rtf"}


def _key_of(job: dict) -> str:
    return ingest.doc_no_norm(job.get("doc_no") or "") or str(job.get("url") or "")


class RunState:
    """逐件状态（run.jsonl，一行一件；put 即追加刷盘，可随时中断续跑）。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.rows: list[dict] = []
        self._index: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        r = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    self.rows.append(r)
                    k = _key_of(r)
                    if k:
                        self._index[k] = r

    def get(self, job: dict) -> dict | None:
        return self._index.get(_key_of(job))

    def put(self, rec: dict) -> None:
        self.rows.append(rec)
        k = _key_of(rec)
        if k:
            self._index[k] = rec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def seen_set(self) -> set[str]:
        """批内去重集合：正文哈希 + 规范化文号，**仅取终态行**（downloaded/skipped/validated）。

        修复（2026-10-16）：此前把 error 行也算进 seen，导致重试的件被自己上一轮的失败记录
        误判为"文号重复（本批）"而跳过。
        """
        seen: set[str] = set()
        for r in self.rows:
            if r.get("status") not in TERMINAL:
                continue
            if r.get("text_sha256"):
                seen.add(r["text_sha256"])
            k = _key_of(r)
            if k:
                seen.add(k)
        return seen


def load_manifest_ids(manifest_path: Path) -> set[str]:
    """台账里已入库的文号集合（取 title 等字段里的文号，DOC_NO_RE 与解析同源）。"""
    ids: set[str] = set()
    p = Path(manifest_path)
    if not p.exists():
        return ids
    with p.open(encoding="utf-8-sig", newline="") as f:
        for row in _csv.DictReader(f):
            blob = " ".join(str(v or "") for v in row.values())
            for m in ingest.DOC_NO_RE.finditer(blob):
                # 与 ingest 同规则：剥离正则可能吸附的前导括号
                ids.add(ingest.doc_no_norm(m.group(0).lstrip("（()").strip()))
    return ids


def verify_download(path: Path) -> tuple[bool, str]:
    """下载文件完整性：存在、非空、扩展名与魔数大致相符（html 误存等直接判失败）。"""
    p = Path(path)
    if not p.exists():
        return False, "文件不存在"
    size = p.stat().st_size
    if size <= 0:
        return False, "空文件"
    head = p.read_bytes()[:8]
    if p.suffix.lower() not in ALLOWED_SUFFIX:
        return False, f"扩展名 {p.suffix} 非文档"
    if head[:1] == b"<":
        return False, "内容像 HTML（未拿到真实文档）"
    return True, ""


def _reason_key(fails: list[str]) -> str:
    return fails[0].split(":", 1)[0] if fails else "unknown"


def run_jobs(session, jobs_path: Path, *, out_dir: Path | None = None, cap: int = 30,
             dry_run: bool = False, resume: bool = True, force: bool = False,
             min_interval: float = 2.0, window_spec: str = "", min_facts: int = 50,
             download_format: str = "auto",
             manifest_path: Path | None = None, logger=print) -> dict:
    jobs_path = Path(jobs_path)
    jobs = [json.loads(x) for x in
            jobs_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = Path(out_dir) if out_dir else jobs_path.parent
    docs_dir = out / "fetch" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    state = RunState(out / "run.jsonl")
    seen = state.seen_set()
    manifest_ids = load_manifest_ids(manifest_path or (COLLECT_DIR / "manifest.csv"))
    window = parse_window(window_spec)
    pacer = Pacer(min_interval)
    sink = None
    counters = {"candidates": len(jobs), "downloaded": 0, "validated": 0, "skipped": 0,
                "download_failed": 0, "errors": 0, "already_done": 0, "cap_remaining": 0}
    reasons: Counter = Counter()
    started = time.strftime("%Y-%m-%d %H:%M")
    in_sha = hashlib.sha256(jobs_path.read_bytes()).hexdigest()[:16]
    loop_t0 = time.monotonic()
    this_run: list[dict] = []  # 本次运行处理的件（计时统计只算这些）
    consec_errors = 0  # 连续失败计数（断路器：防窗口被关/被拦时空转扫完整个队列）
    progress_path = out / "progress.json"
    todo = sum(1 for j in jobs
               if not (resume and not force
                       and (state.get(j) or {}).get("status") in TERMINAL))

    def _progress(force_log: bool = False) -> None:
        """实时进度（v1.2）：每件写 progress.json；每 10 件打一行进度+ETA（配合行缓冲即看即报）。"""
        done = len(this_run)
        if done == 0:
            return
        elapsed = time.monotonic() - loop_t0
        rate = done / elapsed if elapsed else 0.0
        eta_min = round((todo - done) / rate / 60, 1) if rate else None
        try:
            progress_path.write_text(json.dumps({
                "updated": time.strftime("%H:%M:%S"), "done": done, "todo": todo,
                "downloaded": counters["downloaded"], "skipped": counters["skipped"],
                "errors": counters["errors"], "download_failed": counters["download_failed"],
                "last": (this_run[-1].get("doc_no") or this_run[-1].get("url") or "")[:40],
                "last_status": this_run[-1].get("status") or "",
                "elapsed_s": round(elapsed), "items_per_min": round(rate * 60, 1),
                "eta_min": eta_min}, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001 —— 进度文件是辅助手段，失败不中断
            pass
        if force_log or done % 10 == 0:
            eta_txt = f"，预计剩余 {eta_min} 分" if eta_min is not None else ""
            logger(f"[进度] {done}/{todo} 下载{counters['downloaded']} 跳过{counters['skipped']} "
                   f"错{counters['errors']} 速度 {rate * 60:.1f} 件/分{eta_txt}")

    for i, job in enumerate(jobs, 1):
        if resume and not force:
            prev = state.get(job)
            if prev and prev.get("status") in TERMINAL:
                counters["already_done"] += 1
                continue
        if not dry_run and counters["downloaded"] >= cap:
            counters["cap_remaining"] = len(jobs) - i + 1
            logger(f"▣ 达到 --cap {cap}：剩余 {counters['cap_remaining']} 件留待续跑（--resume）")
            break
        url = str(job.get("url") or "")
        if url.startswith("/"):
            url = BASE + url
        rec = {"doc_no": job.get("doc_no") or "", "url": url,
               "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "opened"}
        logger(f"[{i}/{len(jobs)}] {job.get('doc_no') or url}")
        if not url:
            rec.update(status="skipped", reason="作业无链接")
            counters["skipped"] += 1
            reasons["no_url"] += 1
            this_run.append(rec)
            state.put(rec)
            _progress()
            continue
        # —— 打开详情页（零配额）——
        t0 = time.monotonic()
        t_open = t_fetch = t_valid = t_dl0 = t_dl1 = None
        text = ""
        try:
            session.page.goto(url, wait_until="commit", timeout=120_000)
            wait_for_doc(session.page)
            session._check_challenge()
            detail = extract_detail_text(session.page)
            text = detail.get("text") or ""
            t_open = time.monotonic()
        except SecurityChallenge:
            rec.update(status="error", reason="安全验证页：按红线停批，人工处理后续跑（--resume）",
                       timing={"item_s": round(time.monotonic() - t0, 1)})
            counters["errors"] += 1
            reasons["security"] += 1
            this_run.append(rec)
            state.put(rec)
            _progress()
            logger("  ⛔ 安全验证页：整批停止（不绕过；人工完成后 --resume 续跑）")
            break
        except Exception as exc:  # noqa: BLE001 —— 单件失败不拖垮批次
            closed = "TargetClosed" in type(exc).__name__ or "TargetClosed" in str(exc)
            rec.update(status="error",
                       reason=("浏览器窗口已被关闭（重新运行命令会自动新开窗口并 --resume 续跑）"
                               if closed else
                               f"打开失败：{type(exc).__name__}: {str(exc)[:150]}"),
                       timing={"item_s": round(time.monotonic() - t0, 1)})
            counters["errors"] += 1
            reasons["window_closed" if closed else "open_failed"] += 1
            this_run.append(rec)
            state.put(rec)
            _progress()
            consec_errors += 1
            if consec_errors >= 5:
                logger("⛔ 连续 5 件失败（窗口被关/被拦/会话失效）：批次停止。"
                       "处理后重跑 --resume 续跑。")
                counters["breaker_stopped"] = 1
                break
            continue
        if len(text) < 150:  # 实测有 269–284 字的合法简易处罚决定（2026-10-16），门槛从 300 下调；
                             # 真正的"未加载"页正文 <100；质量仍由六校验的 narrative/facts 把关
            rec.update(status="error", reason=f"正文过短（{len(text)} 字，可能未加载或被限制）",
                       timing={"open_s": round(t_open - t0, 1), "item_s": round(time.monotonic() - t0, 1)})
            counters["errors"] += 1
            reasons["too_short"] += 1
            this_run.append(rec)
            state.put(rec)
            _progress()
            consec_errors += 1
            if consec_errors >= 5:
                logger("⛔ 连续 5 件失败（窗口被关/被拦/会话失效）：批次停止。"
                       "处理后重跑 --resume 续跑。")
                counters["breaker_stopped"] = 1
                break
            continue

        probe = probe_text(text)
        if not probe.get("doc_no"):  # 标题兜底（实测标题含文号）
            probe["doc_no"] = doc_no_from_title(detail.get("title", ""))
        sha = sha256_text(text)
        rec.update({"source": detail.get("source", ""), "title": detail.get("title", "")[:100]})
        name = safe_filename(job.get("doc_no") or probe.get("pklaw_id") or f"job{i:04d}")
        txt_path = docs_dir / f"{name}.txt"
        txt_path.write_text(text, encoding="utf-8")
        t_fetch = time.monotonic()
        val = validate_article(job, text=text, probe=probe, text_sha=sha, window=window,
                               min_facts=min_facts, manifest_ids=manifest_ids, seen=seen)
        t_valid = time.monotonic()
        rec.update({"text_sha256": sha, "txt": str(txt_path), "form": probe.get("form"),
                    "facts_len": probe.get("facts_len", 0), "has_amount": probe.get("has_amount"),
                    "validate": val})
        seen.add(sha)
        if job.get("doc_no"):
            seen.add(ingest.doc_no_norm(job["doc_no"]))

        if not val["pass"]:
            rec["status"] = "skipped"
            rec["reason"] = "；".join(val["fails"])[:200]
            counters["skipped"] += 1
            reasons[_reason_key(val["fails"])] += 1
            logger(f"  ✗ 校验未过：{rec['reason']}")
        elif dry_run:
            rec["status"] = "validated"
            counters["validated"] += 1
            logger(f"  ✓ 六校验通过（dry-run 不下载）：{probe.get('form')}，"
                   f"事实段 {probe.get('facts_len', 0)} 字")
        else:
            if sink is None:
                from pkulaw_agent.download import DownloadSink
                sink = DownloadSink(session.context, out / "downloads")
            before = sink.count()
            ok = False
            t_dl0 = time.monotonic()
            try:
                from pkulaw_agent.download import click_download
                ok = click_download(session.page, sink, wait_s=25, fmt=download_format)
            except Exception as exc:  # noqa: BLE001
                logger(f"  ✗ 下载动作异常：{exc}")
            t_dl1 = time.monotonic()
            files = sink.saved[before:]
            if ok and files:
                bad = [f"{Path(x['file']).name}:{n}" for x in files
                       for good, n in [verify_download(Path(x["file"]))] if not good]
                if bad:
                    rec.update(status="error",
                               reason="下载文件校验失败：" + "；".join(bad)[:150],
                               files=[x["file"] for x in files])
                    counters["errors"] += 1
                    reasons["file_bad"] += 1
                else:
                    rec.update(status="downloaded", files=[x["file"] for x in files])
                    counters["downloaded"] += 1
                    logger(f"  ⬇ 已下载：{', '.join(Path(x['file']).name for x in files)}")
            else:
                rec.update(status="error",
                           reason="点下载未收到文件（可在窗口中人工点一次下载后重跑 --resume）")
                counters["download_failed"] += 1
                reasons["download_failed"] += 1
                logger("  ✗ 自动点下载未收到文件")
        rec["timing"] = {
            "open_s": round(t_open - t0, 1) if t_open else None,
            "fetch_s": round(t_fetch - t_open, 1) if (t_fetch and t_open) else None,
            "validate_s": round(t_valid - t_fetch, 1) if (t_valid and t_fetch) else None,
            "download_s": round(t_dl1 - t_dl0, 1) if (t_dl1 and t_dl0) else None,
            "item_s": round(time.monotonic() - t0, 1),
        }
        this_run.append(rec)
        state.put(rec)
        _progress()
        if rec.get("status") == "error":
            consec_errors += 1
            if consec_errors >= 5:
                logger("⛔ 连续 5 件失败（窗口被关/被拦/会话失效）：批次停止。"
                       "处理后重跑 --resume 续跑。")
                counters["breaker_stopped"] = 1
                break
        else:
            consec_errors = 0

    elapsed = time.monotonic() - loop_t0
    item_times = [r["timing"]["item_s"] for r in this_run
                  if isinstance(r.get("timing"), dict) and r["timing"].get("item_s")]
    dl_times = [r["timing"]["download_s"] for r in this_run
                if isinstance(r.get("timing"), dict) and r["timing"].get("download_s")]
    open_times = [r["timing"]["open_s"] for r in this_run
                  if isinstance(r.get("timing"), dict) and r["timing"].get("open_s")]

    def _avg(xs):  # noqa: ANN001, ANN202
        return round(sum(xs) / len(xs), 1) if xs else None

    def _median(xs):  # noqa: ANN001, ANN202
        return round(statistics.median(xs), 1) if xs else None

    def _p90(xs):  # noqa: ANN001, ANN202
        return round(sorted(xs)[min(len(xs) - 1, int(len(xs) * 0.9))], 1) if xs else None

    efficiency = {"elapsed_s": round(elapsed), "processed": len(this_run),
                  "item_s_avg": _avg(item_times), "item_s_median": _median(item_times),
                  "item_s_p90": _p90(item_times), "open_s_avg": _avg(open_times),
                  "download_s_avg": _avg(dl_times), "downloads": len(dl_times),
                  "items_per_min": round(len(this_run) / elapsed * 60, 2) if elapsed else None,
                  "downs_per_10min": round(len(dl_times) / elapsed * 600, 2) if elapsed else None}
    summary = {"mode": "dry-run" if dry_run else f"download(cap={cap},fmt={download_format})",
               "jobs": str(jobs_path), "out": str(out), "input_sha256_16": in_sha,
               "window": window_spec or "", "min_facts": min_facts,
               "download_format": download_format,
               "started": started, "finished": time.strftime("%Y-%m-%d %H:%M"),
               "counters": counters, "reasons": dict(reasons), "efficiency": efficiency}
    if sink is not None:
        sink.write_manifest(out / "downloads" / "downloads.json")
        sink.stop()
    _write_report(out, summary, state)
    logger(f"■ 完成：{counters}")
    logger(f"  报告 → {out / 'run_report.md'}")
    return summary


def _write_report(out: Path, summary: dict, state: RunState) -> None:
    counters, reasons = summary["counters"], summary["reasons"]
    lines = [
        "# pkulaw_agent run 报告", "",
        f"- 作业单：`{summary['jobs']}`（sha256:{summary['input_sha256_16']}）",
        f"- 输出目录：`{summary['out']}`",
        f"- 时间：{summary['started']} → {summary['finished']}；模式：{summary['mode']}",
        f"- 窗口：{summary['window'] or '不限'}；事实段下限：{summary['min_facts']} 字", "",
        "## 计数", "",
        "| 项 | 数 |", "|---|---|",
        f"| 候选 | {counters['candidates']} |",
        f"| 下载完成 | {counters['downloaded']} |",
        f"| 校验通过（dry-run） | {counters['validated']} |",
        f"| 校验未过 | {counters['skipped']} |",
        f"| 下载失败 | {counters['download_failed']} |",
        f"| 打开/取文失败 | {counters['errors']} |",
        f"| 续跑跳过（已完成） | {counters['already_done']} |",
        f"| cap 停止（剩余） | {counters['cap_remaining']} |", "",
        "## 失败原因分布", "",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])] or ["- （无）"]
    eff = summary.get("efficiency") or {}
    if eff:
        lines += ["", "## 时间效率", "",
                  f"- 本次处理 {eff.get('processed')} 件，用时 {eff.get('elapsed_s')}s"
                  f"（{eff.get('items_per_min')} 件/分；下载 {eff.get('downloads')} 件，"
                  f"约 {eff.get('downs_per_10min')} 件/10 分）",
                  f"- 单件耗时：均 {eff.get('item_s_avg')}s / 中位 {eff.get('item_s_median')}s"
                  f" / p90 {eff.get('item_s_p90')}s",
                  f"- 打开页均 {eff.get('open_s_avg')}s；点下载+收文件均 {eff.get('download_s_avg')}s",
                  ""]
    lines += ["", "## 逐件", "", "| # | 文号 | 状态 | 耗时s | 原因/备注 |", "|---|---|---|---|---|"]
    for i, r in enumerate(state.rows, 1):
        note = r.get("reason") or "；".join((r.get("validate") or {}).get("fails") or []) \
            or f"{r.get('form', '')} 事实 {r.get('facts_len', '')} 字"
        t = (r.get("timing") or {}).get("item_s")
        lines.append(f"| {i} | {r.get('doc_no') or ''} | {r.get('status') or ''} | {t if t is not None else '-'} | {str(note)[:120]} |")
    (out / "run_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
