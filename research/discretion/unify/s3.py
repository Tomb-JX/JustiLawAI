"""S3 校验层（parse-format-chain-design v1.2 §9）：规则的新角色——确定性阻断校验。

校验注册表（每条含严重级）：
- error：阻断 → 换旗舰重试一次 → 仍败进低置信队列（design §9 失败处置）
- warn：标记入库不阻断

罚幅对账（两级，Q6 最高优先 + 第十六条豁免）：
- 第一级 multi_violation=false：detention_days/fine 受所引法条单行为幅度约束
  （2012修正第七十条：拘留≤15日、罚款≤3000 元；2025修订幅度库未接——不裁决只提示）；
- 第二级 multi_violation=true 或合并执行：按第十六条合并上限（拘留≤20 日）裁决 executed_penalty；
- 未知版本按第一级口径走 warn（不硬拒），detention>20 一律 error（违反第十六条合并上限）。

版本注解不依赖模型（pilot 实测 76/89 未知）：law_version 定版归组装层（D8），本层只查
模型内部一致性与法定上限越限，不下 law_version 结论。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from s1 import validate as schema_validate
from locate import locate, OffsetIndex
from s1 import data_root

# 法定幅度：优先读引擎导出的常量表（协同指令 §4：$DATA/config/legal_caps.json），
# 缺省用内置 2012修正第七十条 口径；2025修订待常量表就位后由 warn 升级为硬对账
BUILTIN_CAPS = {
    "2012修正": {"detention": 15, "fine": 3000},
    "2025修订": None,   # 幅度库未接
}


def _load_caps() -> dict:
    p = data_root() / "config" / "legal_caps.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            caps = raw.get("caps") if isinstance(raw, dict) else raw
            if isinstance(caps, dict):
                return caps
        except Exception:
            pass
    return BUILTIN_CAPS


try:
    PENALTY_CAPS = _load_caps()
except Exception:
    PENALTY_CAPS = BUILTIN_CAPS

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


# ---------- 各校验器（ctx: unified 记录 + S1 输出 + 定位结果） ----------

def check_schema(ctx):
    errs = schema_validate(ctx["output"])
    return [_mk("schema", "error", e) for e in errs]


def check_quotes(ctx):
    """引文定位：fail=error（防幻觉硬防线）；exact_multi/ws_multi → 消歧，仍歧义=warn。"""
    out, locs = ctx["output"], ctx["locates"]
    findings = []
    for typ, loc in locs.items():
        if loc is None:
            continue
        if loc.status in ("fail", "empty"):
            findings.append(_mk("quote", "error", f"引文未命中（{loc.status}，len={loc.note or '-'}）", [typ]))
        elif loc.status in ("exact_multi", "ws_multi"):
            if not ctx.get("disambiguated", {}).get(typ):
                findings.append(_mk("quote", "warn", f"多处命中未消歧（{loc.occurrences} 处）", [typ]))
            else:
                findings.append(_mk("quote", "warn", "多处命中经消歧定位", [typ]))
        elif loc.status == "fuzzy_unique":
            findings.append(_mk("quote", "warn", f"模糊定位：{loc.note}", [typ]))
    return findings


def check_segments_overlap(ctx):
    """已唯一定位的段之间不得重叠（error）。"""
    locs = [loc for typ, loc in ctx["locates"].items()
            if loc is not None and loc.status in ("exact_unique", "ws_unique") and typ.startswith("seg:")]
    locs.sort(key=lambda l: l.clean_start)
    findings = []
    for a, b in zip(locs, locs[1:]):
        if b.clean_start < a.clean_end:
            findings.append(_mk("segments_overlap", "error",
                                f"段重叠：[{a.clean_start},{a.clean_end}) 与 [{b.clean_start},{b.clean_end})"))
    return findings


def check_decision_present(ctx):
    """有处罚结果的记录必须有 decision 段（error）。"""
    oc = (ctx["output"].get("outcome") or {})
    if oc.get("type") in HARD_OUTCOME:
        segs = {s.get("type") for s in (ctx["output"].get("segments") or [])}
        if "decision" not in segs:
            return [_mk("decision_present", "error", "outcome 有处罚结果但缺 decision 段")]
    return []


def check_outcome_consistency(ctx):
    """type ↔ detention_days ↔ fine 矩阵（error）。"""
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
        "移送刑事": True,   # 形态不定，不裁决
    }
    if t in rules and not rules[t]:
        return [_mk("outcome_consistency", "error", f"type={t} 与 detention_days={d}/fine={f} 不匹配")]
    return []


def check_penalty_caps(ctx):
    """两级罚幅对账（Q6）。"""
    oc = ctx["output"].get("outcome") or {}
    d, f = oc.get("detention_days") or 0, oc.get("fine") or 0
    mv = bool(oc.get("multi_violation"))
    ex = oc.get("executed_penalty") or {}
    ed, ef = ex.get("detention_days") or 0, ex.get("fine") or 0
    arts = oc.get("articles") or []
    edition = (arts[0].get("edition") if arts else "未知") or "未知"
    findings = []

    # 第十六条合并上限：任何情形拘留合计 >20 日都是硬越限
    top = max(d, ed if mv else 0)
    if top > ART16_DETENTION_MAX:
        findings.append(_mk("penalty_caps", "error",
                            f"拘留 {top} 日超第十六条合并上限 {ART16_DETENTION_MAX} 日（edition={edition}, multi_violation={mv}）"))
        return findings

    if mv:
        # 第二级：合并执行对账
        if ed and ed > ART16_DETENTION_MAX:
            findings.append(_mk("penalty_caps", "error", f"executed_penalty 拘留 {ed} 日超合并上限 20 日"))
        if d > ed and ed:
            findings.append(_mk("penalty_caps", "warn", f"multi_violation=true 但单行为拘留 {d} > 合并 {ed}，复核拆项"))
        return findings

    # 第一级：单行为幅度（仅 2012修正有明确幅度；未知版本走 warn 口径）
    caps = PENALTY_CAPS.get(edition)
    if caps is None:
        if edition == "2025修订":
            findings.append(_mk("penalty_caps", "warn", "2025修订幅度库未接，未对账"))
        elif d > 15 or f > 3000:
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


def check_dates(ctx):
    """日期顺序（error）+ 与信封粗日期交叉（warn）。"""
    out, rec = ctx["output"], ctx["record"]
    dates = out.get("dates") or {}
    b = (dates.get("behavior") or {}).get("quote")
    dd = (dates.get("decision") or {}).get("quote")
    # 模型只给引文不给值：顺序核对用信封粗日期（有则核）
    eb = rec.get("behavior_date") or ""
    ed2 = rec.get("decision_date") or ""
    findings = []
    if eb and ed2 and len(eb) >= 7 and len(ed2) >= 7 and eb[:7] > ed2[:7]:
        findings.append(_mk("dates_order", "error", f"信封行为月 {eb[:7]} 晚于决定月 {ed2[:7]}"))
    if b is None and dd is None and rec.get("source_type") != "执法公示":
        findings.append(_mk("dates_order", "warn", "模型未给出任何日期引文"))
    return findings


def check_subject(ctx):
    """本人写法核验（pilot 实测校准）：facts 引文→pass；正文其他位置（decision/evidence
    等段或正文本身）→ warn（facts 引文偏短未含人名是合法形态）；全文没有→ error（疑幻觉）。"""
    out, rec = ctx["output"], ctx["record"]
    subj = (out.get("subject") or {}).get("mention")
    if not subj:
        return []   # subject 缺失是召回问题，不在此阻断
    facts = [s.get("quote") or "" for s in (out.get("segments") or []) if s.get("type") == "facts"]
    if facts and any(subj in q for q in facts):
        return []
    if subj in rec.get("cleaned_text", ""):
        seg_hit = [s.get("type") for s in (out.get("segments") or [])
                   if s.get("type") != "facts" and subj in (s.get("quote") or "")]
        return [_mk("subject", "warn",
                    f"本人写法见于 {seg_hit or ['正文']} 而非 facts 引文（facts 引文 len="
                    f"{min((len(q) for q in facts), default=0)}）")]
    return [_mk("subject", "error", f"本人写法在正文中未找到：{subj[:6]}…（疑幻觉）")]


def check_gambling_cross(ctx):
    """模型 verdict 与预筛交叉（warn → 队列核对）。"""
    gamb = (ctx["output"].get("gambling") or {}).get("verdict")
    pre = ctx["record"]["prefilter"]["gambling"]
    if pre == "是" and gamb == "否":
        return [_mk("gambling_cross", "warn", f"预筛=是 但模型=否（reason={(ctx['output'].get('gambling') or {}).get('reason','')[:40]}）")]
    if pre == "待定" and gamb == "待定":
        return [_mk("gambling_cross", "warn", "预筛与模型均为待定")]
    return []


def check_coverage(ctx):
    """决策类文书主体覆盖 ≥95%（协同指令 §3c）：定位成功的段并集覆盖
    [首段起点, 末段终点] 区间的比例；引文整体过疏 → error。"""
    form = ctx["record"].get("form") or ""
    if not any(k in form for k in ("叙述式-独立成篇", "叙述式-复议")):
        return []   # 公示/结果栏等形态不按主体覆盖裁决
    spans = []
    for typ, loc in (ctx.get("locates") or {}).items():
        if typ.startswith("seg:") and loc is not None and loc.clean_end > loc.clean_start \
                and loc.status in ("exact_unique", "ws_unique"):
            spans.append((loc.clean_start, loc.clean_end))
    if len(spans) < 2:
        return []   # 单段无从谈覆盖；段缺失由 decision_present/quote 把关
    spans.sort()
    lo, hi = spans[0][0], spans[-1][1]
    total = hi - lo
    if total <= 0:
        return []
    covered = 0
    for a, b in spans:
        covered += b - a
    ratio = covered / total
    if ratio < 0.95:
        return [_mk("coverage", "error", f"五段并集覆盖主体 {ratio:.0%} < 95%（引文过疏或漏段）")]
    return []


CHECKS = [
    ("schema", check_schema),
    ("quotes", check_quotes),
    ("segments_overlap", check_segments_overlap),
    ("decision_present", check_decision_present),
    ("outcome_consistency", check_outcome_consistency),
    ("penalty_caps", check_penalty_caps),
    ("dates_order", check_dates),
    ("subject", check_subject),
    ("gambling_cross", check_gambling_cross),
    ("coverage", check_coverage),
]


def run_checks(ctx: dict) -> list[Finding]:
    findings: list[Finding] = []
    for _name, fn in CHECKS:
        findings.extend(fn(ctx))
    return findings


def collect_locates(output: dict, cleaned: str, index: OffsetIndex) -> dict:
    """对 segments + dates 引文逐条定位。键：seg:<type> / date:<k>。"""
    locs = {}
    for s in (output.get("segments") or []):
        typ = s.get("type") or "?"
        locs[f"seg:{typ}"] = locate(cleaned, s.get("quote") or "", index)
    dates = output.get("dates") or {}
    for k in ("behavior", "decision"):
        q = (dates.get(k) or {}).get("quote")
        if q:
            locs[f"date:{k}"] = locate(cleaned, q, index)
    return locs
