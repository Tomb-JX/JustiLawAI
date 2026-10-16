"""数据记录契约：解析层（统一中间格式，L1）与交付层（L3）的字段、取值与逐条校验。

数据分层见 docs/04-plan/project-status.md §4：
  L1 解析层 parsed/<来源>/<批次>/records.jsonl —— 各来源解析器的统一输出，未脱敏；
  L3 交付层 delivery/<版本>/admin_cases.schema-1.0.0.jsonl —— 构建脚本合并、脱敏后交引擎。

校验不在第一个错误处停下，而是返回全部问题（Issue），便于出批次报告：
  error = 必须修（交付层的 error 记录会被退回）；warn = 可接受但要报告；info = 提示。
自检：python -m app.discretion.records check <文件.jsonl> --layer parsed|delivery
"""
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

RECORD_VERSION = "parsed-1"

SOURCES = ("公开网页", "复议专栏", "法宝执法库", "法宝案例库", "裁判文书采购", "合作案卷")
SOURCE_TYPES = ("处罚决定书", "不予处罚决定书", "行政复议决定书", "行政判决书", "执法公示", "合作案卷")
OUTCOME_TYPES = ("不予处罚", "不构成违法", "警告", "罚款", "拘留", "拘留并处罚款", "移送刑事")
REVIEW_RESULTS = ("维持", "变更", "撤销", "确认违法", "程序驳回", "无")
LAW_VERSIONS = ("旧法", "新法", "未知")
LAW_ID = {"旧法": "psal-2012", "新法": "psal-2025"}
NEW_LAW_FROM = date(2026, 1, 1)
TIERS = ("L1", "L2", "L3", "L4")   # 金标候选 / 只有结果 / 范围外 / 待核
SEGMENTS = ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review")
# 事实段里出现即视为混进了结论。"处以""被拘留"等词不在内：前科描述（"曾因赌博被处以拘留五日"）是事实
CONCLUSION_WORDS = ("决定给予", "现决定", "情节严重", "从轻处罚", "减轻处罚", "从重处罚")

# 交付层不允许出现的内部或敏感字段（D3：溯源走台账；脱敏后不得保留原始称谓与文号）
DELIVERY_FORBIDDEN = ("doc_no", "subject_mention", "page_id", "site", "title", "publisher", "url",
                      "extra", "pkulaw_id", "event_hint")
PRIVACY_PATTERNS = {
    "身份证号": re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])|(?<!\d)\d{6}(?:19|20)\d{2}[*＊xX]{4,}"),
    "手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "网址": re.compile(r"https?://", re.I),
    "邮箱": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
}


@dataclass(frozen=True)
class F:
    """字段定义。req：L1 / L3 是否必须有这个键（值可为空看 nullable）。"""
    name: str
    kind: str                      # str / date / bool / int / num / list / dict / enum
    l1: str                        # 必填 / 可选 / —（不属于该层）
    l3: str
    nullable: bool = True
    enum: tuple = ()
    desc: str = ""


