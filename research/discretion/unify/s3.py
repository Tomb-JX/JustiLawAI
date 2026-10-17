"""S3 校验层（parse-format-chain-design v1.2 §9 + 接口 v2 适配）：规则的新角色——确定性阻断校验。

seg-v2（句表分区）语义：模型输出 zones（句号区间）＋字段；覆盖/不重叠由"区间铺满句表"的
结构校验保证（s1.validate），本层把它作为断言复核；引文类检查随引文接口移除。

校验注册表：
- error：阻断 → 换旗舰重试一次 → 低置信队列
- warn：标记入库不阻断
罚幅对账（两级，Q6）：常量表 legal_caps.json（档次区间制展平）；第十六条合并上限硬约束；
条号-版本绑定（N6 类）。

版本注解不依赖模型（pilot 实测 76/89 未知）：law_version 定版归组装层（D8）。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "harvest"))
sys.path.insert(0, str(_HERE.parent / "discover"))

from s1 import validate as schema_validate, data_root  # noqa: E402
from locate import OffsetIndex  # noqa: E402
from parse import CONCLUSION_MARK  # noqa: E402
from parse_qc import CONCL_ANY, EVID_PAT, GENJV  # noqa: E402  与交付 QC 同源（指令 §3 迁移，单一注册表）

# 法定幅度：读引擎/协调层导出的常量表（协同指令 §4：$DATA/config/legal_caps.json，caps-v1 档次区间制），
# 展平为 {版本: {detention上限, fine上限, 条号}}；缺省内置 2012修正第七十条 口径。
BUILTIN_CAPS = {
    "2012修正": {"detention": 15, "fine": 3000, "article": "70"},
}
EDITION_KEY = {"psal-2012": "2012修正", "psal-2025": "2025修订"}


def _flatten_caps(raw: dict) -> dict:
    out = {}
    for law_key, law in (raw.get("laws") or {}).items():
        edition = EDITION_KEY.get(law_key, law_key)
        arts = law.get("gambling_articles") or {}
        det_max = fine_max = 0
        art_no = ""
        for no, art in arts.items():
            if "tiers" not in art:
                continue
            art_no = art_no or no
            for tier in (art.get("tiers") or {}).values():
                det_max = max(det_max, (tier.get("detention") or [0, 0])[1])
                fine_max = max(fine_max, (tier.get("fine") or [0, 0])[1])
        if det_max or fine_max:
            out[edition] = {"detention": det_max, "fine": fine_max, "article": art_no}
    return out


def _load_caps() -> dict:
    p = data_root() / "config" / "legal_caps.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            caps = _flatten_caps(raw)
            if caps:
                return caps
        except Exception:
            pass
    return dict(BUILTIN_CAPS)


try:
    PENALTY_CAPS = _load_caps()
except Exception:
    PENALTY_CAPS = dict(BUILTIN_CAPS)

EDITION_ARTICLE = {k: ("第七十条" if v["article"] == "70" else "第八十二条")
                   for k, v in PENALTY_CAPS.items() if v.get("article")}
ART16_DETENTION_MAX = 20   # 第十六条：合并执行拘留上限
HARD_OUTCOME = {"拘留", "拘留并处罚款", "罚款", "警告", "不予处罚", "不构成违法", "移送刑事"}


@dataclass
class Finding:
    check: str
    severity: str            # error | warn
    detail: str
    seg_types: list = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def _mk(check, severity, detail, seg_types=None):
    return Finding(check, severity, detail, seg_types or [])


# ---------- 区间工具（seg-v2） ----------

def zone_spans(output: dict, sentences: list, index: OffsetIndex | None) -> dict:
    """zones → {type: [(clean_start, clean_end, orig_start, orig_end), ...]}（原文坐标）。"""
    spans: dict[str, list] = {}
    for z in (output.get("zones") or []):
        typ, a, b = z.get("type"), z.get("from"), z.get("to")
        if typ not in ("facts", "evidence", "reasoning", "decision", "review"):
            continue   # meta 不进五段
        if not (isinstance(a, int) and isinstance(b, int) and 1 <= a <= b <= len(sentences)):
            continue
        cs = sentences[a - 1][0]
        ce = sentences[b - 1][1]
        os_, oe = (index.span(cs, ce) if index else (cs, ce))
        spans.setdefault(typ, []).append((cs, ce, os_, oe))
    return spans


def zone_text(spans_by_type: dict, cleaned: str, typ: str) -> str:
    """该类型的区间文本（cleaned 坐标拼接）。"""
    parts = [cleaned[cs:ce] for cs, ce, *_ in spans_by_type.get(typ, [])]
    return "".join(parts)


def check_zones_tiling(ctx):
    """铺满/不重叠断言（s1.validate 已校验，这里以句表坐标复核一遍——实现断言非阻断逻辑）。"""
    out, sentences = ctx["output"], ctx["sentences"]
    errs = schema_validate(out, n_sentences=len(sentences))
    return [_mk("zones_tiling", "error", e) for e in errs if "zone" in e or "铺满" in e or "连续" in e]


# ---------- 各校验器 ----------

def check_schema(ctx):
    errs = schema_validate(ctx["output"], n_sentences=len(ctx["sentences"]))
    return [_mk("schema", "error", e) for e in errs if "zone" not in e]


def check_decision_present(ctx):
    oc = (ctx["output"].get("outcome") or {})
    if oc.get("type") in HARD_OUTCOME:
        if not ctx["spans"].get("decision"):
            return [_mk("decision_present", "error", "outcome 有处罚结果但缺 decision 区间")]
    return []


def check_outcome_consistency(ctx):
    oc = ctx["output"].get("outcome") or {}
    t = oc.get("type")
    d, f = oc.get("detention_days") or 0, oc.get("fine") or 0
    if not isinstance(d, int) or not isinstance(f, (int, float)):
        return [_mk("outcome_consistency", "error", f"detention_days/fine 类型非法: {d!r}/{f!r}")]
    rules = {
        "拘留": d > 0 and f == 0,
        "拘留并处罚款": d > 0 and f > 0,
        "罚款": d == 0 and f > 0,
        "警告": d == 0 and f == 0,
        "不予处罚": d == 0 and f == 0,
        "不构成违法": d == 0 and f == 0,
        "移送刑事": True,
    }
    if t in rules and not rules[t]:
        return [_mk("outcome_consistency", "error", f"type={t} 与 detention_days={d}/fine={f} 不匹配")]
    return []


def check_penalty_caps(ctx):
    oc = ctx["output"].get("outcome") or {}
    d, f = oc.get("detention_days") or 0, oc.get("fine") or 0
    mv = bool(oc.get("multi_violation"))
    ex = oc.get("executed_penalty") or {}
    ed = ex.get("detention_days") or 0
    arts = oc.get("articles") or []
    edition = (arts[0].get("edition") if arts else "未知") or "未知"
    findings = []
    top = max(d, ed if mv else 0)
    if top > ART16_DETENTION_MAX:
        findings.append(_mk("penalty_caps", "error",
                            f"拘留 {top} 日超第十六条合并上限 {ART16_DETENTION_MAX} 日（edition={edition}, multi_violation={mv}）"))
        return findings
    if mv:
        if ed and ed > ART16_DETENTION_MAX:
            findings.append(_mk("penalty_caps", "error", f"executed_penalty 拘留 {ed} 日超合并上限 20 日"))
        if d > ed and ed:
            findings.append(_mk("penalty_caps", "warn", f"multi_violation=true 但单行为拘留 {d} > 合并 {ed}，复核拆项"))
        return findings
    caps = PENALTY_CAPS.get(edition)
    if caps is None:
        ref = PENALTY_CAPS.get("2012修正") or {}
        if d > ref.get("detention", 15) or f > ref.get("fine", 3000):
            findings.append(_mk("penalty_caps", "warn",
                                f"版本未知：拘留 {d}/罚款 {f} 超 2012 第七十条参考幅度（15日/3000元），待幅度库/证据核对"))
        return findings
    if d > caps["detention"]:
        findings.append(_mk("penalty_caps", "error",
                            f"拘留 {d} 日超 {edition} 单行为上限 {caps['detention']} 日"))
    if f > caps["fine"]:
        findings.append(_mk("penalty_caps", "error",
                            f"罚款 {f} 元超 {edition} 单行为上限 {caps['fine']} 元"))
    return findings


def check_article_edition(ctx):
    oc = ctx["output"].get("outcome") or {}
    arts = oc.get("articles") or []
    findings = []
    for a in arts:
        text = (a.get("text") or "") + (a.get("edition") or "")
        edition = a.get("edition") or "未知"
        if edition in EDITION_ARTICLE and EDITION_ARTICLE[edition] not in text \
                and any(n in text for n in ("第七十条", "第八十二条")):
            findings.append(_mk("article_edition", "error",
                                f"条号-版本错配：edition={edition} 应引 {EDITION_ARTICLE[edition]}"))
    return findings


def check_facts_quality(ctx):
    """facts 区间内容质量族（parse_qc 迁移）：定性句收尾（error，边界规则应已 snap——残留=模型越界）、
    段中定性（warn）、证据句/根据法条混入（warn）、截尾、<30 字（区间粒度下仍为内容质量信号）。"""
    cleaned = ctx["record"].get("cleaned_text") or ""
    facts = zone_text(ctx["spans"], cleaned, "facts").strip()
    st = ctx["record"].get("source_type") or ""
    findings = []
    if not facts:
        if st in ("处罚决定书", "执法公示"):
            findings.append(_mk("facts_quality", "error", "facts 区间缺失（决定书/公示形态应有事实）"))
        return findings
    if facts == cleaned.strip() and len(facts) > 120:
        findings.append(_mk("facts_quality", "error", "事实区间=全文（分区失败）"))
    sentences = [p for p in re.split(r"(?<=[。；;])", facts) if p.strip()]
    if sentences and CONCLUSION_MARK.search(sentences[-1]):
        findings.append(_mk("facts_quality", "error", f"定性句收尾（snap 未生效？）：…{sentences[-1][:24]}"))
    for s in sentences[:-1]:
        if CONCLUSION_MARK.search(s):
            findings.append(_mk("facts_quality", "warn", f"定性句段中：…{s[:24]}"))
            break
    m_any = CONCL_ANY.search(facts)
    if m_any and not any("定性句" in f.detail for f in findings):
        findings.append(_mk("facts_quality", "warn", "定性句段中（构成句式）"))
    if EVID_PAT.search(facts):
        findings.append(_mk("facts_quality", "warn", "证据句混入事实区间"))
    if GENJV.search(facts):
        findings.append(_mk("facts_quality", "warn", "事实区间含根据法条"))
    if 0 < len(facts) < 30:
        findings.append(_mk("facts_quality", "warn", "事实区间<30字"))
    return findings


def check_dates(ctx):
    out, rec = ctx["output"], ctx["record"]
    dates = out.get("dates") or {}
    b, dd = dates.get("behavior"), dates.get("decision")
    findings = []
    eb, ed2 = rec.get("behavior_date") or "", rec.get("decision_date") or ""
    if isinstance(b, str) and isinstance(dd, str) and len(b) >= 7 and len(dd) >= 7 and b[:7] > dd[:7]:
        findings.append(_mk("dates_order", "error", f"模型行为月 {b[:7]} 晚于决定月 {dd[:7]}"))
    if eb and ed2 and len(eb) >= 7 and len(ed2) >= 7 and eb[:7] > ed2[:7]:
        findings.append(_mk("dates_order", "error", f"信封行为月 {eb[:7]} 晚于决定月 {ed2[:7]}"))
    # 模型值 vs 信封粗值交叉（仅在有值且前缀可比时）
    if isinstance(b, str) and eb and len(b) >= 7 and len(eb) >= 7 and b[:7] != eb[:7]:
        findings.append(_mk("dates_order", "warn", f"模型行为月 {b[:7]} ≠ 信封 {eb[:7]}"))
    if isinstance(dd, str) and ed2 and len(dd) >= 7 and len(ed2) >= 7 and dd[:7] != ed2[:7]:
        findings.append(_mk("dates_order", "warn", f"模型决定月 {dd[:7]} ≠ 信封 {ed2[:7]}"))
    if b is None and dd is None and rec.get("source_type") != "执法公示":
        findings.append(_mk("dates_order", "warn", "模型未给出任何日期"))
    return findings


def check_subject(ctx):
    out, rec = ctx["output"], ctx["record"]
    subj = (out.get("subject") or {}).get("mention")
    if not subj:
        return []
    cleaned = rec.get("cleaned_text") or ""
    facts = zone_text(ctx["spans"], cleaned, "facts").strip()
    if facts and subj in facts:
        return []
    if subj in cleaned:
        return [_mk("subject", "warn", f"本人写法见于 decision/reasoning 等区间而非 facts（facts len={len(facts)}）")]
    return [_mk("subject", "error", f"本人写法在正文中未找到：{subj[:6]}…（疑幻觉）")]


def check_gambling_cross(ctx):
    gamb = (ctx["output"].get("gambling") or {}).get("verdict")
    pre = ctx["record"]["prefilter"]["gambling"]
    if pre == "是" and gamb == "否":
        return [_mk("gambling_cross", "warn",
                    f"预筛=是 但模型=否（reason={(ctx['output'].get('gambling') or {}).get('reason', '')[:40]}）")]
    if pre == "待定" and gamb == "待定":
        return [_mk("gambling_cross", "warn", "预筛与模型均为待定")]
    return []


CHECKS = [
    ("zones_tiling", check_zones_tiling),
    ("schema", check_schema),
    ("decision_present", check_decision_present),
    ("outcome_consistency", check_outcome_consistency),
    ("penalty_caps", check_penalty_caps),
    ("article_edition", check_article_edition),
    ("facts_quality", check_facts_quality),
    ("dates_order", check_dates),
    ("subject", check_subject),
    ("gambling_cross", check_gambling_cross),
]


def run_checks(ctx: dict) -> list[Finding]:
    findings: list[Finding] = []
    for _name, fn in CHECKS:
        findings.extend(fn(ctx))
    return findings
