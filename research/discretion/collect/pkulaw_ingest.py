"""北大法宝（渠道 C）导出文件 → 结构化数据（对齐 docs/05-research/data-spec.md v0.1）。

两种导出形态（2026-10-16 实测，沪公长(长新)行罚决字〔2025〕00289/00290 两份实样）：

  目录列表 .xls（"北大法宝V6-行政执法-行政执法字段表单"）
    第 1 行：子库与表单名；第 2 行：搜索条件 + 下载时间（进数据卡，必须留住）；
    第 3 行：字段名（序号/标题/执法机关/发文案号/公布日期/行政相对人/执法依据/处罚种类/执法地域/原文链接/罚没总金额（万元））；
    其后为数据行；末尾是版权与二维码页脚（**不是数据**，解析时必须按标记截断）。
    .xls 是 BIFF8 二进制，先用 pkulaw_xls2csv.ps1（Excel COM）转 UTF-8 CSV 再交给本脚本。

  文书 .doc / .docx（处罚决定书公示；司法案例库判决书形态待取得样本后另加解析器）
    元数据块 10 项：主题分类/处罚种类/行政相对人/执法级别/执法机关/执法地域/公布日期/发文案号/罚没情况/执法依据
    决定表 7 行：文号/被处罚对象/处罚事由/处罚依据/处罚结果/处罚决定日期/处罚机关
    页脚：法宝版权 + 原文链接（含 32 位哈希）。法宝引证码（FBM-CLI.…）在**文件名**里。
    .doc 用 antiword 取文本（本机已有），失败退回 Word COM；.docx 用 python-docx。

**这类执法公示摘要没有违法事实、没有行为日期**（决定处罚结果的信息不在文本里）——按 D6 只能进
`admin_outcomes_only.jsonl`（结果-only 层，用于分布校准与 T-time 计数，不进金标、不作模型输入）。
脚本据事实段是否为空自动分级：有事实 → `admin_cases.jsonl`（金标候选），无事实 → 结果-only 层。

**司法案例库是另一条数据线，而且是行政金标的主力**（2026-10-16 实测 + 覆盖普查）：
法院判决书在法宝里是 29 字段的**已分段**结构（Ascertain 经审理查明 / Identified 本院认为 /
RefereeResult 判决结果 / RefereeBasis 裁判依据），事实段里**完整复述原行政处罚**（拘留日数、罚款额、收缴赌资）。
行政赌博判决量级：行政一审 4,986、行政二审 6,604（仅判决书 4,630），远超金标需求；但**近年骤降**
（2025 年审结 43、2026 年 12）——T-time 不能靠判决书。判决书当事人是**真名**，脱敏不能省。

用法（仓库根目录；**输出默认按批次隔离**，不再写入共享目录）：

  # 1) 目录表 → 工作清单（哪些还没下全文；按法条/省/案由/年份统计，用来决定下一批下什么）
  python research/discretion/collect/pkulaw_ingest.py catalog --xls inbox/pkulaw/R1/【北大法宝】目录列表.xls
      # 默认 → $JUSTILAW_DATA_DIR/catalog/<batch>/worklist.csv
  # 2) 已下全文（行政执法库）→ 结构化记录（与工作清单按文号 join）
  python research/discretion/collect/pkulaw_ingest.py docs --docs inbox/pkulaw/R1-docs --batch R1 \\
      --worklist $JUSTILAW_DATA_DIR/catalog/R1/worklist.csv
      # 默认 → $JUSTILAW_DATA_DIR/ingest/R1/{admin_cases.jsonl, admin_outcomes_only.jsonl, …}
      # 累积多批：--append（按引证码/文号去重合并）；重跑同批：--force
  # 3) 司法案例（MCP 响应 JSON / JSONL / 目录）→ 判决书规格 JSONL
  python research/discretion/collect/pkulaw_ingest.py cases --src $JUSTILAW_DATA_DIR/engine/pkulaw_mcp/cache/mcp-case --batch pfnl-2026H2
      # 默认 → $JUSTILAW_DATA_DIR/cases/<batch>/pkulaw_cases.pre_deid.jsonl

**输出保护（2026-10-16 整改）**：历史版本默认 `--out $JUSTILAW_DATA_DIR/admin`，而 `admin/` 是
数据链路（发现层）的统一交付目录（`admin_cases.schema-*.jsonl`、`admin_outcomes_only.jsonl`、
`SHA256SUMS` 等），本脚本的 L2 产物与 `SHA256SUMS` 与其**同名**，默认运行会互相覆盖。
现在：① 缺省输出按 `$JUSTILAW_DATA_DIR/<kind>/<batch>/` 隔离；② 显式 `--out` 指向已有产物时
**拒绝写入**，除非 `--append`（合并，按引证码/文号去重）或 `--force`（覆盖重写）。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import DATA_DIR, registry_add, report, sha256_path  # noqa: E402

SCHEMA_VERSION = "0.1"  # data-spec v0.1
DOC_EXTS = {".doc", ".docx", ".pdf", ".txt", ".md"}

# ---------- 输出隔离与保护（2026-10-16：修"解析脚本默认写共享目录、与他流产物同名互相覆盖"） ----------

OUTPUT_NAMES = {
    "catalog": ("worklist.csv", "catalog.stats.json"),
    "docs": ("admin_cases.jsonl", "admin_outcomes_only.jsonl", "admin_needs_review.jsonl",
             "pkulaw_out_of_scope.jsonl", "SHA256SUMS", "pkulaw_ingest.stats.json"),
    "cases": ("pkulaw_cases.pre_deid.jsonl", "pkulaw_crim.pre_deid.jsonl", "pkulaw_cases.stats.json"),
    "worklist": ("worklist.csv",),
}
# 缺省目录名（与子命令名解耦：docs 的产物落 ingest/，语义更直白）
OUTPUT_DIRNAME = {"docs": "ingest", "cases": "cases", "catalog": "catalog", "worklist": "worklist"}


def batch_tag(explicit: str = "", harvest_date: str = "") -> str:
    """批次标签：显式 > 采集日期 > 时间戳。"""
    return explicit or harvest_date or datetime.now().strftime("%Y%m%d-%H%M%S")


def resolve_out(explicit: str, kind: str, batch: str) -> Path:
    """--out 显式给就尊重；缺省按批次隔离在 $JUSTILAW_DATA_DIR/<dir>/<batch>/。

    `admin/` 是数据链路（发现层）的交付目录，本脚本与其产物同名（admin_outcomes_only.jsonl /
    SHA256SUMS），默认写进去会互相覆盖——所以默认不再指向任何共享目录。
    """
    return Path(explicit) if explicit else DATA_DIR / OUTPUT_DIRNAME.get(kind, kind) / batch


def guard_outputs(out: Path, kind: str, *, force: bool, append: bool = False) -> list[str]:
    """目标目录已有本类产物时拒绝静默覆盖（保护其他批次/其他工作流的输出）。"""
    existing = [n for n in OUTPUT_NAMES[kind] if (out / n).exists()]
    if existing and not (force or append):
        raise SystemExit(
            f"拒绝写入：{out} 已有解析产物 {existing}\n"
            "  这是防覆盖保护（该目录可能属于其他批次或其他工作流）。三种处理：\n"
            "  · 换目录：不传 --out 时默认已按批次隔离（$JUSTILAW_DATA_DIR/<kind>/<batch>/）\n"
            "  · 追加合并：--append（按 引证码/文号 去重后合并）\n"
            "  · 覆盖重写：--force")
    return existing


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _read_text_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl_atomic(path: Path, records: list[dict]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _rec_key(r: dict) -> str:
    return (r.get("pkulaw_id") or r.get("doc_no") or r.get("id")
            or json.dumps(r, ensure_ascii=False, sort_keys=True)[:200])


def merge_jsonl(path: Path, new_records: list[dict]) -> tuple[list[dict], int]:
    """把新记录并入已有 JSONL（按引证码/文号去重，保留旧记录顺序在前），原子重写。

    返回 (合并后记录, 新增数)。
    """
    old = _read_jsonl(path)
    seen, merged = set(), []
    for r in old + new_records:
        k = _rec_key(r)
        if k in seen:
            continue
        seen.add(k)
        merged.append(r)
    added = len(merged) - len(old) if old else len(merged)
    _write_jsonl_atomic(path, merged)
    return merged, max(added, 0)


# ---------- parsed-1：统一中间格式（L1）——契约见 justilaw-api/app/discretion/records.py ----------

PARSER_ID = "collect/pkulaw_ingest.py@0.2"
SOURCE_OF_LIB = {"apy": "法宝执法库", "pfnl": "法宝案例库"}
CONTRACT_TOP_FIELDS = (
    "record_version", "id", "source", "batch", "parser", "source_type", "source_ref", "doc_no",
    "doc_no_hash", "harvest_date", "deidentified", "behavior_date", "decision_date", "authority",
    "region", "province", "law_version", "subject_mention", "event_key", "text_full", "segmented",
    "segments", "text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review",
    "outcome", "review", "quality", "extra",
)
CONTRACT_SOURCE_TYPES = ("处罚决定书", "不予处罚决定书", "行政复议决定书", "行政判决书", "执法公示", "合作案卷")
CONTRACT_OUTCOME_TYPES = ("不予处罚", "不构成违法", "警告", "罚款", "拘留", "拘留并处罚款", "移送刑事")
CONTRACT_REVIEW_RESULTS = ("维持", "变更", "撤销", "确认违法", "程序驳回", "无")
CONTRACT_LAW_VERSIONS = ("旧法", "新法", "未知")
CONTRACT_OUTCOME_FIELDS = ("type", "detention_days", "fine", "detention_not_executed",
                           "confiscation", "articles", "stated_circumstances", "law_version")
# 与 records.py 的 CONCLUSION_WORDS 保持同步（事实段出现即视为混进结论）
CONCLUSION_WORDS = ("决定给予", "现决定", "情节严重", "从轻处罚", "减轻处罚", "从重处罚")
SEGMENT_KEYS = ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review")


def doc_no_norm(doc_no: str) -> str:
    """规格 v0.2 §1.1 的文号规范化——与 research/discretion/harvest/deid.py 同源实现。"""
    s = re.sub(r"\s", "", doc_no or "")
    s = re.sub(r"[〔\[［【(（](20\d{2})[〕\]］】)）]", r"〔\1〕", s)
    return s.translate(str.maketrans({"(": "（", ")": "）", "[": "〔", "]": "〕",
                                      "［": "〔", "］": "〕", "【": "〔", "】": "〕"}))


def doc_no_hash(doc_no: str) -> str:
    """交付字段 doc_no_hash：规范化文号的 SHA-256 前 16 位（与 deid.py 同规则）。"""
    import hashlib
    return hashlib.sha256(doc_no_norm(doc_no).encode("utf-8")).hexdigest()[:16]


def subject_mention_of(rec: dict) -> str:
    """本人在正文中的原写法（供脱敏替换为"甲"）：决定表/元数据块/正文正则三路兜底。"""
    full = rec.get("text_full") or ""
    flat = flatten(full)
    table = table_cells(full)
    v = table.get("被处罚对象") or meta_block(flat).get("行政相对人")
    if v:
        return v.strip()
    m = re.search(r"(?:违法行为人|被处罚人)[:：]?([\u4e00-\u9fa5*＊xX×]{1,12})", flat)
    return m.group(1) if m else ""


def _flatten_map(full: str) -> tuple[str, list[int]]:
    """拍平文本 + 索引映射（与 flatten 同规则：去掉空白与竖线），供段回定位。"""
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(full):
        if ch.isspace() or ch == "|":
            continue
        chars.append(ch)
        idx.append(i)
    return "".join(chars), idx


def _relocate_segment(seg: str, full: str) -> tuple[str, bool]:
    """把段还原成 text_full 的连续子串，返回 (可直接写入的段, 是否成功)。

    实测（2026-10-16）：legacy 的事实段是在**拍平文本**（去空白）上抽出的，天然不是原文子串；
    直接写入会被契约判 segment_not_substring，正确做法是回定位到原文字符区间（保留原文换行/空格）。
    """
    seg = seg or ""
    if not seg.strip():
        return "", True
    if seg in full:
        return seg, True
    flat, idx = _flatten_map(full)
    flat_seg = "".join(ch for ch in seg if not ch.isspace() and ch != "|")
    pos = flat.find(flat_seg)
    if pos < 0 or not flat_seg:
        return "", False
    return full[idx[pos]: idx[pos + len(flat_seg) - 1] + 1], True


DATE_OK = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _clean_date(v) -> tuple[str, bool]:
    """日期字段落库前校验：格式与范围不合法则弃用（构建时会重新定位），返回 (值, 是否合法)。"""
    s = (v or "").strip()
    if not s:
        return "", True
    if not DATE_OK.match(s):
        return "", False
    y, mo = int(s[:4]), int(s[5:7])
    d = int(s[8:10]) if len(s) == 10 else 0
    if 1990 <= y <= 2035 and 1 <= mo <= 12 and (not d or 1 <= d <= 31):
        return s, True
    return "", False


def to_parsed1(rec: dict, *, batch: str, source: str) -> tuple[dict | None, str]:
    """legacy 解析记录 → parsed-1。返回 (记录, 排除原因)；排除原因非空时不产出该条。

    排除规则：source_type 不在契约枚举内（如刑事/民事判决书——v1 范围外，留在 legacy 输出），
    或 outcome.type 非空但不在枚举内且分级为 L1/L2（契约会判 error）。
    """
    st = rec.get("source_type", "")
    if st not in CONTRACT_SOURCE_TYPES:
        return None, f"source_type 不在契约枚举：{st}"
    q = rec.get("quality") or {}
    oc = rec.get("outcome") or {}
    tier = str(q.get("tier", ""))
    oc_type = oc.get("type") or ""
    if oc_type and oc_type not in CONTRACT_OUTCOME_TYPES and tier[:2] in ("L1", "L2"):
        return None, f"outcome.type 不在契约枚举：{oc_type}"

    full = rec.get("text_full") or ""
    b_date, b_ok = _clean_date(rec.get("behavior_date"))
    d_date, d_ok = _clean_date(rec.get("decision_date"))
    extra: dict = {"legacy": {k: v for k, v in rec.items() if k not in CONTRACT_TOP_FIELDS}}
    if not b_ok:
        extra.setdefault("invalid_dates", {})["behavior_date"] = rec.get("behavior_date")
    if not d_ok:
        extra.setdefault("invalid_dates", {})["decision_date"] = rec.get("decision_date")
    out: dict = {
        "record_version": "parsed-1",
        "id": rec.get("id", ""),
        "source": source,
        "batch": batch,
        "parser": PARSER_ID,
        "source_type": st,
        "source_ref": (f"法宝引证码 {rec['pkulaw_id']}" if rec.get("pkulaw_id")
                       else (rec.get("source_ref") or f"台账 {rec.get('id', '')}")),
        "doc_no": rec.get("doc_no", ""),
        "doc_no_hash": doc_no_hash(rec.get("doc_no", "")),
        "harvest_date": rec.get("harvest_date", ""),
        "deidentified": bool(rec.get("deidentified")),
        "behavior_date": b_date,
        "decision_date": d_date,
        "authority": rec.get("authority", ""),
        "region": "",  # legacy 的 region 是省份名或区划名，不是区划代码；统一进 province，构建时再补代码
        "province": rec.get("region") or province_of(rec.get("authority", "")),
        "law_version": oc.get("law_version") or "未知",
        "subject_mention": subject_mention_of(rec),
        "event_key": rec.get("event_key", ""),
        "text_full": full,
        "segmented": bool(rec.get("segmented")),
    }
    dropped = []
    for k in SEGMENT_KEYS:
        seg, ok = _relocate_segment(rec.get(k, ""), full)
        out[k] = seg
        if not ok:
            dropped.append(k)
    if dropped:
        extra["segments_not_in_full"] = dropped
        extra["segments_raw"] = {k: rec.get(k, "") for k in dropped}

    out["outcome"] = {
        "type": oc_type,
        "detention_days": int(oc.get("detention_days") or 0),
        "fine": float(oc.get("fine") or 0),
        "detention_not_executed": oc.get("detention_not_executed") or "否",
        "confiscation": oc.get("confiscation") or "",
        "articles": list(oc.get("articles") or []),
        "stated_circumstances": list(oc.get("stated_circumstances") or []),
        "law_version": oc.get("law_version") if oc.get("law_version") in CONTRACT_LAW_VERSIONS else "",
    }
    oc_extra = {k: v for k, v in oc.items() if k not in CONTRACT_OUTCOME_FIELDS}
    if oc_extra:
        extra["outcome"] = oc_extra
    rv = rec.get("review") or {}
    review_result = rv.get("result") or "无"
    out["review"] = {
        "result": review_result if review_result in CONTRACT_REVIEW_RESULTS else "无",
        "changed_outcome": rv.get("changed_outcome") or {},
    }
    facts = out.get("text_facts") or ""
    conclusion = [w for w in CONCLUSION_WORDS if w in facts]
    out["quality"] = {
        "tier": tier,
        "in_scope": not tier.startswith("L3"),
        "completeness": {"has_amount": bool(q.get("has_amount")),
                         "has_outcome": bool(q.get("has_outcome"))},
        "parse_warnings": list(q.get("parse_warnings") or []),
        "form": q.get("form", ""),
        "gambling": ("是" if tier[:2] in ("L1", "L2")
                     else ("否" if "非赌博" in str(q.get("tier_reason", "")) or "民事" in str(q.get("tier_reason", ""))
                           else "待定")),
        "facts_contains_conclusion": bool(conclusion),
    }
    q_extra = {k: v for k, v in q.items()
               if k not in ("tier", "has_amount", "has_outcome", "parse_warnings", "form")}
    if q_extra:
        extra["quality"] = q_extra
    out["extra"] = extra
    return out, ""


def cmd_parsed1(args) -> None:
    """legacy 解析产物 → parsed-1（统一中间格式 L1）→ parsed/pkulaw/<批次>/records.jsonl。

    一个批次一个文件（契约）；枚举外类型（刑事/民事判决书）排除并记入 stats；逐条内嵌自检。
    """
    sources = [Path(x) for x in args.sources]
    batch = batch_tag(args.batch)
    out = Path(args.out) if args.out else DATA_DIR / "parsed" / "pkulaw" / batch
    out.mkdir(parents=True, exist_ok=True)
    if (out / "records.jsonl").exists() and not args.force:
        raise SystemExit(f"拒绝写入：{out / 'records.jsonl'} 已存在（--force 覆盖）")

    records: list[dict] = []
    excluded: list[dict] = []
    per_source: dict[str, int] = {}
    for src in sources:
        n = 0
        for fname in ("admin_cases.jsonl", "admin_outcomes_only.jsonl",
                      "admin_needs_review.jsonl", "pkulaw_out_of_scope.jsonl"):
            for rec in _read_jsonl(src / fname):
                n += 1
                source = SOURCE_OF_LIB["apy"]
                if rec.get("source_type") in ("行政判决书", "刑事判决书", "民事判决书"):
                    source = SOURCE_OF_LIB["pfnl"]
                got, why = to_parsed1(rec, batch=batch, source=source)
                if got is None:
                    excluded.append({"id": rec.get("id", ""), "doc_no": rec.get("doc_no", ""),
                                     "reason": why})
                    continue
                records.append(got)
        per_source[src.name] = n
    if records:
        _write_jsonl_atomic(out / "records.jsonl", records)
    else:
        (out / "records.jsonl").unlink(missing_ok=True)  # 全被排除的批次不留空文件

    issues = _self_check(records)
    stats = {
        "batch": batch, "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": per_source, "input": sum(per_source.values()), "records": len(records),
        "excluded": excluded,
        "tier": dict(Counter((r.get("quality") or {}).get("tier", "?") for r in records)),
        "events": len({r.get("event_key") for r in records if r.get("event_key")}),
        "self_check": issues,
    }
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    registry_add("L1", out, records=len(records), producer="collect/pkulaw_ingest.py parsed1",
                 pipeline_version="parsed-1", status="现行",
                 note=f"统一中间格式；来源 {', '.join(per_source)}")
    report(f"parsed-1 产出：{len(records)} 条（排除 {len(excluded)}）→ {out / 'records.jsonl'}")
    report(f"  分级：{stats['tier']}｜独立事件 {stats['events']}")
    for e in excluded:
        report(f"  排除：{e['doc_no'] or e['id']}（{e['reason']}）")
    if issues:
        for code, s in issues.items():
            report(f"  自检 {s['level']} {code}: {s['count']} 例：{', '.join(s['ids'][:3])}")
    else:
        report("  自检：零 error / 零 warn")


def _self_check(records: list[dict]) -> dict:
    """内嵌契约自检（justilaw-api/app/discretion/records.py 的 check_parsed）。

    读不到契约模块时跳过（返回 {}）——命令行仍可用外部自检：
      cd justilaw-api && python -m app.discretion.records check <records.jsonl> --layer parsed
    """
    api_root = HERE.parents[2] / "justilaw-api"
    try:
        if str(api_root) not in sys.path:
            sys.path.insert(0, str(api_root))
        from app.discretion.records import check_parsed, summarize  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return {}
    by_id = {}
    for r in records:
        iss = check_parsed(r)
        if iss:
            by_id[r.get("id", "?")] = iss
    out = summarize(by_id)
    return {k: {"level": v["level"], "count": v["count"], "message": v["message"], "ids": v["ids"]}
            for k, v in out.items()}


# ---------- 中文数字与金额 ----------

CN = {"〇": 0, "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
      "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
NUM = r"[\d,，.]+|[〇零一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万]+"


def cn2int(s: str) -> int | None:
    """中文/大写/阿拉伯数字 → 整数（三百→300、1382→1382、两千→2000）；无法解析返回 None。"""
    s = (s or "").replace(",", "").replace("，", "").replace("整", "").strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    if re.fullmatch(r"\d+\.0*", s):
        return int(float(s))
    if not s or any(ch not in CN and ch not in UNIT and ch != "万" for ch in s):
        return None
    total = section = digit = 0
    for ch in s:
        if ch in CN:
            digit = CN[ch]
        elif ch in UNIT:
            section += (digit or 1) * UNIT[ch]
            digit = 0
        elif ch == "万":
            total += (section + digit) * 10000
            section = digit = 0
    return total + section + digit


def cn_num_to_arabic_article(s: str) -> str:
    """条号统一成中文数字写法（data-spec §1.4 的 '治安管理处罚法第七十条'）：第82条 → 第八十二条。"""
    m = re.fullmatch(r"第?(\d{1,4})条", s.strip())
    if not m:
        return s
    n = int(m.group(1))
    if n == 0:
        return s
    cn = "零一二三四五六七八九"
    out = ""
    if n >= 1000:
        out += cn[n // 1000] + "千"
        n %= 1000
    if n >= 100:
        out += cn[n // 100] + "百"
        n %= 100
    if n >= 10:
        if n // 10 > 1:
            out += cn[n // 10]
        out += "十"
        n %= 10
    if n:
        out += cn[n]
    return "第" + out + "条"


# ---------- 日期 ----------

def parse_date(s: str) -> str:
    """'2025.12.29' / '2025-12-29' / '2025年12月29日' / '二〇二五年十二月二十九日' → '2025-12-29'。"""
    s = (s or "").strip()
    m = re.search(r"(\d{4})[.\-/年](\d{1,2})[.\-/月]?(\d{1,2})?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}" if d else f"{y}-{mo:02d}"
    m = re.search(r"([〇零一二三四五六七八九]{4})年([〇零一二三四五六七八九十]{1,3})月([〇零一二三四五六七八九十]{1,3})日", s)
    if m:
        y = m.group(1).translate(str.maketrans("〇零一二三四五六七八九", "00123456789"))
        mo = cn2int(m.group(2)) or 0
        d = cn2int(m.group(3)) or 0
        return f"{y}-{mo:02d}-{d:02d}"
    return ""


# ---------- 目录列表 ----------

CATALOG_FIELDS = ["序号", "标题", "执法机关", "发文案号", "公布日期", "行政相对人",
                  "执法依据", "处罚种类", "执法地域", "原文链接", "罚没总金额（万元）"]
# 司法案例库的目录表是完全另一套列（实测 2026-10-16）——两套合起来当"已知列名"用来自动找表头行
CASE_FIELDS = ["序号", "标题", "审理程序", "案由", "文书类型", "审理法院", "案件字号", "审结日期", "省份"]
KNOWN_COLUMNS = set(CATALOG_FIELDS) | set(CASE_FIELDS)
FOOTER_MARKS = ("©", "北大法宝", "扫码", "法宝快讯")
DATE_FIELDS = ("公布日期", "审结日期")
PROVINCES = ("北京市 天津市 上海市 重庆市 河北省 山西省 辽宁省 吉林省 黑龙江省 江苏省 浙江省 安徽省 福建省 "
             "江西省 山东省 河南省 湖北省 湖南省 广东省 海南省 四川省 贵州省 云南省 陕西省 甘肃省 青海省 "
             "台湾省 内蒙古自治区 广西壮族自治区 西藏自治区 宁夏回族自治区 新疆维吾尔自治区").split()


def read_table(path: Path) -> list[list[str]]:
    """读目录表：.xls 用 xlrd（BIFF8，纯 Python，无需装 Excel）；.csv 直接读（utf-8-sig）。

    .xls 优先用 xlrd 而不是 Excel COM：COM 在批量/无人值守时会因受保护视图或残留进程卡死（实测踩过）。
    `pkulaw_xls2csv.ps1` 只在没有 xlrd 的机器上用。
    """
    if path.suffix.lower() in {".xls", ".xlsx"}:
        import xlrd  # pip install xlrd（只支持 .xls；.xlsx 请先另存为 CSV）

        wb = xlrd.open_workbook(str(path))
        out: list[list[str]] = []
        for sh in wb.sheets():
            for i in range(sh.nrows):
                out.append([str(sh.cell_value(i, j)).strip() for j in range(sh.ncols)])
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [list(r) for r in csv.reader(f)]


def province_of(text: str) -> str:
    """从法院全名/地域里取省级名：'湖南省溆浦县人民法院' → '湖南省'。"""
    for p in PROVINCES:
        if p in (text or ""):
            return p
    return ""


def parse_catalog(path: Path) -> tuple[dict, list[dict]]:
    """目录列表（行政执法库 / 司法案例库两种形态）→ (表头元信息, 数据行)。

    表头行按"已知列名出现 ≥3 个"识别，列名原样保留——子库新增列不需要改代码；
    页脚（版权、二维码）按标记截断，不混进数据。
    """
    grid = read_table(path)
    meta = {"catalog_file": path.name, "library": "", "search": "", "download_time": ""}
    header_at: int | None = None
    fields: list[str] = []
    for i, row in enumerate(grid):
        joined = ",".join(row)
        if not meta["library"] and "北大法宝" in joined:
            meta["library"] = (row[0] if row else "").strip()
        if "搜索条件" in joined:
            m = re.search(r"搜索条件[:：](.*?)(?:；|;|,|，|$)", joined)
            meta["search"] = (m.group(1) if m else joined).strip()
            mt = re.search(r"下载时间[:：]([\d\-/.]+)", joined)
            if mt:
                meta["download_time"] = parse_date(mt.group(1))
        if sum(1 for c in row if c.strip() in KNOWN_COLUMNS) >= 3:
            header_at, fields = i, [c.strip() for c in row]
            break
    if header_at is None:
        raise SystemExit(f"{path}: 找不到字段名行（已知列名 ≥3 个），不是法宝目录列表导出？")

    data: list[dict] = []
    for row in grid[header_at + 1:]:
        cells = [c.strip() for c in row]
        joined = "".join(cells)
        if not joined or any(joined.startswith(mk) for mk in FOOTER_MARKS):
            continue
        rec = {f: (cells[j] if j < len(cells) else "") for j, f in enumerate(fields) if f}
        if not (rec.get("标题") or rec.get("发文案号") or rec.get("案件字号")):
            continue
        for df in DATE_FIELDS:
            if rec.get(df):
                rec[df] = parse_date(rec[df])
        amount = rec.get("罚没总金额（万元）", "")
        if "罚没总金额（万元）" in rec:
            rec["罚没总金额_元"] = int(round(float(amount) * 10000)) if re.fullmatch(r"\d+(\.\d+)?", amount or "") else None
        # 省份规范化：行政执法库给"执法地域"；司法案例库给法院全名（"湖南省溆浦县人民法院"）
        rec["省份规范"] = province_of(rec.get("执法地域", "")) or province_of(rec.get("省份", ""))
        data.append(rec)
    return meta, data


def catalog_stats(rows: list[dict]) -> dict:
    """按子库自适应统计——用来决定下一批下什么（省域普查、法条版本分片、案由分片）。"""
    stats: dict = {"件数": len(rows)}
    if any(r.get("执法依据") for r in rows):
        law = Counter()
        for r in rows:
            basis = r.get("执法依据", "")
            ver = "新法" if ("2025" in basis and "修订" in basis) else ("旧法" if "2012" in basis else "未知")
            art_m = re.search(r"第\s*(\d+)\s*条", basis)
            label = cn_num_to_arabic_article("第" + art_m.group(1) + "条") if art_m else "未识别"
            law[f"{ver} {label}"] += 1
        stats["按法律版本与法条"] = dict(law.most_common())
    if any(r.get("案由") for r in rows):
        stats["按案由（一级）"] = dict(Counter(
            (r.get("案由", "").split("/")[0].split(">")[0] or "未知") for r in rows).most_common())
        stats["按案由（末级）"] = dict(Counter(
            (r.get("案由", "").rstrip(";；").split(">")[-1] or "未知") for r in rows).most_common())
        stats["按文书类型"] = dict(Counter(r.get("文书类型", "") or "未知" for r in rows).most_common())
    if any(r.get("处罚种类") for r in rows):
        stats["按处罚种类"] = dict(Counter(r.get("处罚种类", "") or "未知" for r in rows).most_common())
    stats["按省份"] = dict(Counter(r.get("省份规范") or "未知" for r in rows).most_common(15))
    years = Counter((r.get("公布日期") or r.get("审结日期") or "未知")[:4] for r in rows)
    stats["按年份"] = dict(sorted(years.items()))
    return stats


# ---------- 文书文本获取 ----------

def _splice_prefix_artifact(s: str) -> str:
    """段内"截断前缀+全文"修复：扫描 20 字窗口，若其后 300 字内出现同一窗口且
    "被删片段恰是后一次全文的前缀"，则删除前一次截断部分（保留完整副本）。
    实测两种形态：① 伪影在段首（"…院内，王2026年…"）；② 折行后段首带标题（"现查明2026年…"）。"""
    if len(s) < 60:
        return s
    changed = True
    while changed:
        changed = False
        i, n = 0, len(s)
        while i < n - 40:
            seg = s[i:i + 20]
            q = s.find(seg, i + 1, min(n, i + 300))
            if q > i and s[q:q + (q - i)] == s[i:q]:
                s = s[:i] + s[q:]
                changed = True
                break
            i += 1
    return s


def dedup_page_text(text: str) -> str:
    """清理法宝**源文档**自带的重复伪影（page 抓取与 PDF 导出件同样出现，实测 2026-10-16）：
    ① 整段精确重复（"…出生。…出生。"）；
    ② 段内"截断前缀+全文"（"…养猪院内，王2026年08月26日…"）；
    ③ 跨段碎片重复（全文之后又出现该句尾部、被拆成若干行）。
    ①②按行清理（保留完整副本），③按"连续行拼接若是其它整行的子串"判定并丢弃。对干净文本幂等。"""
    raw_lines = [l.strip() for l in (text or "").split("\n")]
    lines: list[str] = []
    for s in raw_lines:
        if len(s) >= 24 and len(s) % 2 == 0 and s[: len(s) // 2] == s[len(s) // 2:]:
            s = s[: len(s) // 2]  # ① 半段精确重复
        s = _splice_prefix_artifact(s)  # ② 截断前缀：保留后一次完整副本
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
            hit = any(k != i and len(o) >= max(len(seg) + 20, 40) and seg in o
                      for k, o in enumerate(lines) if not (i <= k < i + span))
            if hit:  # ③ 跨段碎片：是其它整行的子串
                for k in range(i, i + span):
                    keep[k] = False
                break
    return "\n".join(l for l, k in zip(lines, keep) if k)


def _find_dup_spans(flat: str) -> list[tuple[int, int]]:  # pragma: no cover —— 保留供排查
    """（诊断用）在拍平文本上找重复伪影的删除区间。生产路径请用 折行+dedup_page_text。"""
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"(.{20,300}?)\1", flat):
        spans.append((m.end(1), m.end()))
    return spans


def doc_to_text(path: Path) -> tuple[str, str]:
    """'.doc/.docx/.pdf/.txt' → (文本, 取文本方式)；统一前置"折行还原"再"去伪影"（幂等）。

    各引擎输出都有硬换行（PDF 版面宽 / antiword ~80 列 / 页面 innerText 段落），先折行使
    "段落≈一行"，行级去伪影规则才能覆盖"截断前缀"跨行的情形。
    """
    text, how = _doc_to_text_raw(path)
    return dedup_page_text(_fold_wrapped_lines(text)), how


def _doc_to_text_raw(path: Path) -> tuple[str, str]:
    """.doc 优先 antiword，退回 Word COM；.pdf 走 PyMuPDF/pypdf 并还原元数据排版。"""
    suf = path.suffix.lower()
    if suf in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace"), "plain"
    if suf == ".docx":
        import docx  # python-docx：按段落 + 表格单元格拼接

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(c.text.replace("\n", " ").strip() for c in row.cells))
        return "\n".join(parts), "python-docx"
    if suf == ".doc":
        if shutil.which("antiword"):
            out = subprocess.run(["antiword", str(path)], capture_output=True)
            if out.returncode == 0 and out.stdout.decode("utf-8", "replace").strip():
                return out.stdout.decode("utf-8", "replace"), "antiword"
        text = _doc_via_word_com(path)
        if text:
            return text, "word-com"
        raise RuntimeError(f"{path}: .doc 取文本失败（antiword 与本机 Word 都不可用）")
    if suf == ".pdf":  # 法宝"下载PDF"导出件（作业台默认原件形态）
        text, engine = _pdf_to_text(path)
        return text, f"pdf:{engine}"
    raise ValueError(f"不支持的扩展名：{path.suffix}")


def _pdf_to_text(path: Path) -> tuple[str, str]:
    """PDF 取文本三链（本机工具探查 2026-10-16）：PyMuPDF(fitz) → pdftotext -layout（poppler）
    → pypdf。统一做"值/标签"换序（折行与去伪影在 doc_to_text 统一处理）。返回 (文本, 引擎名)。"""
    raw = ""
    engine = ""
    try:
        import fitz  # PyMuPDF

        with fitz.open(str(path)) as doc:
            raw = "\n".join(page.get_text() for page in doc)
        engine = "fitz"
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw.strip() and shutil.which("pdftotext"):
        try:
            out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                                 capture_output=True, timeout=120)
            if out.returncode == 0 and out.stdout.strip():
                raw = out.stdout.decode("utf-8", "replace")
                engine = "pdftotext"
        except Exception:  # noqa: BLE001
            pass
    if not raw.strip():
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        raw = "\n".join((p.extract_text() or "") for p in reader.pages)
        engine = "pypdf"
    return _fix_label_after_value(raw), engine


def _fold_wrapped_lines(text: str) -> str:
    """PDF 按版面宽度硬换行；把未以句末标点结束的行并入下一行，使"段落≈一行"，
    行级去伪影规则（dedup_page_text）才能生效（实测 527 号的"截断前缀"跨行）。"""
    out: list[str] = []
    buf = ""
    for raw_line in (text or "").split("\n"):
        s = raw_line.strip()
        if not s:
            if buf:
                out.append(buf)
                buf = ""
            continue
        buf = buf + s if buf else s
        if s.endswith(("。", "！", "？", "；")):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def _fix_label_after_value(text: str) -> str:
    """法宝 PDF 元数据页实测为两列排版、fitz 读序是"值在前、标签在后"（如 "公安\n主题分类："）。
    还原为"标签：值"，meta_block/table_cells 才能正常解析。"""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        single_colon_tail = (nxt.endswith("：") and 2 <= len(nxt) <= 14
                             and "：" not in nxt[:-1] and ":" not in nxt[:-1])
        if cur and single_colon_tail and not cur.endswith("："):
            out.append(f"{nxt}{cur}")
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _doc_via_word_com(path: Path) -> str:
    """Word COM 兜底（本机装了 Office）。导出为 UTF-8 文本再读回。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "out.txt"
        ps = (
            "$ErrorActionPreference='Stop';"
            "$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
            f"$d=$w.Documents.Open('{path}', $false, $true);"
            f"$d.SaveAs('{dst}', 2);"  # wdFormatText
            "$d.Close($false);$w.Quit()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, timeout=120)
        if dst.exists():
            raw = dst.read_bytes()
            for enc in ("utf-8", "gbk", "utf-16"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
    return ""


# ---------- 处罚决定书公示（行政执法库）解析 ----------

TABLE_ROWS = ["行政处罚决定书文号", "被处罚对象", "处罚事由", "处罚依据", "处罚结果",
              "处罚决定日期", "处罚机关"]
LAW_ALIAS = {"中华人民共和国治安管理处罚法": "治安管理处罚法", "治安管理处罚法": "治安管理处罚法"}


def _meta_value(body: str, label: str) -> str:
    """元数据块取值：从标签后取到"下一个字段名"或行尾（两种排版都容错：每字段一行 / 同一行内多字段）。"""
    m = re.search(rf"{label}\s*[:：]\s*", body)
    if not m:
        return ""
    rest = body[m.end():]
    nxt = re.search(rf"(?:{'|'.join(META_LABELS)}|{TABLE_ROWS[0]})\s*[:：]", rest)
    candidate = rest[: nxt.start()] if nxt else rest
    return re.sub(r"\s+", " ", candidate.split("\n")[0]).strip()


def pkulaw_id_from_name(name: str) -> str:
    """文件名里的法宝引证码：'…(FBM-CLI.ALE.47644244).doc' → 'CLI.ALE.47644244'。

    文件名带 FBM- 前缀、文档正文末尾写的是 'CLI.ALE.…'（实测），统一成后者作主键。
    """
    m = re.search(r"\((?:FBM)?-?(CLI(?:[.\-][A-Z]+)*\.\d+)\)", name)
    return m.group(1) if m else ""


def last_date(text: str) -> str:
    """全文最后一个"像落款"的日期——落款日期在文末（取窗口内首个日期会命中出生日期，实测踩过）。

    2026-10-16 加固（实测两类垃圾日期）：
      - 门牌号"2058/2059"、编号"1342-05"会被旧式 `\\d{4}[.\\-/年]\\d{1,2}` 当日期 → 加年份范围校验（1990–2035）；
      - 落款中文写法"二○二三年十月十日"用的是 ○（U+25CB），旧字符类只收 〇（U+3007）→ 落款匹配失败、
        兜底抓到文中的旧日期/门牌 → 补齐 ○/0/零 与月日范围校验。
    """
    candidates: list[tuple[int, str]] = []
    for m in re.finditer(r"((?:19|20)\d{2})\s*[年.\-/]\s*(\d{1,2})(?:\s*[月.\-/]\s*(\d{1,2})\s*日?)?",
                         text or ""):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if 1 <= mo <= 12 and (not d or 1 <= d <= 31):
            candidates.append((m.start(), f"{y}-{mo:02d}" + (f"-{d:02d}" if d else "")))
    cn = "〇○0零一二三四五六七八九"
    for m in re.finditer(rf"([{cn}]{{4}})年([{cn}十]{{1,3}})月([{cn}十]{{1,3}})日", text or ""):
        y = int(m.group(1).translate(str.maketrans(cn, "0000123456789")))
        mo, d = cn2int(m.group(2)) or 0, cn2int(m.group(3)) or 0
        if 1990 <= y <= 2035 and 1 <= mo <= 12 and 1 <= d <= 31:
            candidates.append((m.start(), f"{y}-{mo:02d}-{d:02d}"))
    if not candidates:
        return ""
    return max(candidates, key=lambda x: x[0])[1]


def pkulaw_id_from_text(text: str) -> str:
    """文档正文里的法宝引证码：【法宝引证码】CLI.ALE.47644244（导出文件被改名时靠它）。"""
    m = re.search(r"【法宝引证码】\s*(?:FBM)?-?(CLI(?:[.\-][A-Z]+)*\.\d+)", text)
    return m.group(1) if m else ""


# ---------- 叙述式处罚决定书（法宝执法库的常见形态，含事实） ----------

NARRATIVE_FACTS = re.compile(r"现查明[:：]?\s*(.*?)(?=以上事实有|以上事实|上述事实|根据|依照|依据|$)", re.S)
NARRATIVE_EVIDENCE = re.compile(r"(?:以上|上述)事实有(.*?)(?=根据|依照|依据|现决定|$)", re.S)
NARRATIVE_DECISION = re.compile(r"(?:根据|依照|依据)[^。]{0,120}?之规定[，,]?\s*(?:现)?决定[:：]?\s*(.*?)(?=被处罚人|如不服|当事人|本决定|$)", re.S)
NARRATIVE_BASIS = re.compile(r"((?:根据|依照|依据)[^。]{0,120}?之规定)")
DOC_NO_RE = re.compile(r"[（(]?[\u4e00-\u9fa5][公检法执][\u4e00-\u9fa5]{0,4}?[（(][^）)]{1,8}[）)][^\s，。]{0,24}?字[〔\[（(]?\s*\d{4}\s*[〕\]）)]?\s*第?\s*\d+\s*号")
SUBJECT_RE = re.compile(r"(?:违法行为人|被处罚人|违法嫌疑人)[：:]?\s*([\u4e00-\u9fa5*＊xX×]{2,12})")


def gambling_hint_of(raw: str, doc_no: str, facts: str, meta: dict, table: dict) -> bool:
    """是不是赌博案：先看标题（首个**非空**行，实测导出件的首行常为空）与关键字段，
    都不命中再兜底整篇——兜底会把"因赌博被处罚"这类前科误命中，但漏掉真赌博案的代价更大。
    """
    title = next((l.strip() for l in (raw or "").splitlines() if l.strip()), "")
    primary = flatten(title + doc_no + (facts or "") + meta.get("罚没情况", "")
                      + meta.get("处罚种类", "") + table.get("处罚事由", ""))
    if GAMBLING_MARK.search(primary):
        return True
    return bool(GAMBLING_MARK.search(flatten(raw)))


def flatten(text: str) -> str:
    """拍平：去掉表格竖线与**全部空白**。

    表格换行会把词拆进不同单元格（实测"之|规定"、"民|国"），填充空格还会让 `{0,160}` 这类
    长度窗口失效；中文文本不需要空格，所以抽取前一律拍平，正则才可靠。
    """
    return re.sub(r"\s+", "", (text or "").replace("|", " "))


def table_cells(body: str) -> dict[str, str]:
    """antiword 输出的表格 → {标签: 值}，**合并跨行续格**（续行的标签列是空的）。"""
    out: dict[str, str] = {}
    current = ""
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        label, value = cells[0], " ".join(c for c in cells[1:] if c)
        key = label or current
        if not key:
            continue
        current = key
        out[key] = flatten(out.get(key, "") + value)
    return out


# 三种落位（实测 d1/d2/d3/d4/d5/d6）：正文独立成篇 / 正文塞在表格"处罚结果"栏 / 只有摘要字段
FACTS_PATTERNS = (
    r"现查明[:：]?(.*?)(?=以上事实有|上述事实有|综上所述|行政处罚的种类和依据|根据|依照|依据|$)",
    r"主要违法事实[:：]?(.*?)(?=行政处罚的种类和依据|以上事实有|综上所述|根据|依照|依据|$)",
)
EVIDENCE_PATTERN = r"(?:以上|上述)事实有(.*?)(?=根据|依照|依据|现决定|综上所述|$)"
DECISION_PATTERN = r"(?:根据|依照|依据)[^。]{0,400}?之规定[，,]?(?:现)?决定[:：]?(.*?)(?=被处罚人|如不服|当事人|本决定|执行方式|履行方式|行政处罚的执行|$)"
GAMBLING_MARK = re.compile(r"赌博|赌资|赌具|开设赌场|六合彩|麻将|牌九|比鸡|押宝|炸金花|老虎机|赌博机")


def narrative_bits(text: str) -> dict:
    """全文级抽取事实/证据/决定——**在拍平后的文本上做，三种落位通吃。"""
    t = flatten(text)
    facts = evidence = decision = ""
    for pat in FACTS_PATTERNS:
        m = re.search(pat, t, re.S)
        if m and m.group(1).strip():
            facts = m.group(1).strip()
            break
    m = re.search(EVIDENCE_PATTERN, t, re.S)
    if m:
        evidence = m.group(1).strip()
    m = re.search(DECISION_PATTERN, t, re.S)
    if m:
        decision = m.group(1).strip()
    return {"facts": facts, "evidence": evidence, "decision": decision, "has_facts": bool(facts)}


def is_narrative(text: str) -> bool:
    """有没有可抽的事实段（三种落位通吃）——决定走叙述式还是纯摘要解析。"""
    return bool(narrative_bits(text)["has_facts"])


META_LABELS = ["主题分类", "处罚种类", "行政相对人", "执法级别", "执法机关", "执法地域",
               "公布日期", "发文案号", "罚没情况", "执法依据"]


def meta_block(flat: str) -> dict:
    """元数据块 10 项（法宝的结构化字段，位于文书开头；拍平后按"下一个字段名"截断）。"""
    labels = "|".join(META_LABELS)
    out: dict[str, str] = {}
    for label in META_LABELS:
        m = re.search(rf"{label}[:：](.*?)(?=(?:{labels})[:：]|行政处罚|原文链接|法宝引证码|$)", flat)
        out[label] = m.group(1).strip() if m else ""
    return out


# ---------- 司法案例批量导出（判决书 .doc） ----------

JUDG_META_LABELS = ["案由", "案号", "审理法官", "文书类型", "公开类型", "审理法院", "审结日期",
                    "案件类型", "审理程序", "权责关键词", "刑罚"]
JUDG_SECTIONS = re.compile(
    r"(当事人|审理经过|公诉机关、抗诉机关指控|检察院指控|公诉机关指控|被告辩称|被告及其辩护人辩称|"
    r"本院查明|经审理查明|本院认为|裁判结果|判决如下|落款)")
SECTION_ALIAS = {"经审理查明": "本院查明", "检察院指控": "指控", "公诉机关指控": "指控",
                 "公诉机关、抗诉机关指控": "指控", "被告及其辩护人辩称": "被告辩称",
                 "判决如下": "裁判结果"}


def parse_judgment_doc(text: str, *, filename: str = "") -> dict:
    """判决书 .doc → 与 parse_doc 同构的字段（facts/evidence/decision/reasoning 四段齐）。"""
    raw = re.split(r"©\s*北大法宝|\(c\)\s*北大法宝", text)[0]
    flat = flatten(raw)
    meta: dict[str, str] = {}
    labels = "|".join(JUDG_META_LABELS)
    for lab in JUDG_META_LABELS:
        m = re.search(rf"{lab}[:：](.*?)(?=(?:{labels})[:：]|//|$)", flat)
        meta[lab] = m.group(1).strip() if m else ""

    sections = judgment_sections(raw)

    facts = sections.get("本院查明") or sections.get("指控", "")
    decision = sections.get("裁判结果", "") or meta.get("刑罚", "")
    return {
        "pkulaw_id": pkulaw_id_from_name(filename) or pkulaw_id_from_text(text),
        "form": "判决书",
        "doc_no": meta.get("案号", ""),
        "subject": (re.search(r"(?:被告人|被告|原告)([\u4e00-\u9fa5某*]{1,8})", sections.get("当事人", "")) or
                    re.search(r"([\u4e00-\u9fa5]{1,6}某)", flat[:80]) or
                    re.search(r"(.+)", "")).group(1),
        "authority": meta.get("审理法院", ""),
        "region_text": "",
        "publish_date": "",
        "decision_date": parse_date(meta.get("审结日期", "")),
        "penalty_kinds": "",
        "fine_note": "",
        "basis_text": decision,
        "basis_meta": "",
        "result_text": decision,
        "subject_matter": meta.get("案由", ""),
        "source_url": (re.search(r"原文链接[:：]\s*(https?://\S+)", text) or [None, ""])[1],
        "body": raw.strip(),
        "facts": facts,
        "evidence": sections.get("证据", ""),
        "reasoning": sections.get("本院认为", ""),
        "decision": decision,
        "behavior_date_in_facts": parse_date(facts) or None,
        "gambling_hint": bool(GAMBLING_MARK.search(flat)),
        "judgment": {
            "case_type": meta.get("案件类型", ""),
            "case_reason": meta.get("案由", ""),
            "court": meta.get("审理法院", ""),
            "closed_date": parse_date(meta.get("审结日期", "")),
            "sentence": meta.get("刑罚", ""),
            "keywords": meta.get("权责关键词", ""),
            "procedure": meta.get("审理程序", ""),
        },
        "criminal_result": criminal_result(meta.get("刑罚", "") + decision),
    }


CRIM_RE = re.compile(r"(管制|拘役|有期徒刑)([\d〇零一二三四五六七八九十百]+)(年|个月)"
                     r"(?:([\d〇零一二三四五六七八九十]+)个月)?|(无期徒刑|死刑)")
FINE_RE = re.compile(r"罚金(?:人民币)?([\d,，.]+|[〇零一二三四五六七八九十百千万]+)元")


def criminal_result(text: str) -> dict:
    """刑事判决结果 → {主刑, 月数, 缓刑, 罚金}（v1 只作行刑边界统计，不进行政裁量训练）。"""
    t = flatten(text)
    m = CRIM_RE.search(t)
    months = 0
    main = ""
    if m:
        if m.group(5):                                   # 无期徒刑 / 死刑：没有月数
            main = m.group(5)
        else:
            n = cn2int(m.group(2)) or 0
            months = n * 12 if m.group(3) == "年" else n
            if m.group(4):                               # "有期徒刑一年四个月" 的尾数
                months += cn2int(m.group(4)) or 0
            main = m.group(1)
    f = FINE_RE.search(t)
    return {
        "main": main,
        "months": months,
        "suspended": bool(re.search(r"缓刑", t)),
        "fine": (cn2int(f.group(1)) or 0) if f else 0,
    }


SECTION_NAMES = {"当事人", "审理经过", "公诉机关、抗诉机关指控", "检察院指控", "公诉机关指控",
                 "被告辩称", "被告及其辩护人辩称", "本院查明", "经审理查明", "本院认为",
                 "裁判结果", "判决如下", "落款"}


def judgment_sections(raw: str) -> dict[str, str]:
    """判决书正文 → {小节: 内容}，**按"标题独占一行"识别**。

    拍平后做关键词切分会把正文里的"提及"当标题（实测：某判决里引用了"经审理查明"四字，
    于是事实段只抽到 4 个字）。导出件里标题独占一行，所以按行判更稳。
    """
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if cur and buf:
            seg = flatten(" ".join(buf))
            if len(seg) > len(out.get(cur, "")):
                out[cur] = seg

    for line in (raw or "").splitlines():
        stripped = line.strip()
        name = stripped.rstrip("：:").strip()
        if name in SECTION_NAMES:
            flush()
            cur = SECTION_ALIAS.get(name, name)
            buf = []
        elif cur is not None:
            buf.append(stripped)
    flush()
    return out


def is_judgment_doc(text: str) -> bool:
    flat = flatten(re.split(r"©\s*北大法宝", text)[0])
    return bool(re.search(r"文书类型[:：]", flat) and re.search(r"审理法院[:：]", flat)
                and re.search(r"案由[:：]", flat))


def parse_doc(text: str, *, filename: str = "") -> dict:
    """法宝文书（执法库）统一解析：元数据块 + 表格（可选）+ 全文事实段（可选）。

    产出与旧接口同构的字段；`form` 标注落位形态，便于统计与排错：
      叙述式-独立成篇 / 叙述式-结果栏内 / 字段式公示（无事实）
    """
    if is_judgment_doc(text):                     # 司法案例批量导出的判决书是另一套形态
        return parse_judgment_doc(text, filename=filename)
    raw = re.split(r"©\s*北大法宝|\(c\)\s*北大法宝", text)[0]
    # 拍平只用页脚之前的正文：页脚里的「引证码 50000001 + 页码 1/1」连起来会被当成日期（实测踩过）
    flat = flatten(raw)
    src_url = ""
    m = re.search(r"原文链接[:：]\s*(https?://\S+)", text)
    if m:
        src_url = m.group(1).strip()

    meta = meta_block(flat)
    table = table_cells(raw)
    bits = narrative_bits(raw)

    doc_no = table.get("行政处罚决定书文号") or table.get("行政处罚标题") or meta.get("发文案号", "")
    if not doc_no:
        m = re.search(DOC_NO_RE, flat)
        doc_no = m.group(0).lstrip("（()").strip() if m else ""
    authority = table.get("处罚机关") or meta.get("执法机关", "")
    subject = table.get("被处罚对象") or meta.get("行政相对人", "")
    if not subject:
        m = re.search(r"(?:违法行为人|被处罚人)([\u4e00-\u9fa5*＊xX×]{1,12})", flat)
        subject = m.group(1) if m else ""
    if not authority:
        m = re.search(r"([\u4e00-\u9fa5]{2,20}?(?:公安局|公安分局|分局|派出所))", flat)
        authority = m.group(1) if m else ""

    decision = bits["decision"]
    result_text = table.get("处罚结果", "") or decision
    if bits["has_facts"]:
        form = "叙述式-独立成篇" if not table.get("处罚结果") else "叙述式-结果栏内"
    else:
        form = "字段式公示"

    return {
        "pkulaw_id": pkulaw_id_from_name(filename) or pkulaw_id_from_text(text),
        "form": form,
        "doc_no": doc_no,
        "subject": subject,
        "authority": authority,
        "region_text": meta.get("执法地域", ""),
        "publish_date": parse_date(meta.get("公布日期", "")),
        "decision_date": parse_date(table.get("处罚决定日期", "")) or last_date(flat),
        "penalty_kinds": meta.get("处罚种类", ""),
        "fine_note": meta.get("罚没情况", ""),
        "basis_text": table.get("处罚依据", "") or decision or flat,
        "basis_meta": meta.get("执法依据", ""),
        "result_text": result_text,
        "subject_matter": table.get("处罚事由", "") or ("赌博" if GAMBLING_MARK.search(flat) else ""),
        "source_url": src_url,
        "body": raw.strip(),
        "facts": bits["facts"],
        "evidence": bits["evidence"],
        "behavior_date_in_facts": parse_date(bits["facts"]) or None,
        "decision": decision,
        "gambling_hint": gambling_hint_of(raw, doc_no, bits["facts"], meta, table),
    }


def parse_any_doc(text: str, *, filename: str = "") -> dict:
    """兼容旧调用名：统一走 parse_doc。"""
    return parse_doc(text, filename=filename)


# 旧名保留（判决书链路与外部脚本可能引用）
def parse_enforcement_doc(text: str, *, filename: str = "") -> dict:
    return parse_doc(text, filename=filename)


def parse_narrative_doc(text: str, *, filename: str = "") -> dict:
    return parse_doc(text, filename=filename)


def law_version_raw(*texts: str) -> str:
    """法宝"执法依据"里的版本字样：'…(2012修正) 第70条' / '…(2025修订) 第82条' → '2012修正' / '2025修订'。"""
    joined = "\n".join(t for t in texts if t)
    if "2025" in joined and "修订" in joined:
        return "2025修订"
    if "2012" in joined:
        return "2012修正"
    return ""


def _cited_law_before(text: str, pos: int, window: int = 24) -> str:
    """裸条号前若紧跟一个已闭合的《…》引用（其间无其他书名号/条号），返回所引法规名；否则空串。

    实测（无锡批 P-428/P-550）：'…根据《江苏省公共场所治安管理条例》第二十六条…之规定' 里的
    第二十六条被 assume_law 误套成"治安管理处罚法第二十六条"。
    """
    pre = (text or "")[max(0, pos - window):pos]
    if "》" not in pre:
        return ""
    tail = pre.rsplit("》", 1)[-1]
    if "《" in tail or "第" in tail:
        return ""
    head = pre.rsplit("》", 1)[0]
    return head.rsplit("《", 1)[-1].strip() if "《" in head else ""


_LAW_OR_ARTICLE_RE = re.compile(
    r"(《[^》]+》|[^\s第\d，。；：:]{4,30}?(?:法|条例|办法|规定|细则)(?:[（(][^）)]*[)）])?)"
    r"|(第\s*[\d一二三四五六七八九十百零]+\s*条)")


def articles_in_basis_meta(meta: str) -> list[str]:
    """'执法依据'结构化字段：按出现顺序跟踪"当前法律名"，只取治安管理处罚法的条文。

    实测（无锡批 P-439 等 13 条）：该字段并列多部法规（如"公安机关办理行政案件程序规定(2020修正) 第46条"），
    旧实现把所有裸条号都前缀成治安管理处罚法 → 法条误标（R2 方向）。
    """
    arts: list[str] = []
    current = ""
    for m in _LAW_OR_ARTICLE_RE.finditer(meta or ""):
        if m.group(1):
            name = re.sub(r"[（(]\d{4}(修正|修订|年)?[)）]", "", m.group(1)).strip("《》")
            current = LAW_ALIAS.get(name, "")
        elif current:
            arts.append(current + cn_num_to_arabic_article(m.group(2)))
    return arts


def parse_articles(basis_text: str, version_text: str = "", assume_law: str = "") -> tuple[list[str], str]:
    """→ (法条列表, 法律版本)。'《中华人民共和国治安管理处罚法》第七十条' → (['治安管理处罚法第七十条'], '旧法')。

    版本字样只在法宝结构化字段"执法依据"里（决定表的"处罚依据"没有），所以要单独传 version_text。
    法律版本统一成引擎在用的枚举（旧法 / 新法 / 未知；见 text-processing-spec §2），
    法宝原文写法（2012修正 / 2025修订）由 law_version_raw 另存 quality.law_version_raw 备查。
    """
    raw = law_version_raw(version_text, basis_text)
    law_version = {"2012修正": "旧法", "2025修订": "新法"}.get(raw, "")
    arts: list[str] = []
    for name, short in LAW_ALIAS.items():
        for m in re.finditer(rf"{name}[^第\n]*?(第\s*[\d一二三四五六七八九十百零]+\s*条)", basis_text):
            arts.append(short + cn_num_to_arabic_article(m.group(1)))
    if not arts:  # 《中华人民共和国治安管理处罚法》第七十条 这种书名号写法
        for m in re.finditer(r"《([^》]+)》\s*(第\s*[\d一二三四五六七八九十百零]+\s*条)", basis_text):
            if m.group(1) not in LAW_ALIAS:
                continue  # 非治安法引用（地方条例/程序规定等）不进 outcome.articles，避免法条误标
            arts.append(LAW_ALIAS[m.group(1)] + cn_num_to_arabic_article(m.group(2)))
    if not arts and version_text:
        # "执法依据"字段并列多部法规：按出现顺序跟踪法律名，只取治安法的条（实测无锡批误标 13 条）
        arts = articles_in_basis_meta(version_text)
    if not arts and assume_law:
        # 裸条号（实测 d4：处罚依据="第十一条、第八十二条"）——只在上下文能确定法律时补；
        # 紧跟非治安法《…》引用的裸条号不套 assume_law（无锡批实测）
        for m in re.finditer(r"第\s*([\d一二三四五六七八九十百零]+)\s*条", basis_text or ""):
            cited = _cited_law_before(basis_text, m.start())
            if cited and cited not in LAW_ALIAS:
                continue
            arts.append(assume_law + cn_num_to_arabic_article("第" + m.group(1) + "条"))
    return list(dict.fromkeys(arts)), law_version


def outcome_from(result_text: str, penalty_kinds: str, fine_note: str = "") -> dict:
    """处罚结果/处罚种类 → outcome（data-spec §1.4）。拘留天数、罚款额可能两者都写在一句里。"""
    r = result_text or ""
    det = [cn2int(x) for x in re.findall(rf"(?:行政拘留|拘留)\s*({NUM})\s*[日天]", r)]
    det = [d for d in det if d]
    merged = re.search(rf"合并执行[^，。；;]*?({NUM})\s*[日天]", r)
    fines = [cn2int(x) for x in re.findall(rf"罚款\s*(?:人民币)?\s*({NUM})\s*[元圆圓]", r) + re.findall(rf"罚款\s*({NUM})\s*[元圆圓]", fine_note)]
    fines = [x for x in fines if x]
    days = (cn2int(merged.group(1)) if merged else None) or (det[0] if det else 0)
    fine = fines[0] if fines else 0

    if re.search(r"不予处罚|不予行政处罚", r):
        ptype = "不予处罚"
    elif re.search(r"不构成违法", r):
        ptype = "不构成违法"
    elif re.search(r"移送|涉嫌犯罪", r):
        ptype = "移送刑事"
    elif days and fine:
        ptype = "拘留并处罚款"
    elif days:
        ptype = "拘留"
    elif fine:
        ptype = "罚款"
    elif "警告" in r or "警告" in penalty_kinds:
        ptype = "警告"
    else:
        ptype = ""

    confiscation = ""
    if "没收" in penalty_kinds:
        confiscation = "、".join(p for p in re.split(r"[、,，]", penalty_kinds) if "没收" in p)
    return {
        "type": ptype,
        "detention_days": days,
        "detention_items": det,
        "fine": fine,
        "detention_not_executed": "是" if re.search(r"不执行(?:行政)?拘留|不送(?:达)?拘留所|依法不执行", r) else "否",
        "confiscation": confiscation,
        "articles": [],
        "law_version": "",
        "stated_circumstances": [c for c in ("情节严重", "情节较轻", "从轻", "减轻", "从重", "认错认罚") if c in r],
    }


def has_amount(facts: str) -> bool:
    """事实段里有没有金额——信息完整度（规格 §2）与 D6 分流都靠它。

    规则与 harvest/parse.py 的 has_amount 保持一致（跨工作流不 import，靠同规则对齐）：
    金额词 + 25 字内出现数字，或直接出现"数字元"。
    """
    f = facts or ""
    return bool(re.search(rf"(赌资|赌注|输赢|抽头|抽水|筹码|充值|台费|彩金|获利|好处费|底注|封顶)[^。]{{0,25}}?({NUM})", f)
                or re.search(rf"({NUM})元", f))


def build_record(parsed: dict, *, manifest_id: str = "", harvest_date: str = "",
                 catalog_row: dict | None = None) -> dict:
    """解析结果 → data-spec v0.1 §1 的交付记录（脱敏前，deidentified=false）。

    两种形态共用：字段式公示（无事实 → 结果-only 层）与叙述式决定书（有"现查明"事实 → 金标候选）。
    """
    if parsed.get("form") == "判决书":
        return build_judgment_doc_record(parsed, manifest_id=manifest_id, harvest_date=harvest_date)
    assume_law = "治安管理处罚法" if re.search(r"治安管理处罚法|赌博|赌资", parsed.get("body", "")) else ""
    articles, law_version = parse_articles(parsed["basis_text"], parsed["basis_meta"], assume_law)
    # 优先用"决定"段算处罚（表格结果栏是整篇长文时，会先命中"违法经历"里的旧拘留天数——实测 d6）
    oc = outcome_from(parsed.get("decision") or parsed["result_text"] or parsed.get("body", ""),
                      parsed["penalty_kinds"], parsed["fine_note"])
    if oc["detention_not_executed"] == "否" and re.search(
            r"不执行(?:行政)?拘留|不送(?:达)?拘留所|依法不执行", parsed.get("body", "")):
        oc["detention_not_executed"] = "是"      # 实测 d2："已满七十周岁…不送拘留所执行"
    oc["articles"] = articles
    oc["law_version"] = law_version
    lv_raw = law_version_raw(parsed["basis_meta"], parsed["basis_text"])
    if str(parsed.get("form", "")).startswith("叙述式") and not oc["articles"]:
        # 叙述式的法条写在"根据《…》第X条之规定"里（在"现决定"之前），取法条与版本
        oc["articles"] = penalty_articles(parsed["body"], "")
    if not oc["law_version"]:                    # 没有版本字样时按条文推：70 条=旧法、82 条=新法
        joined = "".join(oc["articles"])
        if "第八十二条" in joined:
            oc["law_version"] = "新法"
        elif "第七十条" in joined:
            oc["law_version"] = "旧法"

    facts = parsed.get("facts", "")
    warns = []
    if not facts:
        warns.append("facts_missing")
    if not oc["type"]:
        warns.append("outcome_not_parsed")
    if not articles and not oc["articles"]:
        warns.append("articles_not_parsed")
    cat_fine = (catalog_row or {}).get("罚没总金额_元")
    try:
        cat_fine = int(float(cat_fine))
    except (TypeError, ValueError):
        cat_fine = None
    if cat_fine is not None and cat_fine > 0 and oc["fine"] != cat_fine:
        warns.append(f"fine_mismatch:doc={oc['fine']},catalog={cat_fine}")

    return {
        "id": manifest_id,                       # 台账 id（由 import_manual/manifest 分配）
        "pkulaw_id": parsed["pkulaw_id"],        # 法宝引证码：稳定主键，去重与复下都靠它
        "source_type": "处罚决定书" if facts else "执法公示",
        "source_ref": "文号哈希待生成（D3）｜原文链接见台账",
        "doc_no": parsed["doc_no"],
        "harvest_date": harvest_date or datetime.now().strftime("%Y-%m-%d"),
        "deidentified": False,                   # 走脱敏 SOP + R6 后才能置"是"
        "behavior_date": parsed.get("behavior_date_in_facts") or None,
        "decision_date": parsed["decision_date"],
        "authority": parsed["authority"],
        "region": parsed["region_text"],
        "text_full": parsed["body"],
        "segmented": bool(facts),
        "text_facts": facts,
        "text_evidence": parsed.get("evidence", ""),
        "text_reasoning": parsed.get("reasoning", ""),
        "text_decision": parsed.get("decision", "") or parsed["result_text"],
        "text_review": "",
        "outcome": oc,
        "review": {"result": "无", "changed_outcome": ""},
        "quality": {
            "form": parsed.get("form", ""),      # 叙述式-独立成篇 / 叙述式-结果栏内 / 字段式公示
            **tier_of(has_facts=bool(facts), has_outcome=bool(oc["type"]),
                      gambling=parsed.get("gambling_hint", True), in_scope=True),
            "has_amount": has_amount(facts),
            "has_outcome": bool(oc["type"]),
            "outcome_only": not facts,           # True → 只能进结果-only 层（D6）
            "law_version_raw": lv_raw,
            "parse_warnings": warns,
        },
        "event_key": event_key_of(parsed["authority"], facts),
        "event_hint": {"authority": parsed["authority"], "decision_date": parsed["decision_date"],
                       "doc_seq": _doc_seq(parsed["doc_no"])},
    }


def build_judgment_doc_record(parsed: dict, *, manifest_id: str = "", harvest_date: str = "") -> dict:
    """判决书（司法案例批量导出的 .doc）→ data-spec v0.1 §1 记录（脱敏前）。

    刑事判决 → `criminal` 块（主刑/月数/缓刑/罚金），只作行刑边界与后续扩展，不进行政裁量训练；
    民事判决 → `quality.in_scope=False`（全文检索的已知噪声，cmd_docs 会跳过）；
    行政判决 → 与 MCP 路径同义（原处罚在"本院查明"里复述，判决结论在"裁判结果"）。
    """
    j = parsed["judgment"]
    cr = parsed["criminal_result"]
    case_type, case_reason = j["case_type"], j["case_reason"]
    is_criminal = "刑事" in case_type or "罪" in case_reason
    is_civil = "民事" in case_type or "民事" in case_reason

    warns = []
    if not parsed["facts"]:
        warns.append("facts_missing")
    if not parsed["decision"]:
        warns.append("decision_not_found")

    oc = {"type": "", "detention_days": 0, "detention_items": [], "fine": 0,
          "detention_not_executed": "否", "confiscation": "", "articles": [],
          "law_version": "", "stated_circumstances": []}
    review = {"result": "无", "changed_outcome": ""}
    if is_criminal:
        oc["type"] = "刑事判决"
        oc["fine"] = cr["fine"]                       # 罚金（元）
    elif not is_civil:
        oc = outcome_from(parsed["facts"], "", "")     # 行政判决：原处罚在事实段里复述
        oc["articles"] = penalty_articles(parsed["facts"], parsed["decision"])
        joined = "".join(oc["articles"])
        oc["law_version"] = "新法" if "第八十二条" in joined else ("旧法" if "第七十条" in joined else "")
        r = parsed["decision"]
        review["result"] = ("维持" if "驳回" in r else "撤销" if "撤销" in r else
                           "变更" if "变更" in r else "确认违法" if "确认" in r and "违法" in r else "无")

    return {
        "id": manifest_id,
        "pkulaw_id": parsed["pkulaw_id"],
        "source_type": "刑事判决书" if is_criminal else ("民事判决书" if is_civil else "行政判决书"),
        "source_ref": "案号哈希待生成（D3）｜原文链接见台账",
        "doc_no": parsed["doc_no"],
        "harvest_date": harvest_date or datetime.now().strftime("%Y-%m-%d"),
        "deidentified": False,
        "behavior_date": parsed["behavior_date_in_facts"],
        "decision_date": j["closed_date"],
        "authority": j["court"],
        "region": province_of(j["court"]) or province_of(parsed["doc_no"]),
        "court": j["court"],
        "text_full": parsed["body"],
        "segmented": True,
        "text_facts": parsed["facts"],                 # 本院查明（或指控事实）
        "text_evidence": parsed["evidence"],
        "text_reasoning": "",
        "text_decision": parsed["decision"],           # 裁判结果
        "text_review": parsed["reasoning"],            # 本院认为
        "outcome": oc,
        "review": {**review, "judgment_date": j["closed_date"], "case_reason": case_reason,
                   "case_type": case_type, "procedure": j["procedure"]},
        "criminal": cr if is_criminal else None,
        "quality": {
            "form": "判决书",
            **tier_of(has_facts=bool(parsed["facts"]), has_outcome=bool(oc["type"]) or is_criminal,
                      gambling=parsed.get("gambling_hint", True), in_scope=not is_civil),
            "in_scope": not is_civil,                  # 民事判决是全文检索噪声，不进交付
            "case_type": case_type,
            "has_amount": has_amount(parsed["facts"]),
            "has_outcome": bool(oc["type"]),
            "outcome_only": False,
            "keywords": j["keywords"],
            "sentence": j["sentence"],
            "parse_warnings": warns,
        },
        "event_key": event_key_of(j["court"], parsed["facts"]),
        "event_hint": {"authority": j["court"], "behavior_date": parsed["behavior_date_in_facts"] or "",
                       "doc_seq": _doc_seq(parsed["doc_no"])},
    }


def event_key_of(authority: str, facts: str) -> str:
    """事件指纹：机关 + 事实段首个日期 + 赌资金额集合。

    同一次集中查处的多名当事人会各出一份决定书，这三项相同（实测：一次抓赌 5–8 份），
    门禁 §7 要求按事件分组划分，所以交付记录必须带这个键；批次报告也用它算"篇数→事件数"折算率。
    """
    f = facts or ""
    dates = re.findall(r"(\d{4}年\d{1,2}月\d{1,2}日)", f)
    money = re.findall(r"(?:赌资|资金|款)[^\d]{0,6}([\d,]+)\s*元", f) or re.findall(r"([\d,]{2,})\s*元", f)
    money_key = ",".join(sorted(set(money))) if money else "-"
    return f"{authority}|{dates[0] if dates else '-'}|{money_key}"


def tier_of(*, has_facts: bool, has_outcome: bool, gambling: bool, in_scope: bool) -> dict:
    """记录级分级——决定进哪个产物、能不能当训练原料。

    L1 金标候选：有事实段 + 处罚结果可解析 + 赌博范围内 → 训练/测试原料（`admin_cases.jsonl`）
    L2 结果-only：无事实但有结果 → 省份/年份分布校准、T-time 计数、跨源核对（`admin_outcomes_only.jsonl`，D6）
    L3 范围外：非赌博、民事判决、结果不可解析且无事实（全文检索噪声）→ 单独存放，不进任何训练（`pkulaw_out_of_scope.jsonl`）
    L4 待核：有事实但结果解析失败（或反之）→ 人工过一眼（`admin_needs_review.jsonl`）
    """
    if not in_scope:
        return {"tier": "L3-范围外", "tier_reason": "非赌博/民事判决"}
    if not gambling:
        return {"tier": "L3-范围外", "tier_reason": "赌博特征未命中"}
    if has_facts and has_outcome:
        return {"tier": "L1-金标候选", "tier_reason": "有事实段且结果可解析"}
    if has_outcome:
        return {"tier": "L2-结果only", "tier_reason": "无事实段（公示原文即无案情）"}
    if has_facts:
        return {"tier": "L4-待核", "tier_reason": "有事实但结果未解析"}
    return {"tier": "L3-范围外", "tier_reason": "既无事实也无结果"}


def _doc_seq(doc_no: str) -> str:
    m = re.findall(r"(\d{3,})", doc_no or "")
    return m[-1] if m else ""


# ---------- 司法案例库：法院判决书（另一条数据线） ----------

# 法宝司法案例记录是 29 个字段的**已分段**结构（2026-10-16 实测，MCP case-keyword 返回）：
#   TrialAfter 审理经过 / PlaintiffClaims 原告诉称 / DefenseViewpoint 被告辩称 /
#   Ascertain 经审理查明 / Identified 本院认为 / RefereeResult 判决结果 / RefereeBasis 裁判依据
#   另有 Category 案由层级、CaseFlag 案号、Court 法院、LastInstanceDate 审结日期、CriminalPunish 主题标签
# 与 data-spec 的对应：Ascertain→text_facts、Identified→text_review、RefereeBasis→outcome.articles、
# RefereeResult→review.result；**原行政处罚的结果写在 Ascertain 里**（判决书复述原处罚）。
# 注意：当事人是**真名**（不同于执法公示的"陈*英"），脱敏不能省。

JUDGMENT_CASE_TYPES = {"行政一审": "行政判决书", "行政二审": "行政判决书", "行政再审": "行政判决书",
                       "刑事一审": "刑事判决书", "刑事二审": "刑事判决书"}
AUTHORITY_RE = re.compile(r"被告([\u4e00-\u9fa5]{2,24}?(?:公安局|公安分局|分局|派出所|人民政府|管委会))")
DATE_CN = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
PKULAW_CASE_HASH = re.compile(r"/pfnl/([0-9a-f]{16,})bdfb\.html")


def pkulaw_case_id(record: dict) -> str:
    """判决书的稳定主键：原文链接里的 pfnl 哈希（如 9445…bdfb.html）。"""
    m = PKULAW_CASE_HASH.search(record.get("Url") or "")
    return m.group(1) if m else ""


def authority_from_judgment(record: dict) -> str:
    """从"被告××公安局辩称"这类句子里取作出原处罚的机关。判决书没有单列被告字段。"""
    for field in ("DefenseViewpoint", "Ascertain", "PlaintiffClaims", "Title"):
        text = record.get(field) or ""
        m = AUTHORITY_RE.search(text)
        if m:
            return m.group(1)
    return ""


def dates_from_facts(facts: str) -> list[str]:
    return [f"{y}-{int(m):02d}" + (f"-{int(d):02d}" if d else "") for y, m, d in DATE_CN.findall(facts or "")]


def decision_date_from_facts(facts: str) -> str:
    """原处罚决定日期：判决书里常写"同日/当日……作出……处罚决定"，所以要回溯最近的前置日期。"""
    facts = facts or ""
    m = re.search(r"(?:作出|下达|出具)[^。；]{0,60}?决定", facts)
    if not m:
        return ""
    before = facts[max(0, m.start() - 40): m.start()]
    prior = list(DATE_CN.finditer(facts[: m.start()]))
    if re.search(r"同日|当日", before) and prior:
        y, mo, d = prior[-1].groups()
        return f"{y}-{int(mo):02d}" + (f"-{int(d):02d}" if d else "")
    nxt = DATE_CN.search(facts[m.end(): m.end() + 160])
    if nxt:
        y, mo, d = nxt.groups()
        return f"{y}-{int(mo):02d}" + (f"-{int(d):02d}" if d else "")
    if prior:
        y, mo, d = prior[-1].groups()
        return f"{y}-{int(mo):02d}" + (f"-{int(d):02d}" if d else "")
    return ""


PENALTY_ARTICLES_RE = re.compile(r"根据[^。；]{0,60}?治安管理处罚法[^。；]{0,24}?(第[一二三四五六七八九十百]+条)")
PENALTY_TIER_ARTICLES = ("第七十条", "第八十二条", "第十九条", "第二十条", "第二十一条", "第二十二条", "第二十三条")


def penalty_articles(facts: str, basis: str) -> list[str]:
    """**处罚依据**（不是法院的裁判依据）。

    判决书的 RefereeBasis 还含法院判决所依据的程序条文（如行政诉讼法第六十九条、治安管理处罚法
    第九十三条举证规则），直接拿来当 outcome.articles 会污染标签。所以优先从事实段
    "根据《…治安管理处罚法》第X条…作出…处罚决定"里取；取不到再退回裁判依据里的处罚性条款。
    """
    arts: list[str] = []
    for m in PENALTY_ARTICLES_RE.finditer(facts or ""):
        arts.append("治安管理处罚法" + cn_num_to_arabic_article(m.group(1)))
    if not arts:
        for a in parse_articles(basis or "")[0]:
            if any(t in a for t in PENALTY_TIER_ARTICLES):
                arts.append(a)
    return list(dict.fromkeys(arts))


def build_judgment_record(record: dict, *, manifest_id: str = "", harvest_date: str = "") -> dict:
    """法宝司法案例记录（判决书）→ data-spec v0.1 §1 交付记录（脱敏前）。"""
    facts = record.get("Ascertain") or ""
    reasoning = record.get("Identified") or ""
    result = record.get("RefereeResult") or ""
    basis = record.get("RefereeBasis") or ""
    case_type = record.get("CaseClassName") or ""
    court = record.get("Court") or ""
    case_flag = record.get("CaseFlag") or ""

    # 原处罚结果：判决书在"经审理查明"里复述（"对原告行政拘留12日，并处罚款1900元；收缴赌资2664元"）
    oc = outcome_from(facts, "", "")
    oc["articles"] = penalty_articles(facts, basis)
    oc["law_version"] = "新法" if "第八十二条" in "".join(oc["articles"]) else (
        "旧法" if "第七十条" in "".join(oc["articles"]) else "")
    oc["stated_circumstances"] = [c for c in ("情节严重", "情节较轻", "从轻", "减轻", "从重", "认错认罚")
                                  if c in (reasoning + facts)]

    # 判决结论：驳回（维持）/ 撤销 / 变更 / 确认违法
    if re.search(r"驳回", result):
        rv = "维持"
    elif re.search(r"撤销", result):
        rv = "撤销"
    elif re.search(r"变更", result):
        rv = "变更"
    elif re.search(r"确认[^。；]{0,24}?违法", result):
        rv = "确认违法"
    else:
        rv = "无"
    changed = ""
    if rv == "变更":
        c = outcome_from(result, "", "")
        changed = f"拘留{c['detention_days']}日，罚款{c['fine']}元" if (c["detention_days"] or c["fine"]) else ""

    ds = dates_from_facts(facts)
    decision_date = decision_date_from_facts(facts)

    warns = []
    if not facts:
        warns.append("facts_missing")
    if not oc["type"]:
        warns.append("outcome_not_parsed")
    if not oc["articles"]:
        warns.append("articles_not_parsed")
    if not decision_date:
        warns.append("decision_date_not_found")
    if not oc["detention_days"] and not oc["fine"]:
        warns.append("no_penalty_amounts")

    return {
        "id": manifest_id,
        "pkulaw_id": pkulaw_case_id(record),
        "source_type": "行政判决书" if case_type.startswith("行政") else "刑事判决书",
        "source_ref": "案号哈希待生成（D3）｜原文链接见台账",
        "doc_no": case_flag,
        "harvest_date": harvest_date or datetime.now().strftime("%Y-%m-%d"),
        "deidentified": False,                      # 判决书是**真名**，必须走脱敏 SOP + R6
        "behavior_date": ds[0] if ds else None,     # 事实段首个日期（多为查处日），粒度待 D2 拍板
        "decision_date": decision_date or None,     # 原处罚决定日期（判决书复述取得）
        "authority": authority_from_judgment(record),
        "region": province_of(court) or province_of(case_flag),
        "court": court,
        "text_full": (facts + "\n" + reasoning + "\n" + result).strip(),
        "segmented": True,                          # 法宝已按语义分段，无需自切
        "text_facts": facts,                        # 经审理查明（含原处罚复述）
        "text_evidence": "",
        "text_reasoning": "",                       # 原处罚机关的裁量说明，判决书里通常没有
        "text_decision": result,
        "text_review": reasoning,                   # 本院认为 = 法院审查意见（data-spec text_review）
        "outcome": oc,                              # 原行政处罚（不是判决结果！）
        "review": {"result": rv, "changed_outcome": changed,
                   "judgment_date": parse_date(record.get("LastInstanceDate") or ""),
                   "case_grade": "／".join(record.get("CaseGrade") or []),
                   "category": "／".join(record.get("Category") or [])},
        "quality": {
            "has_amount": has_amount(facts),
            "has_outcome": bool(oc["type"]),
            "outcome_only": False,
            "plaintiff_claims": record.get("PlaintiffClaims") or "",   # 原告主张（不入模型输入，留作出题）
            "trial_after": record.get("TrialAfter") or "",
            "criminal_punish_tags": record.get("CriminalPunish") or [],
            "parse_warnings": warns,
        },
        "event_hint": {"authority": authority_from_judgment(record), "behavior_date": ds[0] if ds else "",
                       "doc_seq": _doc_seq(case_flag)},
    }


# ---------- 子命令 ----------

def cmd_catalog(args) -> None:
    out = resolve_out(args.out, "catalog", batch_tag(getattr(args, "batch", "")))
    out.mkdir(parents=True, exist_ok=True)
    guard_outputs(out, "catalog", force=getattr(args, "force", False))
    meta, rows = parse_catalog(Path(args.xls))
    worklist = out / "worklist.csv"
    fields = list(rows[0].keys()) if rows else []
    for ff in ("法宝引证码", "已下全文"):
        if ff not in fields:
            fields.append(ff)
    with open(worklist, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r.setdefault("已下全文", "")
            w.writerow(r)
    stats = catalog_stats(rows)
    stats["表头元信息"] = meta
    (out / "catalog.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    report(f"目录解析：{len(rows)} 条 → {worklist}")
    report(f"  {meta['library']}｜搜索条件：{meta['search']}（下载时间 {meta['download_time']}）")
    for k, v in catalog_stats(rows).items():
        report(f"  {k}：{v}")


TIER_RANK = {"L1-金标候选": 0, "L2-结果only": 1, "L4-待核": 2, "L3-范围外": 3}


def record_rank(r: dict) -> tuple:
    """跨批去重时的"择优"排序：金标候选 > 结果-only > 待核 > 范围外；同级事实段更长优先。"""
    tier = r.get("quality", {}).get("tier", "")
    return (TIER_RANK.get(tier, 9), -len(r.get("text_facts") or ""), -len(r.get("text_full") or ""))


def doc_files(root: Path) -> list[Path]:
    """递归收集可解析文书；排除 Word 临时/锁文件（~$…，Word 打开文档时生成）与隐藏文件。

    实测踩坑：导出目录里混有 `~$….doc`（Word 锁文件），不排除会被当文书解析。
    """
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in DOC_EXTS:
            continue
        if p.name.startswith("~$") or p.name.startswith("."):
            continue
        out.append(p)
    return sorted(out)


def cmd_docs(args) -> None:
    docs_dir = Path(args.docs)
    out = resolve_out(args.out, "docs", batch_tag(args.batch, args.harvest_date))
    out.mkdir(parents=True, exist_ok=True)
    guard_outputs(out, "docs", force=args.force, append=args.append)
    files = doc_files(docs_dir)
    if not files:
        raise SystemExit(f"{docs_dir} 下没有可解析的文书（{sorted(DOC_EXTS)}）")

    by_no: dict[str, dict] = {}
    if args.worklist and Path(args.worklist).exists():
        with open(args.worklist, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                by_no[r.get("发文案号", "")] = r

    # 台账 id：按文件 SHA-256 与 manifest 对齐（原始文件先经 import_manual.py 入库）
    id_by_sha: dict[str, str] = {}
    if args.manifest and Path(args.manifest).exists():
        with open(args.manifest, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("sha256"):
                    id_by_sha[r["sha256"]] = r.get("id", "")

    records, counters, sha_lines = [], Counter(), []
    for p in files:
        text, how = doc_to_text(p)
        parsed = parse_any_doc(text, filename=p.name)     # 自动分派：叙述式 / 字段式公示
        cat = by_no.get(parsed["doc_no"])
        sha = sha256_path(p)
        rec = build_record(parsed, manifest_id=id_by_sha.get(sha, ""), harvest_date=args.harvest_date,
                           catalog_row=cat)
        rec["quality"]["text_source"] = how
        if args.manifest and not rec["id"]:
            rec["quality"]["parse_warnings"].append("not_in_manifest")  # 先跑 import_manual.py 入库
        records.append(rec)
        counters["total"] += 1
        counters[f"form:{rec['quality']['form']}"] += 1
        counters["in_worklist" if cat else "not_in_worklist"] += 1
        sha_lines.append(f"{sha}  {p.name}")

    # 同一文号的重复条目（法宝同一条记录常有两个标题变体）只留一条
    seen, uniq = set(), []
    for r in records:
        key = r["doc_no"] or r["pkulaw_id"]
        if key in seen:
            counters["duplicated"] += 1
            continue
        seen.add(key)
        uniq.append(r)
    records = uniq
    for r in records:
        for w in r["quality"]["parse_warnings"]:
            counters[f"warn:{w.split(':')[0]}"] += 1

    # 范围外：民事判决 + 非赌博 + 无事实且无结果（全文检索噪声），单独存放不进任何训练
    outside = [r for r in records if r["quality"].get("in_scope") is False
               or str(r["quality"].get("tier", "")).startswith("L3")]
    if outside:
        counters["skipped_out_of_scope"] = len(outside)
        records = [r for r in records if r not in outside]

    buckets = {"L1-金标候选": [], "L2-结果only": [], "L3-范围外": [], "L4-待核": []}
    for r in records:
        buckets.setdefault(r["quality"].get("tier", "L4-待核"), []).append(r)
    tier_counts = {k: len(v) for k, v in buckets.items() if v}
    cases, only = buckets.get("L1-金标候选", []), buckets.get("L2-结果only", [])

    tier_files = (("admin_cases.jsonl", cases), ("admin_outcomes_only.jsonl", only),
                  ("admin_needs_review.jsonl", buckets.get("L4-待核", [])))
    written: list[Path] = []
    appended: dict[str, int] = {}
    if args.append:
        # 合并模式：与既有产物按 引证码/文号 去重后合并（跨批累积用）
        if outside:
            merge_jsonl(out / "pkulaw_out_of_scope.jsonl", outside)
        for name, subset in tier_files:
            if subset:
                merge_jsonl(out / name, subset)
        for name, _ in tier_files:
            if (out / name).exists():
                written.append(out / name)
        # SHA256SUMS：按行合并去重（跨批保留全部文件指纹）
        old_sums = _read_text_lines(out / "SHA256SUMS")
        new_sums = sorted(set(old_sums) | set(sha_lines))
        (out / "SHA256SUMS").write_text("\n".join(new_sums) + "\n", encoding="utf-8")
    else:
        if outside:
            _write_jsonl_atomic(out / "pkulaw_out_of_scope.jsonl", outside)
        for name, subset in tier_files:
            if not subset:
                continue
            target = out / name
            _write_jsonl_atomic(target, subset)
            written.append(target)
        (out / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    # 回写工作清单：标记哪些已下全文（三天窗口里靠这张表决定"还差哪些"）
    if by_no and args.worklist and Path(args.worklist).exists():
        got = {r["doc_no"]: r["pkulaw_id"] for r in records if r["doc_no"]}
        with open(args.worklist, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        for ff in ("法宝引证码", "已下全文"):
            if ff not in fields:
                fields.append(ff)
        for row in rows:
            if row.get("发文案号") in got:
                row["法宝引证码"] = got[row["发文案号"]]
                row["已下全文"] = "是"
        with open(args.worklist, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        done = sum(1 for r in rows if r.get("已下全文") == "是")
        report(f"  工作清单已回写：{done}/{len(rows)} 条已下全文 ← {args.worklist}")

    stats_records = records
    if args.append:
        stats_records = []
        for name, _ in tier_files:
            stats_records.extend(_read_jsonl(out / name))
    facts_len = sorted(len(r["text_facts"]) for r in stats_records)
    stats = {
        "schema_version": SCHEMA_VERSION,
        "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "batch": args.batch or batch_tag("", args.harvest_date),
        "mode": "append" if args.append else "write",
        "counts": dict(counters),
        "tier": dict(Counter(r["quality"].get("tier", "?") for r in stats_records)),
        "facts_len_median": facts_len[len(facts_len) // 2] if facts_len else 0,
        "unique_events": len({r.get("event_key", "") for r in stats_records}),
        "event_yield": round(len({r.get("event_key", "") for r in stats_records}) / max(len(stats_records), 1), 3),
        "has_amount_ratio": round(sum(1 for r in stats_records if r["quality"]["has_amount"]) / max(len(stats_records), 1), 3),
        "missing_decision_date_ratio": round(
            sum(1 for r in stats_records if not r["decision_date"]) / max(len(stats_records), 1), 3),
        "outcome_only": sum(1 for r in stats_records if r["quality"].get("tier") == "L2-结果only"),
        "with_facts": sum(1 for r in stats_records if r["quality"].get("tier") == "L1-金标候选"),
        "outcome_types": dict(Counter(r["outcome"]["type"] or "未解析" for r in stats_records)),
        "law_versions": dict(Counter(r["outcome"]["law_version"] or "未知" for r in stats_records)),
        "files": [t.name for t in written],
    }
    (out / "pkulaw_ingest.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    forms = dict(Counter(r["quality"]["form"] for r in stats_records))
    tiers = dict(Counter(r["quality"].get("tier", "?") for r in stats_records))
    mode = "追加合并" if args.append else "写入"
    report(f"{mode} {len(records)} 份文书（合计 {len(stats_records)} 条；形态 {forms}）")
    report(f"  分级：{tiers}")
    report(f"  有事实（金标候选，A 类主力）：{stats['with_facts']} → admin_cases.jsonl")
    report(f"  无事实（结果-only，B 类，D6）：{stats['outcome_only']} → admin_outcomes_only.jsonl")
    report(f"  处罚类型分布：{stats['outcome_types']}")
    report(f"  法律版本分布：{stats['law_versions']}")
    report(f"  质量提示：{ {k: v for k, v in counters.items() if k.startswith('warn:')} }")
    report(f"  批次指标：事实段中位 {stats['facts_len_median']} 字｜含金额 {stats['has_amount_ratio']:.0%}"
           f"｜缺决定日期 {stats['missing_decision_date_ratio']:.0%}")
    report(f"  事件产出：{stats['unique_events']} 个独立事件 / {len(stats_records)} 篇（折算率 {stats['event_yield']:.0%}）")
    registry_add("L1-legacy", out, records=len(stats_records),
                 producer="collect/pkulaw_ingest.py docs", pipeline_version=SCHEMA_VERSION,
                 status="工作副本",
                 note=f"批次 {stats['batch']}；parsed-1 正本见 parsed/pkulaw/{stats['batch']}/")
    report(f"  产出目录：{out}（批次 {stats['batch']}；含 SHA256SUMS；已登 REGISTRY）")


def cmd_merge(args) -> None:
    """跨批次合并解析产物（择优去重）：多盒 L1/L2/L3/L4 → 一个唯一集合。

    去重键：法宝引证码 > 文号（_rec_key）；重复时按 record_rank 择优
    （金标候选 > 结果-only > 待核 > 范围外，同级事实段更长优先）。
    产出：out/<批次>/ 四个分级文件 + merge.stats.json（含重复明细 per_key）。
    """
    sources = [Path(x) for x in args.sources]
    out = resolve_out(args.out, "docs", batch_tag(args.batch))
    out.mkdir(parents=True, exist_ok=True)
    guard_outputs(out, "docs", force=args.force)

    best: dict[str, dict] = {}
    key_source: dict[str, str] = {}
    dup_log: list[dict] = []
    per_source: dict[str, int] = {}
    for src in sources:
        n = 0
        for f in ("admin_cases.jsonl", "admin_outcomes_only.jsonl",
                  "admin_needs_review.jsonl", "pkulaw_out_of_scope.jsonl"):
            for r in _read_jsonl(src / f):
                n += 1
                k = _rec_key(r)
                if k in best and record_rank(r) >= record_rank(best[k]):
                    dup_log.append({"key": k, "kept": key_source[k], "dropped": src.name})
                    continue
                if k in best:
                    dup_log.append({"key": k, "kept": src.name, "dropped": key_source[k]})
                best[k] = r
                key_source[k] = src.name
        per_source[src.name] = n

    buckets = {"L1-金标候选": [], "L2-结果only": [], "L3-范围外": [], "L4-待核": []}
    for k, r in best.items():
        buckets.setdefault(r.get("quality", {}).get("tier", "L4-待核"), []).append(r)
    names = (("admin_cases.jsonl", "L1-金标候选"), ("admin_outcomes_only.jsonl", "L2-结果only"),
             ("admin_needs_review.jsonl", "L4-待核"), ("pkulaw_out_of_scope.jsonl", "L3-范围外"))
    for fname, tier in names:
        if buckets.get(tier):
            _write_jsonl_atomic(out / fname, buckets[tier])
    events = {r.get("event_key", "") for r in best.values() if r.get("event_key")}
    stats = {
        "merged_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "batch": args.batch or batch_tag(""),
        "sources": {k: v for k, v in per_source.items()},
        "total_in": sum(per_source.values()), "unique": len(best),
        "tier": {t: len(v) for t, v in buckets.items() if v},
        "unique_events": len(events),
        "duplicates": dup_log,
        "key_source": key_source,
    }
    (out / "merge.stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    report(f"合并 {len(sources)} 个来源 → {out}")
    report(f"  输入 {stats['total_in']} 条 → 唯一 {stats['unique']} 条（去重 {len(dup_log)}）")
    report(f"  分级：{stats['tier']}｜独立事件 {len(events)}")
    for d in dup_log:
        report(f"  重复：{d['key']}（保留 {d['kept']}，丢弃 {d['dropped']}）")
    registry_add("L1-legacy", out, records=stats["unique"],
                 producer="collect/pkulaw_ingest.py merge", pipeline_version=SCHEMA_VERSION,
                 status="工作副本", note=f"跨批合并（去重 {len(dup_log)}）；并入 parsed-1 另行产出")


def cmd_cases(args) -> None:
    """司法案例记录 → 判决书规格 JSONL（未脱敏，产出与收割链路的 web_cases.pre_deid.jsonl 并列）。

    输入：MCP 响应 JSON（含 Data 数组）、JSONL、或目录（递归取 *.json/*.jsonl）。
    """
    src = Path(args.src)
    out = resolve_out(args.out, "cases", batch_tag(getattr(args, "batch", ""),
                                                   getattr(args, "harvest_date", "")))
    out.mkdir(parents=True, exist_ok=True)
    guard_outputs(out, "cases", force=args.force, append=args.append)

    files: list[Path]
    if src.is_dir():
        files = sorted(p for p in src.rglob("*") if p.suffix.lower() in {".json", ".jsonl"})
    else:
        files = [src]
    if not files:
        raise SystemExit(f"{src} 下没有 .json/.jsonl")

    raw_records: list[dict] = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() == ".jsonl":
            raw_records += [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            d = json.loads(text)
            if isinstance(d, dict) and "Data" in d:
                raw_records += d["Data"] or []
            elif isinstance(d, dict) and "structured" in d:      # 调用层缓存文件
                raw_records += (d["structured"] or {}).get("Data") or []
            elif isinstance(d, list):
                raw_records += d
            else:
                raise SystemExit(f"{p}: 认不出结构（既不是 MCP 响应也不是记录数组）")

    by_no: dict[str, dict] = {}
    if args.worklist and Path(args.worklist).exists():
        with open(args.worklist, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                by_no[r.get("案件字号", "")] = r

    records, counters = [], Counter()
    for rec in raw_records:
        built = build_judgment_record(rec, harvest_date=args.harvest_date)
        records.append(built)
        counters["total"] += 1
        counters[f"source_type:{built['source_type']}"] += 1
    # 去重：同一 pkulaw_id 只留一条
    seen, uniq = set(), []
    for r in records:
        key = r["pkulaw_id"] or r["doc_no"]
        if key in seen:
            counters["duplicated"] += 1
            continue
        seen.add(key)
        uniq.append(r)

    # 按文书类型分流：行政→金标候选；刑事→另行存放（v1 范围外，供行刑边界与后续扩展）
    groups = {"行政": [r for r in uniq if r["source_type"].startswith("行政")],
              "刑事": [r for r in uniq if r["source_type"].startswith("刑事")]}
    written, per_group = [], {}
    for kind, subset in groups.items():
        if not subset:
            continue
        name = "pkulaw_cases.pre_deid.jsonl" if kind == "行政" else "pkulaw_crim.pre_deid.jsonl"
        target = out / name
        if args.append:
            merged, added = merge_jsonl(target, subset)
            written.append(f"{target.name}（{kind} 追加 {added}，合计 {len(merged)} 件）")
        else:
            _write_jsonl_atomic(target, subset)
            written.append(f"{target.name}（{kind} {len(subset)} 件）")
        warns = Counter(w for r in subset for w in r["quality"]["parse_warnings"])
        per_group[kind] = {
            "件数": len(subset),
            "判决结论": dict(Counter(r["review"]["result"] for r in subset)),
            "原处罚类型": dict(Counter(r["outcome"]["type"] or "未解析" for r in subset)),
            "法律版本": dict(Counter(r["outcome"]["law_version"] or "未知" for r in subset)),
            "省份前 10": dict(Counter(r["region"] or "未知" for r in subset).most_common(10)),
            "信息完整（有金额+结果）": sum(1 for r in subset if r["quality"]["has_amount"] and r["quality"]["has_outcome"]),
            "解析告警": dict(warns),
        }
    stats = {"parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "counts": dict(counters),
             "files": written, "per_group": per_group}
    (out / "pkulaw_cases.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    registry_add("L1-legacy", out, records=len(uniq),
                 producer="collect/pkulaw_ingest.py cases", pipeline_version=SCHEMA_VERSION,
                 status="工作副本", note=f"判决书批次 {args.batch or batch_tag('')}")
    report(f"判决书解析 {len(uniq)} 件（去重 {counters['duplicated']}） → " + "；".join(written))
    for kind, g in per_group.items():
        report(f"  [{kind}] 判决结论 {g['判决结论']}｜原处罚 {g['原处罚类型']}")
        report(f"       法律版本 {g['法律版本']}｜信息完整 {g['信息完整（有金额+结果）']}/{g['件数']}")
        report(f"       省份前 10 {g['省份前 10']}")
        report(f"       告警 {g['解析告警']}")
    report("  注意：判决书含**真名**，交付前必须脱敏 + R6（deidentified=false）")


def cmd_worklist(args) -> None:
    """MCP 行政执法检索结果（JSON/JSONL/目录）→ 工作清单。

    用途：用"叙述式短语"检索出的结果**天然只含含事实的文书**，把它们落成文号清单，
    下载时按文号逐条勾选（网页一次最多 50 篇），下完用 `docs --worklist` 回写"已下全文"。
    """
    src = Path(args.src)
    out = resolve_out(args.out, "worklist", batch_tag(getattr(args, "batch", "")))
    out.mkdir(parents=True, exist_ok=True)
    guard_outputs(out, "worklist", force=getattr(args, "force", False))
    files = sorted(src.rglob("*")) if src.is_dir() else [src]
    files = [f for f in files if f.suffix.lower() in {".json", ".jsonl"}]
    if not files:
        raise SystemExit(f"{src} 下没有 .json/.jsonl")

    rows: dict[str, dict] = {}
    for f in files:
        text = f.read_text(encoding="utf-8")
        items: list[dict] = []
        if f.suffix.lower() == ".jsonl":
            items = [json.loads(l) for l in text.splitlines() if l.strip()]
        else:
            d = json.loads(text)
            if isinstance(d, dict) and "structured" in d:
                d = d["structured"] or {}
            if isinstance(d, dict) and "data" in d:
                items = d["data"] or []
            elif isinstance(d, dict) and "Data" in d:
                items = d["Data"] or []
            elif isinstance(d, list):
                items = d
        for r in items:
            no = (r.get("documentNo") or r.get("文号") or "").strip()
            if not no or no in rows:                     # 同一文号在库里常有两个标题变体，按文号去重
                continue
            rows[no] = {
                "发文案号": no,
                "标题": (r.get("title") or "")[:60],
                "处罚机关": r.get("punishOrgan") or "",
                "公布日期": r.get("punishmentDate") or "",
                "处罚种类": "／".join(r.get("punishmentType") or []),
                "依据法条": "／".join(r.get("accordingLaw") or []),
                "原文链接": (r.get("url") or "").replace("?way=mcp", ""),
                "叙述式": "是",                              # 命中叙述式短语 ⇒ 已知含事实
                "已下全文": "",
            }
    dest = out / "worklist.csv"
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(next(iter(rows.values())).keys()) if rows else ["发文案号"])
        w.writeheader()
        for r in rows.values():
            w.writerow(r)
    report(f"工作清单：{len(rows)} 个文号（去重后）→ {dest}")
    if rows:
        report(f"  日期跨度：{min(r['公布日期'] for r in rows.values())} ~ {max(r['公布日期'] for r in rows.values())}")
        report(f"  机关数：{len({r['处罚机关'] for r in rows.values()})}")


def main() -> None:
    ap = argparse.ArgumentParser(description="北大法宝导出 → 结构化数据（data-spec v0.1）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog", help="目录列表（.xls / CSV）→ 工作清单与统计")
    c.add_argument("--xls", "--catalog", dest="xls", required=True, help="法宝导出的目录列表 .xls（或已转好的 CSV）")
    c.add_argument("--out", default="", help="输出目录；缺省按批次隔离：$JUSTILAW_DATA_DIR/<kind>/<batch>/（不再默认写共享目录）")
    c.add_argument("--batch", default="", help="批次标签（缺省用时间戳）")
    c.add_argument("--force", action="store_true", help="允许覆盖已有产物（默认拒写）")
    c.set_defaults(func=cmd_catalog)
    d = sub.add_parser("docs", help="已下全文（.doc/.docx/.txt）→ 结构化 JSONL")
    d.add_argument("--docs", required=True, help="放导出文书的目录（递归）")
    d.add_argument("--worklist", default="", help="catalog 产出的 worklist.csv（按文号 join）")
    d.add_argument("--manifest", default=str(HERE / "manifest.csv"),
                   help="台账 manifest.csv：按文件 SHA-256 回填 id（默认本目录下的台账）")
    d.add_argument("--harvest-date", default="")
    d.add_argument("--out", default="", help="输出目录；缺省按批次隔离：$JUSTILAW_DATA_DIR/<kind>/<batch>/（不再默认写共享目录）")
    d.add_argument("--batch", default="", help="批次标签（缺省用 harvest-date 或时间戳）")
    d.add_argument("--append", action="store_true",
                   help="与目标目录已有产物按 引证码/文号 去重合并（跨批累积）")
    d.add_argument("--force", action="store_true", help="允许覆盖已有产物（默认拒写）")
    d.set_defaults(func=cmd_docs)
    wl = sub.add_parser("worklist", help="MCP 行政执法检索结果 → 工作清单（含'已知含事实'标记）")
    wl.add_argument("--src", required=True, help="MCP 响应 JSON/JSONL 或目录（含缓存目录）")
    wl.add_argument("--out", default="", help="输出目录；缺省按批次隔离：$JUSTILAW_DATA_DIR/<kind>/<batch>/（不再默认写共享目录）")
    wl.add_argument("--batch", default="", help="批次标签（缺省用时间戳）")
    wl.add_argument("--force", action="store_true", help="允许覆盖已有产物（默认拒写）")
    wl.set_defaults(func=cmd_worklist)
    m = sub.add_parser("merge", help="跨批次合并解析产物（择优去重）→ 一个唯一集合")
    m.add_argument("--from", dest="sources", nargs="+", required=True, help="要合并的批次目录（含四个分级文件）")
    m.add_argument("--out", default="", help="输出目录；缺省 $JUSTILAW_DATA_DIR/ingest/<批次>/")
    m.add_argument("--batch", default="", help="批次标签（缺省时间戳）")
    m.add_argument("--force", action="store_true", help="允许覆盖已有产物（默认拒写）")
    m.set_defaults(func=cmd_merge)
    p1 = sub.add_parser("parsed1", help="legacy 解析产物 → parsed-1（统一中间格式 L1）")
    p1.add_argument("--from", dest="sources", nargs="+", required=True, help="legacy 批次目录（含分级文件）")
    p1.add_argument("--out", default="", help="缺省 $JUSTILAW_DATA_DIR/parsed/pkulaw/<批次>/")
    p1.add_argument("--batch", default="", help="批次标签（缺省时间戳）")
    p1.add_argument("--force", action="store_true", help="允许覆盖已有 records.jsonl（默认拒写）")
    p1.set_defaults(func=cmd_parsed1)
    c2 = sub.add_parser("cases", help="司法案例记录（MCP 响应/JSONL）→ 判决书规格 JSONL")
    c2.add_argument("--src", required=True, help="MCP 响应 JSON、JSONL 或目录")
    c2.add_argument("--worklist", default="", help="司法案例库目录 worklist.csv（按案件字号 join）")
    c2.add_argument("--harvest-date", default="")
    c2.add_argument("--out", default="", help="输出目录；缺省按批次隔离：$JUSTILAW_DATA_DIR/<kind>/<batch>/（不再默认写共享目录）")
    c2.add_argument("--batch", default="", help="批次标签（缺省用 harvest-date 或时间戳）")
    c2.add_argument("--append", action="store_true", help="与已有产物按 引证码/文号 去重合并")
    c2.add_argument("--force", action="store_true", help="允许覆盖已有产物（默认拒写）")
    c2.set_defaults(func=cmd_cases)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