FIELDS: tuple[F, ...] = (
    F("record_version", "str", "必填", "—", False, desc=f"解析层格式版本，固定为 {RECORD_VERSION}"),
    F("id", "str", "必填", "必填", False, desc="台账 id，前缀标来源（W- 公开网页，B- 复议专栏，P- 法宝，C- 采购）"),
    F("source", "enum", "必填", "可选", False, SOURCES, "来源渠道"),
    F("batch", "str", "必填", "可选", False, desc="原始层批次名（raw/<来源>/<批次>/），用于追溯"),
    F("parser", "str", "必填", "—", False, desc="解析器与版本，如 harvest/parse.py@0.4"),
    F("source_type", "enum", "必填", "必填", False, SOURCE_TYPES, "文书类型"),
    F("source_ref", "str", "必填", "—", False, desc="原文出处（URL、台账引用或法宝引证码）；交付层不得出现"),
    F("doc_no", "str", "可选", "—", desc="原始文号；交付层只给 doc_no_hash"),
    F("doc_no_hash", "str", "可选", "必填", desc="规范化文号的 SHA-256 前 16 位，无文号时为空"),
    F("harvest_date", "date", "必填", "必填", False, desc="采集日期"),
    F("deidentified", "flag", "可选", "必填", False, desc="交付层必须为'是'；解析层可写 false"),
    F("r6_scan", "dict", "—", "必填", False, desc="隐私扫描结果 {passed, date}"),
    F("behavior_date", "date", "可选", "必填", desc="违法行为日期，持续行为取结束日；可只到月"),
    F("decision_date", "date", "可选", "必填", desc="处罚决定日期"),
    F("authority", "str", "可选", "必填", desc="作出决定的机关"),
    F("region", "str", "可选", "必填", desc="行政区划代码；交付层必须有"),
    F("province", "str", "可选", "可选"),
    F("province_code", "str", "—", "可选"),
    F("region_level", "str", "—", "可选"),
    F("law_version", "enum", "可选", "必填", False, LAW_VERSIONS, "旧法（2012 修正）/ 新法（2025 修订）/ 未知"),
    F("subject_mention", "str", "可选", "—", desc="脱敏前本人在正文中的写法（如'王某某'），供脱敏替换为'甲'"),
    F("subject_alias", "str", "—", "必填", False, desc="本人代称，固定为'甲'"),
    F("event_key", "str", "可选", "可选", desc="事件指纹：处罚机关 + 事实段首个日期 + 金额"),
    F("event_id", "str", "—", "必填", False, desc="事件编号，同一事件多人共用"),
    F("linked_ids", "list", "—", "必填", False, desc="关联记录（如复议决定书与原处罚决定书）"),
    F("text_full", "str", "必填", "必填", False, desc="正文；交付层是脱敏后冻结的正本"),
    F("text_sha256", "str", "—", "必填", False, desc="text_full 的 SHA-256"),
    F("segmented", "bool", "必填", "必填", False),
    F("segments", "dict", "可选", "必填", False, desc="各段在 text_full 中的 [起, 止)"),
    *(F(s, "str", "可选", "必填") for s in SEGMENTS),
    F("outcome", "dict", "必填", "必填", False, desc="处罚结果（见 OUTCOME_FIELDS）"),
    F("review", "dict", "必填", "必填", False, desc="复议、诉讼结论（见 REVIEW_FIELDS）"),
    F("quality", "dict", "必填", "必填", False, desc="质量与分级（见 QUALITY_FIELDS）"),
    F("schema_version", "str", "—", "必填", False, desc="要素本体版本"),
    F("pipeline_version", "str", "—", "必填", False, desc="构建管线版本"),
    F("extra", "dict", "可选", "—", desc="来源专有的内部字段（page_id、site、pkulaw_id 等）一律放这里"),
)
OUTCOME_FIELDS: tuple[F, ...] = (
    F("type", "enum", "必填", "必填", True, OUTCOME_TYPES, "处罚类型；L3/L4 分级的记录可为空"),
    F("detention_days", "int", "必填", "必填", False, desc="拘留天数，没有填 0；合并执行取合并后"),
    F("fine", "num", "必填", "必填", False, desc="罚款（元），没有填 0"),
    F("detention_not_executed", "enum", "必填", "必填", False, ("是", "否")),
    F("confiscation", "str", "可选", "可选"),
    F("articles", "list", "必填", "必填", False),
    F("stated_circumstances", "list", "可选", "可选"),
    F("law_version", "enum", "可选", "可选", True, LAW_VERSIONS, "若给出须与顶层 law_version 一致"),
)
REVIEW_FIELDS: tuple[F, ...] = (
    F("result", "enum", "必填", "必填", False, REVIEW_RESULTS,
      "诉讼'判决驳回诉讼请求'记'维持'；复议驳回申请、裁定驳回起诉记'程序驳回'"),
    F("changed_outcome", "dict", "可选", "可选"),
)
QUALITY_FIELDS: tuple[F, ...] = (
    F("tier", "str", "必填", "可选", False, desc="L1 金标候选 / L2 只有结果 / L3 范围外 / L4 待核（允许'L1-金标候选'写法）"),
    F("in_scope", "bool", "必填", "可选", False),
    F("completeness", "dict", "必填", "必填", False, desc="{has_amount, has_outcome}"),
    F("parse_warnings", "list", "必填", "必填", False),
    F("form", "str", "可选", "可选", desc="页面或文书形态（叙述式、字段式、汇总、复议、判决书……）"),
    F("gambling", "enum", "可选", "—", True, ("是", "否", "待定")),
    F("ocr", "bool", "可选", "可选"),
    F("facts_contains_conclusion", "bool", "可选", "可选"),
    F("ambiguous_persons", "bool", "可选", "可选"),
    F("age_uncertain", "bool", "可选", "可选"),
)


