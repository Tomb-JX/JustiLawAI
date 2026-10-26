"""Field-table layer for non-sentence document headers.

The audit of expansion-1000 found that 96.5% of meta-only leaks come from
pkulaw/web field blocks, not from sentence-level meta. This module treats those
blocks as typed fields:

  label -> field_id + value span + role (person/case/prior/outcome/other)

The parser is label/schema driven, not semantic regex. The model may later
override roles for unknown fields; the parser never invents text: it only
returns spans in cleaned coordinates and the view builder projects them back to
the original text.

No model quote is produced here. The output is field IDs/spans, consistent with
the project's ID-reference wire.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date

from evidence_types import CleanSpan

# Labels audited on expansion-1000. This is a field vocabulary (data), not a
# semantic classifier: a label identifies a field, the role says which view it
# belongs to. Unknown labels stay role=other and are excluded from the teacher view.
FIELD_ROLES = {
    # person
    "行政相对人名称": "person", "行政相对人": "person", "行政相对人类型": "person",
    "行政相对人类别": "person", "被处罚对象": "person", "被处罚人": "person",
    "违法嫌疑人": "person", "违法行为人": "person", "姓名": "person",
    "工作单位": "person", "户籍地": "person", "户籍所在地": "person",
    "现住址": "person", "住址": "person", "证件类型": "person", "证件号": "person",
    "身份证号": "person", "法定代表人": "person", "法定代表人姓名": "person",
    "法定代表人身份证号": "person", "自然人证件类型": "person",
    "自然人证件号码": "person", "行政相对人统一社会信用代码": "person",
    "行政相对人工商登记码": "person", "行政相对人组织机构代码": "person",
    "行政相对人税务登记号": "person", "行政相对人事业单位证书号": "person",
    "行政相对人社会组织登记证号": "person",
    # case / document metadata
    "主题分类": "case", "执法级别": "case", "执法机关": "case", "执法地域": "case",
    "公布日期": "case", "发文案号": "case", "行政处罚决定书文号": "case",
    "决定书文号": "case", "案件名称": "case", "决定书名称": "case",
    "处罚决定日期": "case", "处罚机关": "case", "处罚决定机关": "case",
    "执法主体名称": "case", "执法主体": "case",
    # prior
    "违法前科": "prior", "前科": "prior", "违法经历": "prior",
    # outcome / legal basis
    "处罚种类": "outcome", "处罚类别": "outcome", "处罚内容": "outcome",
    "处罚结果": "outcome", "罚款金额": "outcome", "罚没情况": "outcome",
    "执法依据": "outcome", "处罚依据": "outcome", "处罚决定": "outcome",
    # other / section headings
    "违法事实": "other",
}
LABEL_RE = re.compile(r"(?P<label>" + "|".join(
    map(re.escape, sorted(FIELD_ROLES, key=len, reverse=True))) + r")\s*[:：]")
LABEL_LINE_RE = re.compile(r"^\s*(?P<label>" + "|".join(
    map(re.escape, sorted(FIELD_ROLES, key=len, reverse=True))) + r")\s*$")
SECTION_HEADS = ("现查明", "经查", "违法事实", "以上事实", "另查明")
DATE_RE = re.compile(r"(?:19|20)\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]?\s*(?:\d{1,2}\s*日?)?")
NONE_MARKERS = ("无前科", "没有前科", "无违法犯罪前科", "无违法前科", "无违法经历",
                "无前科记录", "无犯罪前科")


def _sentence_text(rec, sid):
    a, b = rec["sentences"][sid - 1]
    return rec["cleaned_text"][a:b]


def _zones(out):
    types = {}
    for zone in out.get("zones") or []:
        for sid in range(zone["from"], zone["to"] + 1):
            types[sid] = zone["type"]
    return types


def _cut_at_section(value):
    for head in SECTION_HEADS:
        idx = value.find(head)
        if idx > 0:
            return value[:idx].rstrip("，,；;。 \n"), True
    return value, False


def parse_fields(rec, out):
    """Return field records with cleaned start/end spans and roles.

    Label-only lines take the next non-label line as their value. Values stop at
    the next label or a section heading; a value that still looks contaminated is
    marked needs_review, not guessed.
    """
    types = _zones(out)
    first_f = next((sid for sid, typ in types.items() if typ == "facts"), len(rec["sentences"]) + 1)
    fields = []
    for sid in sorted(types):
        text = _sentence_text(rec, sid)
        base = rec["sentences"][sid - 1][0]
        hits = list(LABEL_RE.finditer(text))
        for i, hit in enumerate(hits):
            label = hit.group("label")
            role = FIELD_ROLES.get(label, "other")
            if role == "other":
                continue
            value_start = hit.end()
            value_end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
            raw_value = text[value_start:value_end]
            lead = len(raw_value) - len(raw_value.lstrip())
            value_start += lead
            value = raw_value.strip(" \t\n:：")
            status = "ok"
            clean_value, cut = _cut_at_section(value)
            if cut:
                value = clean_value
                status = "truncated"
            if not value:
                status = "empty"
            block = ("header" if sid < first_f and types.get(sid) == "meta"
                     else "table" if rec.get("zones_det") else
                     "body_prior" if role == "prior" else "body")
            fields.append({
                "field_id": f"F{len(fields) + 1}", "label": label, "role": role,
                "sentence_id": sid, "block": block, "status": status,
                "value": value, "start": base + value_start,
                "end": base + value_start + len(value),
            })
        # Prior labels sometimes appear without a colon (e.g. "违法前科2023年...").
        covered = {(hit.group("label"), hit.start()) for hit in hits}
        for m in re.finditer(r"(违法前科|前科|违法经历)\s*[:：]?", text):
            label = m.group(1)
            if (label, m.start()) in covered:
                continue
            before = text[max(0, m.start() - 2):m.start()]
            if any(x in before for x in ("无", "没")):
                value, status = "无", "ok"
            else:
                value = text[m.end():].strip(" \t\n:：")
                value, cut = _cut_at_section(value)
                status = "truncated" if cut else ("empty" if not value else "ok")
            fields.append({
                "field_id": f"F{len(fields) + 1}", "label": label, "role": "prior",
                "sentence_id": sid, "block": "header" if sid < first_f else "body_prior",
                "status": status, "value": value,
                "start": base + m.end(), "end": base + m.end() + len(value),
            })
        # label-only lines: use the next line as value, if it is not a label.
        lines = text.splitlines()
        for li, line in enumerate(lines):
            m = LABEL_LINE_RE.match(line)
            if not m:
                continue
            label = m.group("label")
            role = FIELD_ROLES.get(label, "other")
            if role == "other":
                continue
            nxt = lines[li + 1].strip() if li + 1 < len(lines) else ""
            if not nxt or LABEL_LINE_RE.match(nxt) or LABEL_RE.match(nxt):
                value, status = "", "empty"
            else:
                value, status = nxt, "ok"
            start = base + text.find(nxt) if value else base
            fields.append({
                "field_id": f"F{len(fields) + 1}", "label": label, "role": role,
                "sentence_id": sid, "block": "table" if rec.get("zones_det") else "body",
                "status": status, "value": value, "start": start,
                "end": start + len(value),
            })
    # Person identity block: pre-facts meta sentence carrying the target and
    # identity markers. Keep the prefix before prior/outcome labels, so a merged
    # identity+prior sentence still yields a person span for target visibility.
    # 2026-10-26 L5-VIEW-01：块起点收窄，不再从整句起点投影——字段表文书的标题
    # （"××局行政处罚决定书"+文号）与身份块同句，整句投影会把结果性标题带进教师视图。
    # 起点三候选取最大（均须落在身份锚之前）：① 结果性标题及其紧随文号的结尾（强制剥离）；
    # ② 身份锚之前最后一个 person 字段标签的起点（宽松无冒号，保留"被处罚人党**"类前导）；
    # ③ target 之前最近分隔符之后（保留"温某某，男…"类紧邻前导——锚本身是"男/女"，
    #    锚前分隔常在 target 与锚之间，直接用会把 target 切掉）。target 支持掩码等价。
    target = (rec.get("subject_mention") or "").strip()
    from s3 import mask_contains
    _SEP = "，,；;：:。 \n"
    _PERSON_LABEL_RE = re.compile("|".join(map(re.escape, sorted(
        (label for label, role in FIELD_ROLES.items() if role == "person"),
        key=len, reverse=True))))
    for sid in sorted(types):
        if not (sid < first_f and types.get(sid) == "meta"):
            continue
        text = _sentence_text(rec, sid)
        if not target or not (target in text or mask_contains(text, target)):
            continue
        identity = re.search(r"(?:男|女).{0,24}(?:出生|身份证|证件|户籍|住址|工作单位)", text)
        if not identity:
            continue
        base = rec["sentences"][sid - 1][0]
        head = text[:identity.start()]
        cands = [0]
        # 分隔项唯一来源：target 可定位时取 target 前最近分隔（保留紧邻前导）；
        # 掩码异形定位不到 target 时退化为身份锚前最近分隔。锚前分隔在 target 与锚
        # 之间的情况（"温某某，男"）若不丢弃会越过 target 本身。
        tpos = text.find(target)
        sep_from = tpos if 0 <= tpos < identity.start() else identity.start()
        cands.append(max(text[:sep_from].rfind(ch) for ch in _SEP) + 1)
        # 身份锚之前最后一个 person 字段标签起点（保留"被处罚人党**"类前导）
        cands.extend(label_hit.start() for label_hit in _PERSON_LABEL_RE.finditer(head))
        # 结果性标题及其紧随文号的结尾（强制剥离，L5-VIEW-01）
        for title in re.finditer(r"行政处罚决定书", head):
            end = title.end()
            doc_no = re.match(r"[^，,；;：:。]{0,40}?\d{0,8}号", head[end:])
            end += doc_no.end() if doc_no else 0
            while end < len(head) and head[end] in _SEP:
                end += 1
            cands.append(end)
        start_off = max(cands)
        cut_at = len(text)
        for hit in LABEL_RE.finditer(text):
            if FIELD_ROLES.get(hit.group("label")) in ("prior", "outcome"):
                cut_at = min(cut_at, hit.start())
        value = text[start_off:cut_at].rstrip("，,；;。 \n")
        if not value or not (target in value or mask_contains(value, target)):
            continue
        block_start, block_end = base + start_off, base + start_off + len(value)
        # The block already carries the identity fields; drop overlapping person
        # sub-fields to avoid duplicate text in the teacher view.
        fields = [f for f in fields
                  if not (f.get("role") == "person"
                          and not (f["end"] <= block_start or f["start"] >= block_end))]
        fields.append({"field_id": f"F{len(fields) + 1}", "label": "person_block",
                       "role": "person", "sentence_id": sid, "block": "header",
                       "status": "ok", "value": value, "start": block_start,
                       "end": block_end})
    return fields


def subtract_spans(spans, cuts):
    out = []
    for start, end in spans:
        cur = start
        for c, d in sorted(cuts):
            if d <= cur or c >= end:
                continue
            if c > cur:
                out.append((cur, min(c, end)))
            cur = max(cur, d)
            if cur >= end:
                break
        if cur < end:
            out.append((cur, end))
    return out


def _project(index, original, start, end):
    result = []
    for span in index.project_span(CleanSpan(start, end), original):
        if span.end > span.start:
            result.append((span.start, span.end))
    return result


def build_field_inputs(rec, out, index, meta_fields=None, prior_sentence_ids=None):
    """Build facts + person/prior fields; outcome/other never enter the view.

    Facts zone spans are reduced by every field/meta span, so a prior or outcome
    sub-span embedded in a facts sentence is removed from facts and (for prior)
    reinserted as a prior field.
    """
    target = (rec.get("subject_mention") or "").strip()
    original = rec.get("_text_full") or ""
    sentences = rec.get("sentences") or []
    types = _zones(out)
    # 掩码/实名变体等价（2026-10-26）：target 与原文写法可差在掩码字形（王*乙↔王x乙）
    from s3 import mask_contains
    if not target or not (target in original or mask_contains(original, target)) or not sentences:
        return None
    first_f = next((sid for sid, typ in types.items() if typ == "facts"), len(sentences) + 1)
    fields = parse_fields(rec, out)
    items, cuts = [], []
    seen_spans = set()
    # Every parsed field is removed from facts, including outcome/case fields.
    for field in fields:
        if field["status"] != "empty" and field["value"]:
            cuts.append((field["start"], field["end"]))
    for mf in (meta_fields or []):
        if isinstance(mf, dict) and isinstance(mf.get("start"), int) and isinstance(mf.get("end"), int):
            if mf["start"] < mf["end"]:
                cuts.append((mf["start"], mf["end"]))

    def add_meta(start, end, role, ref, block="field"):
        if not (0 <= start < end <= len(rec["cleaned_text"])):
            return
        if any(not (end <= s or start >= e) for s, e in seen_spans):
            return
        seen_spans.add((start, end))
        for a, b in _project(index, original, start, end):
            text = original[a:b]
            if text.strip():
                items.append({"id": ref, "sentence_id": None, "type": "meta",
                              "meta_role": role, "start": a, "end": b, "text": text,
                              "field_block": block})

    for field in fields:
        if field["role"] not in ("person", "prior"):
            continue
        if field["status"] == "empty" or not field["value"]:
            continue
        add_meta(field["start"], field["end"], field["role"], field["field_id"], field["block"])
    for mf in (meta_fields or []):
        if not isinstance(mf, dict) or mf.get("role") not in ("person", "prior"):
            continue
        start, end = mf.get("start"), mf.get("end")
        if isinstance(start, int) and isinstance(end, int) and start < end:
            add_meta(start, end, mf["role"], f"S{mf.get('sentence')}.meta", "meta_fields")
    for sid in (prior_sentence_ids or []):
        if type(sid) is not int or not 1 <= sid <= len(sentences):
            continue
        start, end = sentences[sid - 1]
        cuts.append((start, end))
        add_meta(start, end, "prior", f"S{sid}.prior", "prior_sentence")

    facts_spans = []
    for sid, typ in types.items():
        if typ == "facts":
            a, b = sentences[sid - 1]
            facts_spans.append((a, b))
    remaining = subtract_spans(facts_spans, cuts)
    for n, (start, end) in enumerate(remaining, 1):
        for part, (a, b) in enumerate(_project(index, original, start, end), 1):
            text = original[a:b]
            if text.strip():
                items.append({"id": f"facts.{n}.{part}", "sentence_id": None,
                              "type": "facts", "start": a, "end": b, "text": text})

    items.sort(key=lambda x: x["start"])
    if not items:
        return None
    if target not in "\n".join(x["text"] for x in items):
        return None
    aliases = (out.get("subject") or {}).get("aliases") or []
    return {"target": target, "aliases": aliases, "sentence_view": items,
            "facts_text": "\n".join(x["text"] for x in items if x["type"] == "facts"),
            "meta_text": "\n".join(x["text"] for x in items if x["type"] == "meta"),
            "regions": [(x["start"], x["end"]) for x in items],
            "view_hash": __import__("hashlib").sha256(
                __import__("json").dumps(items, ensure_ascii=False, sort_keys=True)
                .encode("utf-8")).hexdigest(),
            "fields": fields}


def _parse_date(text):
    m = DATE_RE.search(text or "")
    if not m:
        return None, "unknown"
    s = re.sub(r"[年月日./-]", "-", m.group(0))
    parts = [p for p in re.split(r"-+", s) if p]
    if len(parts) < 2:
        return None, "unknown"
    try:
        year, month = int(parts[0]), int(parts[1])
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day).isoformat(), ("明确" if len(parts) > 2 else "推断")
    except ValueError:
        return None, "unknown"


def build_prior_records(rec, fields, meta_fields=None, prior_sentence_ids=None):
    """Assemble prior facts from typed prior fields and prior meta spans.

    No legal conclusion is made here: date/kind are facts; whether the prior
    triggers a heavier penalty belongs to the norm layer.
    """
    target = rec.get("subject_mention") or ""
    prior_items = [f for f in fields if f["role"] == "prior" and f["status"] != "empty"
                   and f["value"]]
    for mf in (meta_fields or []):
        if isinstance(mf, dict) and mf.get("role") == "prior" and mf.get("quote"):
            prior_items.append({"field_id": f"S{mf.get('sentence')}.meta",
                                "label": "prior", "role": "prior",
                                "block": "meta_fields", "status": "ok",
                                "value": mf.get("quote"), "sentence_id": mf.get("sentence")})
    covered_sids = {item.get("sentence_id") for item in prior_items}
    for sid in (prior_sentence_ids or []):
        if type(sid) is not int or not 1 <= sid <= len(rec.get("sentences") or []):
            continue
        if sid in covered_sids:
            continue
        text = _sentence_text(rec, sid)
        prior_items.append({"field_id": f"S{sid}.prior", "label": "prior", "role": "prior",
                            "block": "sentence", "status": "ok", "value": text,
                            "sentence_id": sid})
    records = []
    positives = []
    explicit_none = False
    for item in prior_items:
        value = (item.get("value") or "").strip()
        is_none = any(marker in value for marker in NONE_MARKERS) or value in ("无", "没有", "无前科")
        date_value, date_status = _parse_date(value)
        binding = ("target_specific" if target and target in value else
                   "person_scoped" if item.get("block") in ("header", "table") else
                   "needs_review")
        record = {"source_ref": item.get("field_id"), "sentence_id": item.get("sentence_id"),
                  "raw": value, "explicit_none": is_none,
                  "date": date_value, "date_status": date_status,
                  "subject_binding": binding}
        records.append(record)
        if is_none:
            explicit_none = True
        else:
            positives.append(record)
    dated = [r for r in positives if r["date"]]
    if dated:
        latest_record = max(dated, key=lambda r: r["date"])
        latest, latest_status = latest_record["date"], latest_record["date_status"]
    elif positives:
        latest, latest_status = None, "推断"
    else:
        latest, latest_status = None, "未提及"
    return {"records": records, "has_prior": bool(positives),
            "explicit_none": explicit_none and not positives,
            "last_date": latest, "date_status": latest_status}


def find_person_binding(rec, out, target):
    """页头 person 角色字段 ↔ 目标人的确定性绑定。

    字段表/叙述式文书的"决定区"可能天生不含人名（决定区=处罚种类/执法依据栏目），
    但页头 person 栏（行政相对人/被处罚人/…，含 person_block 身份前缀块）载有目标人。
    2026-10-25 金丝雀（706 法宝 target 闸拒收全量 57 条）：57/57 绑定成功、0 错绑，
    报告 $DATA/s1_runs/person-binding-canary-20261025/CANARY-REPORT.md。

    只做标签抽取 + 掩码变体等值（复用 s3 的 mask_equal/mask_contains，含实名↔掩码），
    语义归属仍归模型（B-10）。返回绑定的 field dict；无绑定返回 None。
    """
    if not target:
        return None
    from s3 import mask_equal, mask_contains, strip_role_prefix
    try:
        fields = parse_fields(rec, out)
    except Exception:
        return None
    for f in fields:
        if f.get("role") != "person" or f.get("status") == "empty":
            continue
        value = (f.get("value") or "").strip()
        if not value:
            continue
        cands = [value] + [p.strip() for p in re.split(r"[、,，/和及]|等\d*人", value) if p.strip()]
        for c in cands:
            if mask_equal(c, target) or mask_equal(strip_role_prefix(c), target):
                return f
        if mask_contains(value, target):
            return f
    return None


def audit_view(inp, fields=None):
    """Role-aware audit: outcome fields never enter; prior may contain penalty words."""
    if not inp:
        return {"built": False}
    roles = Counter(x.get("meta_role") for x in inp["sentence_view"] if x["type"] == "meta")
    outcome_in_view = roles.get("outcome", 0)
    return {"built": True, "roles": dict(roles), "outcome_in_view": outcome_in_view,
            "prior_in_view": roles.get("prior", 0), "person_in_view": roles.get("person", 0),
            "target_visible": inp["target"] in "\n".join(x["text"] for x in inp["sentence_view"]),
            "facts_chars": len(inp["facts_text"]), "meta_chars": len(inp["meta_text"])}
