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
from zoning import is_public_form  # noqa: E402
from parse import cn2int  # noqa: E402  中文数字互转（值-文对账用）

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
    """decision 区间要求按形态分治：叙述式=error；公示族（条目为"事实＋处罚"融合摘要，
    无独立决定句）降为 warn——处罚信息以 outcome 字段为准。复议有 review 区间时同样放宽。"""
    oc = (ctx["output"].get("outcome") or {})
    if oc.get("type") not in HARD_OUTCOME:
        return []
    if ctx["spans"].get("decision"):
        return []
    form = ctx["record"].get("form") or ""
    if is_public_form(form):
        return [_mk("decision_present", "warn", "公示族融合条目无独立 decision 句（处罚在 outcome 字段）")]
    if ctx["spans"].get("review"):
        return [_mk("decision_present", "warn", "复议文书：结论在 review 区间，无独立 decision")]
    return [_mk("decision_present", "error", "outcome 有处罚结果但缺 decision 区间")]


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
        # 遮蔽金额豁免：正文含"＊＊元"类遮蔽且未填 fine_masked——warn 不 error（值不可知非矛盾）
        cleaned = ctx["record"].get("cleaned_text") or ""
        if t in ("罚款", "拘留并处罚款") and (oc.get("fine") or 0) == 0 \
                and re.search(r"[＊*xX×]{2,}\s*元", cleaned):
            return [_mk("outcome_consistency", "warn",
                        f"type={t} 金额被发布方遮蔽（应标 fine_masked）：与 fine=0 不算矛盾")]
        # 幅度句豁免："7.6万元以上10万元以下"无单值可填——模型填 0 是正确保守，warn 提示标注幅度
        if t in ("罚款", "拘留并处罚款") and (oc.get("fine") or 0) == 0 \
                and re.search(r"万元以上[^。]{0,12}以下|[0-9.万]{1,8}元以上", cleaned):
            return [_mk("outcome_consistency", "warn",
                        f"type={t} 正文为罚款幅度（无单值），fine=0 待幅度标注")]
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
    """facts 区间内容质量族（parse_qc 迁移），按形态分治：
    - 叙述式（决定书/复议）：定性句收尾 = error（M1 输入不得含答案）；事实区间=全文 = error（分区失败）；
    - 公示族（字段表/标题汇总/混合）：条目是"事实＋定性"融合的压缩摘要——定性收尾降 warn、
      区间=全文为固有形态（整条目即事实），均不阻断（facts_contains_conclusion 旗标承担引擎豁免）；
    结构检查（缺失/=<30字/=全文）对所有形态一致。"""
    cleaned = ctx["record"].get("cleaned_text") or ""
    form = ctx["record"].get("form") or ""
    narrative = not is_public_form(form)
    facts = zone_text(ctx["spans"], cleaned, "facts").strip()
    st = ctx["record"].get("source_type") or ""
    findings = []
    if not facts:
        if st in ("处罚决定书", "执法公示"):
            findings.append(_mk("facts_quality", "error", "facts 区间缺失（决定书/公示形态应有事实）"))
        return findings
    if narrative and facts == cleaned.strip() and len(facts) > 120:
        findings.append(_mk("facts_quality", "error", "事实区间=全文（分区失败）"))
    sentences = [p for p in re.split(r"(?<=[。；;])", facts) if p.strip()]
    tail_sev = "error" if narrative else "warn"
    if sentences and CONCLUSION_MARK.search(sentences[-1]):
        findings.append(_mk("facts_quality", tail_sev,
                            f"定性句收尾：…{sentences[-1][:24]}" + ("" if narrative else "（公示族融合语义，降 warn）")))
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


# ---------- 值-文对账（仔细校验层：v2 接口补回 v1 引文锚定的值级 grounding） ----------

