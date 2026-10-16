"""六项原文校验（纯函数，便于单测；设计见 pkulaw-agent-design.md §10.4）。

规则：
  1) doc_no    页面文号（归一化）与作业文号一致；
  2) gambling  赌博要素词命中，且非烟草/彩票类；
  3) year      处罚日期或正文年份落在配置窗口内（排除"2025修订"式法条版本字样）；
  4) narrative 形态为叙述式且事实段长度 ≥ 阈值；
  5) masked    金额/日期位没有 xx/＊/□ 式打码；
  6) dedupe    文号/正文哈希不与台账、本批重复。
全部为纯函数：输入文本与探针结果，输出 (ok, note)。调用方（run.py）负责取页面数据。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

COLLECT_DIR = Path(__file__).resolve().parents[1]
if str(COLLECT_DIR) not in sys.path:
    sys.path.insert(0, str(COLLECT_DIR))

import pkulaw_ingest as ingest  # noqa: E402 —— 文号规范化与拍平，与下游同源

# 赌博要素核心词（比解析层的 GAMBLING_MARK 略宽，含常见赌具/玩法）
GAMBLING_CORE = re.compile(
    r"赌博|参赌|赌资|赌具|抽头|渔利|赌场|麻将|扑克|骰子|牌九|炸金花|押宝|比鸡|老虎机|赌博机|六合彩")
TOBACCO_RE = re.compile(r"烟草|卷烟|烟叶|烟丝|香烟|专卖管理")
# 打码：连续掩码字符（ASCII * 常见于法宝源文，如"赌资****元""20**年**月**日"；
# x/×/＊/□ 为变体）后跟金额或日期单位；单个 × 紧随年月日也认。
# 注意：姓名的"张**"、条号的"第**条"不触发（后随非单位字）。
MASK_TOKEN_RE = re.compile(r"(?:[xX×*]{2,}|[＊□\u25a1]{1,})\s*([元年月日])|×\s*([年月日])")
# 日期位豁免语境：出生日期与"之前无违法犯罪记录"式前科句——遮的是非关键要素（真实样本：
# 安陆 34 号只遮年龄/出生日期，行为日期与赌资完好，属可用件，不应拦）
MASK_EXCUSE = ("出生", "之前")
# 正文年份（排除"2025年修订/2012年修正"式版本字样——它出现在法条名里，不是案件年份）
YEAR_IN_TEXT = re.compile(r"(20\d{2})年(?!修订|修正)")


def check_doc_no(page_doc_no: str, job_doc_no: str) -> tuple[bool, str]:
    a, b = ingest.doc_no_norm(page_doc_no or ""), ingest.doc_no_norm(job_doc_no or "")
    if not b:
        return True, "作业无文号（跳过比对）"
    if not a:
        return False, "页面未取到文号"
    if a == b or b in a or a in b:
        return True, ""
    return False, f"文号不一致（页面={a} 作业={b}）"


def check_gambling(text: str) -> tuple[bool, str]:
    flat = ingest.flatten(text)
    if GAMBLING_CORE.search(flat):
        return True, ""
    if TOBACCO_RE.search(flat):
        return False, "烟草类（非赌博）"
    return False, "未见赌博要素词"


def check_year(job: dict, text: str, window: tuple[int, int] | None) -> tuple[bool, str]:
    """window=(起始年, 结束年)，None 表示不限。处罚日期或正文明文年份任一命中即通过。"""
    if not window:
        return True, ""
    start, end = window
    hits: list[str] = []
    m = re.search(r"(20\d{2})", str(job.get("punishment_date") or ""))
    if m and start <= int(m.group(1)) <= end:
        hits.append(f"处罚{m.group(1)}")
    for y in sorted(set(YEAR_IN_TEXT.findall(ingest.flatten(text)))):
        if start <= int(y) <= end:
            hits.append(f"正文{y}")
    if hits:
        return True, "；".join(dict.fromkeys(hits))
    return False, f"年份不在窗内（{start}-{end}）"


def check_narrative(probe: dict, min_facts: int = 50) -> tuple[bool, str]:
    if probe.get("form") != "narrative":
        return False, f"形态={probe.get('form') or '未知'}"
    fl = int(probe.get("facts_len") or 0)
    if fl < min_facts:
        return False, f"事实段仅 {fl} 字"
    return True, ""


def check_masked(text: str) -> tuple[bool, str]:
    """金额位打码一律拦；日期位打码仅当不是"出生/前科记录"语境时拦（那两类遮的不是关键要素）。"""
    flat = ingest.flatten(text)
    hits: list[str] = []
    for m in MASK_TOKEN_RE.finditer(flat):
        unit = m.group(1) or m.group(2) or ""
        if unit in "年月日":
            window = flat[m.end():m.end() + 12]
            if any(w in window for w in MASK_EXCUSE):
                continue
        hits.append(m.group(0))
    if hits:
        return False, f"疑似打码：{hits[0][:12]}（共{len(hits)}处）"
    return True, ""


def check_dedupe(doc_no: str, text_sha: str, *, manifest_ids: set[str],
                 seen: set[str]) -> tuple[bool, str]:
    b = ingest.doc_no_norm(doc_no or "")
    if b and b in manifest_ids:
        return False, "台账已入库"
    if text_sha and text_sha in seen:
        return False, "正文重复（本批）"
    if b and b in seen:
        return False, "文号重复（本批）"
    return True, ""


def parse_window(spec: str) -> tuple[int, int] | None:
    """'2026' → (2026,2026)；'2025-07:2026' → (2025,2026)；空串 → None。"""
    years = [int(y) for y in re.findall(r"20\d{2}", spec or "")]
    if not years:
        return None
    return (min(years), max(years))


def validate_article(job: dict, *, text: str, probe: dict, text_sha: str = "",
                     window: tuple[int, int] | None = None, min_facts: int = 50,
                     manifest_ids: set[str] | None = None,
                     seen: set[str] | None = None) -> dict:
    """六项校验汇总。返回 {pass, fails:[…], checks:{名:{ok,note}}}，fails 为空即通过。"""
    checks = [
        ("doc_no", *check_doc_no(probe.get("doc_no") or "", job.get("doc_no") or "")),
        ("gambling", *check_gambling(text)),
        ("year", *check_year(job, text, window)),
        ("narrative", *check_narrative(probe, min_facts)),
        ("masked", *check_masked(text)),
        ("dedupe", *check_dedupe(job.get("doc_no") or "", text_sha,
                                 manifest_ids=manifest_ids or set(), seen=seen or set())),
    ]
    fails = [f"{name}:{note}" for name, ok, note in checks if not ok]
    return {"pass": not fails, "fails": fails,
            "checks": {name: {"ok": bool(ok), "note": note} for name, ok, note in checks}}