@dataclass(frozen=True)
class Issue:
    level: str                     # error / warn / info
    code: str
    field: str
    message: str


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def parse_date(v) -> tuple[date | None, str]:
    """返回 (日期, 精度)；精度为 day / month / none / bad。只到月的取 1 日。"""
    if _empty(v):
        return None, "none"
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s), "day"
        if re.fullmatch(r"\d{4}-\d{2}", s):
            return date.fromisoformat(s + "-01"), "month"
    except ValueError:
        pass
    return None, "bad"


def _check_type(f: F, v, path: str, layer: str) -> list[Issue]:
    out: list[Issue] = []
    if _empty(v):
        if not f.nullable and f.kind not in ("list", "dict"):
            out.append(Issue("error", "empty_required", path, f"{path} 不能为空"))
        return out
    ok = {"str": isinstance(v, str), "enum": isinstance(v, str), "bool": isinstance(v, bool),
          "int": isinstance(v, int) and not isinstance(v, bool),
          "num": isinstance(v, (int, float)) and not isinstance(v, bool),
          "list": isinstance(v, list), "dict": isinstance(v, dict),
          "date": isinstance(v, str), "flag": isinstance(v, (bool, str))}[f.kind]
    if not ok:
        out.append(Issue("error", "bad_type", path, f"{path} 应为 {f.kind}，实为 {type(v).__name__}"))
    elif f.enum and v not in f.enum:
        hint = "；'驳回'请按 D4 改为'维持'或'程序驳回'" if path == "review.result" and v == "驳回" else ""
        out.append(Issue("error", "bad_enum", path, f"{path}='{v}' 不在 {list(f.enum)} 中{hint}"))
    elif f.kind == "date":
        _, prec = parse_date(v)
        if prec == "bad":
            out.append(Issue("error", "bad_date", path, f"{path}='{v}' 不是 YYYY-MM-DD 或 YYYY-MM"))
        elif prec == "month" and layer == "delivery" and path != "harvest_date":
            out.append(Issue("info", "date_month_only", path, f"{path} 只到月"))
    return out


def _check_fields(rec: dict, fields: tuple[F, ...], layer: str, prefix: str = "") -> list[Issue]:
    col = "l1" if layer == "parsed" else "l3"
    out: list[Issue] = []
    for f in fields:
        req = getattr(f, col)
        path = prefix + f.name
        if req == "—":
            continue
        if f.name not in rec:
            if req == "必填":
                out.append(Issue("error", "missing_field", path, f"缺少字段 {path}"))
            continue
        v = rec[f.name]
        if v == "" and f.kind == "enum" and f.nullable is False:
            out.append(Issue("error", "empty_required", path, f"{path} 为空字符串；未知请写'未知'等取值"))
            continue
        out += _check_type(f, v, path, layer)
    return out


@lru_cache(maxsize=1)
def statutory_limits() -> dict[str, tuple[int, float, int]]:
    """{法律版本: (拘留上限, 罚款上限, 合并执行拘留上限)}，取自规范库，随规范库更新。"""
    from .norm_store import load
    lib = load()
    out = {}
    for version, law_id in LAW_ID.items():
        law = lib.law(law_id)
        merge = (law.modifiers.get("merge_cap") or {}).get("max_detention_days", 20)
        out[version] = (max(t.detention[1] for t in law.tiers.values()),
                        max(t.fine[1] for t in law.tiers.values()), merge)
    return out