_CN_DIG = {"零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
           "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}


def _CN_READ(v: int) -> str:
    """整数 → 中文小写读法（保留；值对账已改反向解析，不再依赖正向生成）。"""
    if v < 0 or v > 9999:
        return ""
    CN = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
    U = ["", "十", "百", "千"]
    s = str(v)
    parts = []
    n = len(s)
    zero_pending = False
    for i, ch in enumerate(s):
        d = int(ch)
        u = U[n - 1 - i]
        if d == 0:
            if parts:
                zero_pending = True
            continue
        if zero_pending:
            parts.append("零")
            zero_pending = False
        if d == 1 and u == "十" and not parts:
            parts.append("十")
        else:
            parts.append(CN[d] + u)
    return "".join(parts) or "零"


# 金额/天数**反向解析**：正文的"数字+元/日"用 cn2int 解析成数值集合（认阿拉伯、
# 小写、大写、千分位、混合书写"三佰"），再查模型值成员——正向生成读法会漏大写形态
# （贰佰肆拾元=240），ds300 实测曾把 52/68 件大写金额误判幻觉，教训在此。
_NUM_CHARS = "0-9０-９〇零○一二三四五六七八九十百千万萬亿佰仟拾两壹贰貳叁參肆伍陆陸柒捌玖拾"
_AMOUNT = re.compile(rf"([{_NUM_CHARS}]{{1,16}})[ \t]*元")
# 字段表公示的金额列常无"元"单位（"罚款金额：300"）——标签+纯数字模式
_LABEL_AMOUNT = re.compile(r"(?:金额|罚款)[：:]?\s*(\d{1,10})(?![\d.])")
_DAYS = re.compile(rf"([{_NUM_CHARS}]{{1,8}})[ \t]*(?:日|天)")


def _text_numbers(text: str, kind: str) -> set[int]:
    """正文中 数字+元/日天 的全部数值集合（千分位归一；cn2int 同源 parse.py；
    金额另含"金额/罚款：数字"标签模式——字段表公示常见）。"""
    t = re.sub(r"(?<=[0-9０-９])[,，](?=[0-9０-９])", "", text or "")
    out = set()
    pat = _AMOUNT if kind == "元" else _DAYS
    for m in pat.finditer(t):
        v = cn2int(m.group(1))
        if v is not None:
            out.add(int(v))
    if kind == "元":
        for m in _LABEL_AMOUNT.finditer(t):
            out.add(int(m.group(1)))
    return out


def check_value_grounded(ctx):
    """值-文对账（仔细校验核心件）：模型字段值必须能在正文找到对应数值/条文——
    反向解析（正文金额/天数集合 ∋ 模型值）。覆盖：fine（error）、detention_days（warn）、
    dates（warn）、articles 条号（error）、aliases（warn）。fine_masked 件跳过金额对账。"""
    out = ctx["output"]
    cleaned = ctx["record"].get("cleaned_text") or ""
    spans = ctx["spans"]
    findings = []

    def zone_join(types: list[str]) -> str:
        return "".join(cleaned[cs:ce] for typ in types for cs, ce, *_ in (spans.get(typ) or []))

    decision_text = zone_join(["decision", "facts"])          # 罚/拘常写在决定段，事实段含赌资数额
    oc = out.get("outcome") or {}
    fine = oc.get("fine") or 0
    det = oc.get("detention_days") or 0
    fm = bool(oc.get("fine_masked"))
    if fine and not fm:
        amts = _text_numbers(decision_text, "元") | _text_numbers(cleaned, "元")
        # 尾子串兜底：日期粘连长串（"202312284000元"）解析值失真，但 "4000元" 是其后缀
        if int(fine) not in amts and f"{int(fine)}元" not in cleaned:
            findings.append(_mk("value_grounded", "error",
                                f"罚款 {fine} 元不在正文金额集 {sorted(amts)[:6]}（疑幻觉/合并值）"))
    if det:
        days = _text_numbers(decision_text, "日") | _text_numbers(cleaned, "日")
        if int(det) not in days:
            findings.append(_mk("value_grounded", "warn",
                                f"拘留 {det} 日不在正文天数集 {sorted(days)[:6]}（复核）"))
    # 日期：模型值（YYYY-MM-DD/MM）→ 年月日/年月 两种原文形态
    dates = out.get("dates") or {}
    for k in ("behavior", "decision"):
        dv = dates.get(k)
        if isinstance(dv, str) and len(dv) >= 7:
            y, m = dv[:4], int(dv[5:7])
            dday = int(dv[8:10]) if len(dv) >= 10 and dv[8:10].isdigit() else None
            cands = [f"{y}年{m}月"]
            if dday:
                cands.append(f"{y}年{m}月{dday}日")
                cands.append(f"{y}-{m:02d}-{dday:02d}")
                cands.append(f"{y}.{m}.{dday}")
            if not any(c in cleaned for c in cands):
                # 宽口径：年月任一出现即算有据（公示常见"2026年1月17日"全角点等由 S0 归一）
                if not (f"{y}年" in cleaned and f"{m}月" in cleaned):
                    findings.append(_mk("value_grounded", "warn", f"dates.{k}={dv} 在正文中未找到对应年月"))
    # articles：条号原文写法（去版本注解）须出现在 decision/reasoning 区间
    art_zone = zone_join(["decision", "reasoning", "facts"])
    art_no = re.compile(r"第[一二三四五六七八九十百零\d]+条(?:第[一二三四五六七八九十\d]+款)?(?:第?[（(]?[一二三四五六七八九十\d]+[)）]?项)?")
    # 空白归一比对：OCR 中文间空格（"第十一 条第一款"）不应算未命中
    art_zone_c = re.sub(r"\s+", "", art_zone)
    cleaned_c = re.sub(r"\s+", "", cleaned)
    for a in (oc.get("articles") or []):
        t = (a.get("text") or "")
        # 条号提取：法条原文常被书名号/机关名分隔，整串匹配会误报——提取"第X条"式条号部分核对；
        # 无"第"写法（"网络安全法六十三条第一款"）剥法名后试补"第"再核对
        t_core = re.sub(r"《[^》]*》|（\d{4}[修订]?）|中华人民共和国|治安管理处罚法", "", t).strip()
        nos = art_no.findall(t_core if "第" in t_core else "第" + t_core.lstrip("第")) or art_no.findall(t)
        for no in (nos or [t_core]):
            if len(no) >= 3 and no not in art_zone and no not in cleaned \
                    and no not in art_zone_c and no not in cleaned_c:
                findings.append(_mk("value_grounded", "error", f"法条条号未命中：{no}（edition={a.get('edition')}）"))
                break
    # subject 三档中的 error 档已由 check_subject 承担；此处补 aliases 的存在性（warn）
    subj = out.get("subject") or {}
    for al in (subj.get("aliases") or [])[:5]:
        if isinstance(al, str) and al.strip() and al not in cleaned:
            findings.append(_mk("value_grounded", "warn", f"alias 未在正文找到：{al[:10]}"))
    return findings


CHECKS = [
    ("zones_tiling", check_zones_tiling),
    ("schema", check_schema),
    ("decision_present", check_decision_present),
    ("outcome_consistency", check_outcome_consistency),
    ("penalty_caps", check_penalty_caps),
    ("article_edition", check_article_edition),
    ("value_grounded", check_value_grounded),
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