def _check_outcome(rec: dict, layer: str) -> list[Issue]:
    oc, out = rec.get("outcome") or {}, []
    tier = str((rec.get("quality") or {}).get("tier", ""))[:2]
    t = oc.get("type")
    days, fine = oc.get("detention_days") or 0, oc.get("fine") or 0
    if _empty(t):
        if layer == "delivery" or tier in ("L1", "L2"):
            out.append(Issue("error", "outcome_missing", "outcome.type", "金标候选或只有结果的记录必须有处罚类型"))
        return out
    expect = {"罚款": (False, True), "拘留": (True, False), "拘留并处罚款": (True, True),
              "不予处罚": (False, False), "不构成违法": (False, False), "警告": (False, False)}.get(t)
    if expect and ((days > 0) != expect[0] or (fine > 0) != expect[1]):
        out.append(Issue("error", "outcome_inconsistent", "outcome",
                         f"类型'{t}'与拘留 {days} 天、罚款 {fine} 元不符"))
    if t == "警告":
        out.append(Issue("warn", "warning_not_in_article", "outcome.type",
                         "警告不在第七十条、第八十二条的罚则内，确认是否为减轻处罚"))
    version = rec.get("law_version") or oc.get("law_version")
    if version in statutory_limits():
        dmax, fmax, merge = statutory_limits()[version]
        if days > merge:
            out.append(Issue("error", "detention_over_limit", "outcome.detention_days",
                             f"拘留 {days} 天超过合并执行上限 {merge} 天"))
        elif days > dmax:
            out.append(Issue("warn", "detention_merged", "outcome.detention_days",
                             f"拘留 {days} 天超过单项上限 {dmax} 天，应为合并执行"))
        if fine > fmax:
            out.append(Issue("error", "fine_over_limit", "outcome.fine",
                             f"罚款 {fine} 元超过{version}上限 {fmax:g} 元（多项违法合并的请在 parse_warnings 注明）"))
    if oc.get("law_version") not in (None, "") and rec.get("law_version") not in (None, "") \
            and oc["law_version"] != rec["law_version"]:
        out.append(Issue("error", "law_version_mismatch", "outcome.law_version", "与顶层 law_version 不一致"))
    return out


def _check_dates_and_law(rec: dict) -> list[Issue]:
    out = []
    b, _ = parse_date(rec.get("behavior_date"))
    d, _ = parse_date(rec.get("decision_date"))
    version = rec.get("law_version") or (rec.get("outcome") or {}).get("law_version")
    if b and d and d < b:
        out.append(Issue("warn", "decision_before_behavior", "decision_date", "决定日期早于行为日期"))
    if b and b >= NEW_LAW_FROM and version == "旧法":
        out.append(Issue("error", "law_version_conflict", "law_version", "行为在 2026-01-01 之后，不能适用旧法"))
    if b and b < NEW_LAW_FROM and version == "新法":
        out.append(Issue("info", "new_law_for_old_behavior", "law_version",
                         "行为在新法施行前却适用新法：应为从旧兼从轻，请确认"))
    return out


def _check_segments(rec: dict, layer: str) -> list[Issue]:
    full, out = rec.get("text_full") or "", []
    spans = rec.get("segments") or {}
    for s in SEGMENTS:
        seg = rec.get(s)
        if _empty(seg):
            continue
        if layer == "parsed":
            if seg not in full:
                out.append(Issue("error", "segment_not_substring", s, f"{s} 不是 text_full 的连续子串"))
            continue
        span = spans.get(s)
        if not span or len(span) != 2:
            out.append(Issue("error", "segment_offset_missing", f"segments.{s}", f"{s} 有内容但没有起止位置"))
        elif full[span[0]:span[1]] != seg:
            out.append(Issue("error", "segment_offset_mismatch", f"segments.{s}", f"{s} 的起止位置切不出原段"))
    if rec.get("segmented") and _empty(rec.get("text_facts")) and _empty(rec.get("text_decision")):
        out.append(Issue("warn", "segmented_but_empty", "segmented", "标了已分段，但事实段和决定段都为空"))
    return out


def _check_quality(rec: dict, layer: str) -> list[Issue]:
    q, out = rec.get("quality") or {}, []
    out += _check_fields(q, QUALITY_FIELDS, layer, "quality.")
    tier = str(q.get("tier", ""))[:2]
    if "tier" in q and tier not in TIERS:
        out.append(Issue("error", "bad_enum", "quality.tier", f"quality.tier='{q.get('tier')}' 应以 L1–L4 开头"))
    if tier == "L1" and _empty(rec.get("text_facts")):
        out.append(Issue("error", "tier_inconsistent", "quality.tier", "L1 金标候选必须有事实段"))
    c = q.get("completeness") or {}
    for k in ("has_amount", "has_outcome"):
        if "completeness" in q and not isinstance(c.get(k), bool):
            out.append(Issue("error", "missing_field", f"quality.completeness.{k}", f"缺少布尔值 {k}"))
    return out


def check_parsed(rec: dict) -> list[Issue]:
    """解析层（L1，统一中间格式）逐条校验。"""
    out = _check_fields(rec, FIELDS, "parsed")
    if rec.get("record_version") not in (None, RECORD_VERSION):
        out.append(Issue("error", "bad_record_version", "record_version", f"应为 {RECORD_VERSION}"))
    known = {f.name for f in FIELDS if f.l1 != "—"}
    extra = sorted(set(rec) - known)
    if extra:
        out.append(Issue("warn", "unknown_field", ",".join(extra), f"未定义的顶层字段请移入 extra：{extra}"))
    out += _check_fields(rec.get("outcome") or {}, OUTCOME_FIELDS, "parsed", "outcome.") if rec.get("outcome") else []
    out += _check_fields(rec.get("review") or {}, REVIEW_FIELDS, "parsed", "review.") if rec.get("review") else []
    out += _check_quality(rec, "parsed") + _check_segments(rec, "parsed")
    out += _check_outcome(rec, "parsed") + _check_dates_and_law(rec)
    if _empty(rec.get("region")) and _empty(rec.get("province")) and _empty(rec.get("authority")):
        out.append(Issue("warn", "unlocatable", "region", "区划、省份、机关都为空，构建时无法定位到省"))
    if str((rec.get("quality") or {}).get("tier", ""))[:2] == "L1" and _empty(rec.get("event_key")):
        out.append(Issue("info", "event_key_missing", "event_key", "建议给出事件指纹，便于按事件分组"))
    return out


def check_delivery(rec: dict) -> list[Issue]:
    """交付层（L3）逐条校验，对应数据交付规格 §4。"""
    out = _check_fields(rec, FIELDS, "delivery")
    leaked = [k for k in DELIVERY_FORBIDDEN if k in rec]
    if leaked:
        out.append(Issue("error", "internal_field_leaked", ",".join(leaked), f"内部或敏感字段不得进入交付：{leaked}"))
    known = {f.name for f in FIELDS if f.l3 != "—"}
    extra = sorted(set(rec) - known - set(leaked))
    if extra:
        out.append(Issue("warn", "unknown_field", ",".join(extra), f"规格未定义的字段：{extra}"))
    out += _check_fields(rec.get("outcome") or {}, OUTCOME_FIELDS, "delivery", "outcome.")
    out += _check_fields(rec.get("review") or {}, REVIEW_FIELDS, "delivery", "review.")
    out += _check_quality(rec, "delivery") + _check_segments(rec, "delivery")
    out += _check_outcome(rec, "delivery") + _check_dates_and_law(rec)
    if rec.get("deidentified") != "是":
        out.append(Issue("error", "not_deidentified", "deidentified", "交付层必须已脱敏"))
    if not (rec.get("r6_scan") or {}).get("passed"):
        out.append(Issue("error", "r6_not_passed", "r6_scan", "隐私扫描未通过或缺失"))
    full = rec.get("text_full") or ""
    if rec.get("text_sha256") and hashlib.sha256(full.encode("utf-8")).hexdigest() != rec["text_sha256"]:
        out.append(Issue("error", "sha_mismatch", "text_sha256", "text_sha256 与正文不符"))
    if rec.get("subject_alias") not in (None, "甲"):
        out.append(Issue("error", "bad_alias", "subject_alias", "本人代称必须为'甲'"))
    facts = rec.get("text_facts") or ""
    if facts and "甲" not in facts:
        out.append(Issue("error", "subject_not_in_facts", "text_facts", "事实段里找不到本人代称'甲'"))
    if facts and not (rec.get("quality") or {}).get("facts_contains_conclusion"):
        hits = [w for w in CONCLUSION_WORDS if w in facts]
        if hits:
            out.append(Issue("error", "conclusion_in_facts", "text_facts", f"事实段含结论词 {hits}，且未标注"))
    texts = " ".join(str(rec.get(k) or "") for k in ("text_full", "authority", "source_ref"))
    for name, pat in PRIVACY_PATTERNS.items():
        if pat.search(texts):
            out.append(Issue("error", "privacy_hit", name, f"疑似残留{name}"))
    return out


FIELD_SPECIFIC = ("missing_field", "bad_type", "empty_required", "bad_enum", "bad_date")


def summarize(issues_by_id: dict[str, list[Issue]]) -> dict:
    """{问题: {level, count, message, ids}}，按级别、次数排序；与字段相关的问题按"问题:字段"分开计数。"""
    agg: dict[str, dict] = {}
    for rid, issues in issues_by_id.items():
        for i in issues:
            key = f"{i.code}:{i.field}" if i.code in FIELD_SPECIFIC else i.code
            a = agg.setdefault(key, {"level": i.level, "count": 0, "message": i.message, "ids": []})
            a["count"] += 1
            if len(a["ids"]) < 20:
                a["ids"].append(rid)
    order = {"error": 0, "warn": 1, "info": 2}
    return dict(sorted(agg.items(), key=lambda kv: (order[kv[1]["level"]], -kv[1]["count"])))


def field_table_markdown() -> str:
    """规格文档里的字段表（由本模块生成，保证文档与校验一致）。"""
    def rows(fields, prefix=""):
        for f in fields:
            enum = "、".join(f.enum) if f.enum else ""
            yield f"| `{prefix}{f.name}` | {f.kind} | {f.l1} | {f.l3} | {'可' if f.nullable else '否'} | {enum} | {f.desc} |"
    head = "| 字段 | 类型 | 解析层 L1 | 交付层 L3 | 可为空 | 取值 | 说明 |\n|---|---|---|---|---|---|---|"
    return "\n".join([head, *rows(FIELDS), *rows(OUTCOME_FIELDS, "outcome."), *rows(REVIEW_FIELDS, "review."),
                      *rows(QUALITY_FIELDS, "quality.")])


def update_doc(path: str) -> None:
    from pathlib import Path
    doc = Path(path)
    text = doc.read_text("utf-8")
    block = (f"<!-- records:begin -->\n> 由 `records.py`（{RECORD_VERSION}）自动生成，请勿手改。\n\n"
             f"{field_table_markdown()}\n<!-- records:end -->")
    new, n = re.subn(r"<!-- records:begin -->.*?<!-- records:end -->", lambda _: block, text, flags=re.S)
    if n != 1:
        raise SystemExit(f"{path} 中没有找到唯一的 records 标记")
    doc.write_text(new, "utf-8")


def _cli(argv: list[str]) -> int:
    import argparse
    import json
    from pathlib import Path
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m app.discretion.records")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="逐条校验一个 JSONL 文件")
    c.add_argument("path")
    c.add_argument("--layer", choices=["parsed", "delivery"], required=True)
    d = sub.add_parser("update-doc", help="把字段表写进规格文档的 records 标记之间")
    d.add_argument("path")
    a = ap.parse_args(argv)
    if a.cmd == "update-doc":
        update_doc(a.path)
        return 0
    check = check_parsed if a.layer == "parsed" else check_delivery
    by_id, n = {}, 0
    with Path(a.path).open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            n += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                by_id[f"第{i}行"] = [Issue("error", "bad_json", "", str(e))]
                continue
            issues = check(rec)
            if issues:
                by_id[str(rec.get("id") or f"第{i}行")] = issues
    bad = sum(any(i.level == "error" for i in v) for v in by_id.values())
    print(f"{a.path}：{n} 条，含 error 的 {bad} 条")
    for code, s in summarize(by_id).items():
        print(f"  {s['level']:<5} {code:<28} {s['count']:>5}  {s['message'][:70]}  例：{', '.join(s['ids'][:3])}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
