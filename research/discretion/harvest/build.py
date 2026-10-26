"""parsed-1 → 交付引擎的行政案例文件（文本处理规范；2026-10-17 起主管线零遮蔽，修订案 D-003）。

步骤：
  1. 原文正本组装（build_record）：text_full 即 parsed-1 原文，各段为原文连续子串；文号明文（D3 放宽）+
     doc_no_hash 去重键；subject_mention 承担本人定位；B 类定性句裁剪（parse.trim_facts_conclusions）。
     deid / R6 / deid_map 已停产——外发前另跑衍生遮蔽（text-processing-spec §4.2/§4.3）。
  2. 区划（regions.py 产出的 regions.csv，人工覆盖 regions_manual.csv）。
  3. 纳入判定（规范 §4.5）：② 事实 ≥30 字且含赌博行为描述、③ 处罚结果已解析、④ 能定位到省、本人可指认（subject_mention）。
     ③④ 满足但事实不够的（汇总条目、只有案件名的字段表）进 admin_outcomes_only.jsonl（D6 建议 B），不进金标。
  4. 去重与关联（规范 §4.4）：文号哈希相同 → 只留一份；近重复（事实 + 决定段字符 5-gram Jaccard ≥ 0.8）、
     同站同日且事实相似（3-gram Jaccard ≥ 0.5）的多人同案、复议与原处罚（复议正文引用的原处罚文号）→ 归入同一 event_id，
     划分训练/测试时整组同侧（R7、G1.3）。linked_ids 只记复议 ↔ 原处罚。
  5. 写出 admin_cases.schema-1.0.0.jsonl、admin_outcomes_only.jsonl、admin_excluded.csv、build_stats.json、SHA256SUMS。

用法（仓库根目录）：
  # 只跑网页来源（旧行为）：
  python research/discretion/harvest/build.py
  # 统一构建：网页 L1 + 各来源 parsed-1（可多次 --parsed NAME=PATH），交付按版本目录发布：
  python research/discretion/harvest/build.py \
      --parsed pkulaw=$JUSTILAW_DATA_DIR/parsed/pkulaw/merged-20261016 \
      --out $JUSTILAW_DATA_DIR/delivery/2026-10-16.pk1 --version 2026-10-16.pk1
输入：网页 L1 = $JUSTILAW_DATA_DIR/admin/web_cases.pre_deid.jsonl（parse.py 产出）；
      parsed-1 来源 = parsed/<来源>/<批次>/records.jsonl（数据记录契约见 justilaw-api/app/discretion/records.py）。
输出：默认 $JUSTILAW_DATA_DIR/admin/；给 --out 时写该目录（建议 delivery/<版本>/，并写父目录 LATEST 指针）。
登记：写 $JUSTILAW_DATA_DIR/REGISTRY.csv（总览 §6；失败不阻断构建）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))

import r6_scan  # noqa: E402  # 仅外发衍生工具入口保留；主管线不再调用（修订案 D-003）
from deid import doc_no_hash, parse_meta_date  # noqa: E402
from parse import CONCLUSION_MARK, trim_facts_conclusions  # noqa: E402
from regions import Resolver, load_regions, load_table  # noqa: E402
from search import data_root  # noqa: E402
from triage import DOC_NO  # noqa: E402

SCHEMA_VERSION = "1.0.0"
PIPELINE_VERSION = "harvest-0.6"   # 0.6：脱敏全量取消（D-003）——原文正本交付、文号明文、R6/deid_map 停产、B 类定性句裁剪
SEGMENTS = ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review")
TYPE_RANK = {"处罚决定书": 3, "行政复议决定书": 3, "执法公示": 1}
GAMBLING_FACT = re.compile(r"赌|抽头|抽水|六合彩|私彩|牌九|麻将|扑克|炸金花|押宝|牛牛|三公|推筒|跑胡子|下注|投注|彩票")


# ---------- 单件 ----------

REVIEW_VALUES = {"维持", "变更", "撤销", "确认违法", "程序驳回", "无"}
LAW_TAG = {"旧法": "（2012修正）", "新法": "（2025修订）"}


def law_version_of(behavior_date: str, by_article: str) -> str:
    """规格 v0.2 §1.2 / D8：**以实际引用的法条版本为准**（不要用行为日覆盖）；没有引用时退回行为日推断。

    2026-10-16 修 I-01：旧实现按行为日优先，把 13 条"从旧兼从轻、实际引用新法"的案件标成旧法。
    """
    if by_article:
        return by_article
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", behavior_date or ""):
        return "新法" if behavior_date >= "2026-01" else "旧法"
    return "未知"


def tag_articles(articles: list[str], version: str) -> list[str]:
    """法条统一写法：治安管理处罚法第七十条 → 治安管理处罚法（2012修正）第七十条（版本按所引条文判定）。"""
    tag = LAW_TAG.get(version, "")
    return [re.sub(r"^(?:中华人民共和国)?治安管理处罚法(?![（(])", "治安管理处罚法" + tag, a) if tag else a for a in articles]


def place_segment(full: str, seg: str) -> tuple[int, int] | None:
    """段落在正本里的位置；字段式公示拼出来的决定段（"依据；结果"）找不到原样时，退而取其中能原样找到的结果部分。"""
    pos = full.find(seg)
    if pos >= 0:
        return pos, pos + len(seg)
    parts = [p for p in re.split(r"[；;]", seg) if p.strip() and full.find(p.strip()) >= 0]
    if not parts:
        return None
    best = next((p for p in parts if re.search(r"拘留|罚款|警告|不予|处罚", p)), max(parts, key=len)).strip()
    pos = full.find(best)
    return pos, pos + len(best)


def build_record(rec: dict) -> tuple[dict, bool]:
    """原文正本交付（修订案 D-003 / 用户 2026-10-17：主管线零遮蔽）。

    - 各段取原文连续子串（place_segment，无投影——text_full 即 parsed-1 原文）；
    - 文号明文交付（D3 放宽），doc_no_hash 保留为去重/关联键；
    - subject_mention 承担本人定位（subject_alias"甲"取消）；
    - deidentified/r6_scan 字段取消；deid_map 停产；B 类定性句裁剪（parse.trim_facts_conclusions）。
    返回 (交付记录, 是否发生 B 类裁剪)。
    """
    full = rec.get("text_full") or ""
    out_segments, offsets = {}, {}
    for f in SEGMENTS:
        seg = (rec.get(f) or "").strip()
        place = place_segment(full, seg) if seg else None
        if place:
            out_segments[f], offsets[f] = full[place[0]:place[1]], [place[0], place[1]]
        else:
            out_segments[f], offsets[f] = "", None
    facts_raw = out_segments.get("text_facts") or ""
    facts_trim, trimmed = trim_facts_conclusions(facts_raw)
    if trimmed:
        place = place_segment(full, facts_trim)
        if place:   # 裁剪后仍是原文连续子串才换；否则保留原文（连续性优先）
            out_segments["text_facts"], offsets["text_facts"] = full[place[0]:place[1]], [place[0], place[1]]
            trimmed = out_segments["text_facts"] == facts_trim
    oc = dict(rec.get("outcome") or {})
    internal = {k: oc.pop(k) for k in ("detention_items", "from_execution_clause") if k in oc}
    oc["articles"] = tag_articles(oc.get("articles") or [], oc.get("law_version", ""))
    rv = dict(rec.get("review") or {})
    rv["result"] = {"驳回": "程序驳回"}.get(rv.get("result", ""), rv.get("result", ""))
    rv["changed_outcome"] = rv.get("changed_outcome") or None
    no = rec.get("doc_no") or ""
    warns = [w for w in (rec.get("parse_warnings") or []) if w != "facts_contains_conclusion"]
    fcc = bool(CONCLUSION_MARK.search(out_segments.get("text_facts") or ""))
    if fcc:
        warns.append("facts_contains_conclusion")
    out = {
        "id": rec["id"],
        "source_type": rec.get("source_type", ""),
        "doc_no": no,
        "doc_no_hash": doc_no_hash(no) if no else "",
        "harvest_date": rec.get("harvest_date", ""),
        "behavior_date": rec.get("behavior_date", ""),
        "decision_date": rec.get("decision_date", ""),
        "authority": rec.get("authority") or "",
        "region": "", "region_level": "", "province": "", "province_code": "",
        "law_version": law_version_of(rec.get("behavior_date", ""), oc.get("law_version", "")),
        "subject_mention": rec.get("subject_mention", ""),
        "event_id": "",
        "linked_ids": [],
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "text_full": full,
        "text_sha256": hashlib.sha256(full.encode("utf-8")).hexdigest(),
        **out_segments,
        "segmented": bool(rec.get("segmented")),
        "segments": offsets,
        "outcome": oc,
        "review": rv,
        "quality": {"ocr": bool(rec.get("ocr")), "completeness": rec.get("completeness") or {},
                    "parse_warnings": warns,
                    "facts_contains_conclusion": fcc,
                    "ambiguous_persons": False,   # 原为 deid 派生布尔；引擎契约修订（修订案 §B）后删除
                    "age_uncertain": False,
                    **internal},
    }
    # 复议引用的原处罚文号（原文取，留哈希做关联键）
    out["_cited"] = sorted({doc_no_hash(m.group(1)) for m in DOC_NO.finditer(full) if m.group(1) != no})
    out["_site"] = rec.get("site", "")
    out["_region"] = rec.get("_region")  # parsed-1 来源在接入时已解析的区划（无站点来源用；写出时按 _ 前缀剥离）
    return out, trimmed


BOILERPLATE = re.compile(r"违法行为人|违法嫌疑人|被处罚人|[甲乙丙丁戊己庚壬癸]|因?实施了?|(?:为赌博提供条件、?)?赌博的?违法行为|的违法行为"
                         r"|于?\d{4}年\d{1,2}月(?:[初中下上旬末底份]{0,2})?(?:至(?:\d{4}年)?\d{1,2}月)?(?:间|期间)?"
                         r"|因赌博|参与赌博|进行赌博|[，,。、；\s]")


def inclusion(out: dict) -> list[str]:
    """不满足的纳入条件（空表示可进金标）。"""
    miss = []
    facts = out.get("text_facts") or ""
    # 结果表一行既当事实又当决定（海南定安等）：事实没有单独成段，不进金标。
    # I-03：汇总条目"违法行为人甲，于2025年10月至2026年1月期间实施了赌博的违法行为，"字数够 30 但没有任何要素——
    # 去掉称谓、日期、"实施了赌博的违法行为"这类套话后不足 12 字的也算事实不足
    core = BOILERPLATE.sub("", facts)
    if (len(re.sub(r"\s", "", facts)) < 30 or not GAMBLING_FACT.search(facts) or facts == out.get("text_decision")
            or len(core) < 12):
        miss.append("②事实不足")
    if not (out.get("outcome") or {}).get("type"):
        miss.append("③结果未解析")
    if not out.get("province_code"):
        miss.append("④无区划")
    subject = out.get("subject_mention") or ""
    if not subject:
        miss.append("本人不可指认")
    # 修订案 §B：subject_alias"甲出现率"检查随脱敏取消删除——本人定位由 subject_mention 承担，
    # 不再要求其在事实段字面出现（正文以"违法行为人"等指代为合法形态）
    if (out.get("review") or {}).get("result") not in REVIEW_VALUES:
        miss.append("复议结论未解析")
    return miss


# ---------- 去重与关联 ----------

def shingles(text: str, n: int) -> set[str]:
    t = re.sub(r"\s", "", text or "")
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def jaccard_pairs(sets: dict[str, set[str]], threshold: float, max_df: int = 300) -> list[tuple[str, str, float]]:
    """精确 Jaccard（倒排索引找候选对，跳过出现在太多文档里的公文套话片段）。"""
    index: dict[str, list[str]] = defaultdict(list)
    for k, s in sets.items():
        for g in s:
            index[g].append(k)
    overlap: Counter = Counter()
    for g, ks in index.items():
        if len(ks) > max_df:
            continue
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                overlap[(ks[i], ks[j])] += 1
    out = []
    for (a, b), _ in overlap.items():
        sa, sb = sets[a], sets[b]
        inter = len(sa & sb)
        jac = inter / (len(sa) + len(sb) - inter) if sa or sb else 0.0
        if jac >= threshold:
            out.append((a, b, jac))
    return out


def dates_close(a: str, b: str, days: int = 31) -> bool:
    da, db = parse_meta_date(a), parse_meta_date(b)
    if not da or not db:
        return True
    return abs((da - db).days) <= days


class DSU:
    def __init__(self, keys):
        self.p = {k: k for k in keys}

    def find(self, k):
        while self.p[k] != k:
            self.p[k] = self.p[self.p[k]]
            k = self.p[k]
        return k

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def quality_rank(r: dict) -> tuple:
    return (TYPE_RANK.get(r["source_type"], 0), r["segmented"], len(r.get("text_facts") or ""), not r["quality"]["ocr"])


def dedupe_and_link(records: list[dict]) -> tuple[list[dict], list[tuple[str, str]], dict]:
    """返回 (保留的记录, [(被去掉的 id, 原因)], 统计)。就地写 event_id、linked_ids。"""
    by_hash: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["doc_no_hash"]:
            by_hash[r["doc_no_hash"]].append(r)
    dropped = []
    drop_ids = set()
    for h, rs in by_hash.items():
        if len(rs) > 1:
            keep = max(rs, key=quality_rank)
            for r in rs:
                if r is not keep:
                    drop_ids.add(r["id"])
                    dropped.append((r["id"], f"重复文号:{keep['id']}"))
    kept = [r for r in records if r["id"] not in drop_ids]
    ids = [r["id"] for r in kept]
    dsu = DSU(ids)
    rec = {r["id"]: r for r in kept}
    # 近重复
    near = jaccard_pairs({r["id"]: shingles((r.get("text_facts") or "") + (r.get("text_decision") or "")
                                            or r["text_full"], 5) for r in kept}, 0.8)
    near = [(a, b, j) for a, b, j in near if dates_close(rec[a]["behavior_date"], rec[b]["behavior_date"])]
    for a, b, _ in near:  # 近重复但行为日相差一个多月的是套话相同的不同案件，不并（规格 §4：同一 event_id 日期相同或相近）
        dsu.union(a, b)
    # 同站同日、事实相似：同一事件多人
    groups: dict[tuple, list[str]] = defaultdict(list)
    for r in kept:
        if r["behavior_date"] and len(r["behavior_date"]) == 10:
            groups[(r["_site"], r["behavior_date"])].append(r["id"])
    same_event = 0
    for ks in groups.values():
        if len(ks) < 2:
            continue
        sets = {k: shingles(rec[k].get("text_facts") or "", 3) for k in ks}
        for a, b, _ in jaccard_pairs(sets, 0.5, max_df=10 ** 9):
            dsu.union(a, b)
            same_event += 1
    # 复议 ↔ 原处罚
    hash_to_ids: dict[str, list[str]] = defaultdict(list)
    for r in kept:
        if r["doc_no_hash"]:
            hash_to_ids[r["doc_no_hash"]].append(r["id"])
    links = 0
    for r in kept:
        for h in r["_cited"]:
            for other in hash_to_ids.get(h, []):
                if other != r["id"]:
                    rec[other]["linked_ids"] = sorted(set(rec[other]["linked_ids"]) | {r["id"]})
                    r["linked_ids"] = sorted(set(r["linked_ids"]) | {other})
                    dsu.union(r["id"], other)
                    links += 1
    members: dict[str, list[str]] = defaultdict(list)
    for k in ids:
        members[dsu.find(k)].append(k)
    for root, ks in members.items():
        eid = "E-" + hashlib.sha1("|".join(sorted(ks)).encode()).hexdigest()[:10]
        for k in ks:
            rec[k]["event_id"] = eid
    stats = {"dup_doc_no_dropped": len(dropped), "near_dup_pairs": len(near), "same_event_pairs": same_event,
             "review_links": links, "events": len(members), "multi_record_events": sum(len(v) > 1 for v in members.values())}
    return kept, dropped, stats


# ---------- parsed-1（统一中间格式）来源接入（2026-10-16：法宝来源首批） ----------

def region_for_record(resolver: Resolver, rec: dict) -> dict | None:
    """无站点来源的区划解析：机关名（权重 3）+ 正文前 300 字（1），复用站点同一张表与打分；省名兜底。"""
    texts = [(t, w) for t, w in ((rec.get("authority") or "", 3),
                                 ((rec.get("text_full") or "")[:300], 1)) if t]
    got = resolver.resolve(texts) if texts else None
    if got:
        return got
    prov = rec.get("province") or ""
    if prov:
        for p in resolver.provinces:
            if prov in (p["name"], resolver.short[p["code"]]):
                return resolver.row(p, 1, "province_only")
    return None


def from_parsed1(rec: dict, resolver: Resolver) -> dict | None:
    """parsed-1（L1 统一中间格式）→ 构建内部形状（与 parse.py 的输出同形）。

    只收 quality.in_scope 为真的记录；区划在接入时按机关解析（省名兜底）。
    """
    q = rec.get("quality") or {}
    if not q.get("in_scope"):
        return None
    extra = rec.get("extra") or {}
    oc = dict(rec.get("outcome") or {})
    oc.update(extra.get("outcome") or {})            # detention_items 等内部字段还原
    # 依地方条例处罚的记录没有治安法版本 → 用顶层"未知"，避免按治安法上限误判（实测 P-550 罚款 4000）
    oc["law_version"] = oc.get("law_version") or rec.get("law_version") or ""
    # fine_masked 豁免（协同指令 §2.4，P-715–717）：发布方遮蔽金额（"＊＊＊元"）致结果未解析的，
    # 按决定段关键词定 type，金额不猜测记 fine_masked（引擎 acfabf6 的 outcome.fine_masked 字段口径）
    if not oc.get("type"):
        probe = (rec.get("text_decision") or "") + (rec.get("text_full") or "")[:300]
        if re.search(r"[＊*xX×]{1,8}\s*元", probe):
            t = ("拘留并处罚款" if "拘留" in probe and "罚款" in probe
                 else "拘留" if "拘留" in probe
                 else "罚款" if "罚款" in probe
                 else "警告" if "警告" in probe else "")
            if t:
                oc["type"] = t
                oc["fine"] = oc.get("fine") or 0
                oc["detention_days"] = oc.get("detention_days") or 0
                oc["fine_masked"] = True
    site = extra.get("site", "")                     # 网页来源（to_parsed1.py）带站点，区划与"同站同日"事件分组都靠它
    if rec.get("region") and rec.get("province"):    # 解析层已给区划（网页按站点表）的直接用，否则按机关名解析
        region = {"region_code": rec["region"], "level": extra.get("region_level", ""), "province": rec["province"],
                  "province_code": extra.get("province_code") or rec["region"][:2] + "0000"}
    else:
        region = region_for_record(resolver, rec)
    out = {
        "id": rec["id"],
        "source_type": rec.get("source_type", ""),
        "site": site,
        "doc_no": rec.get("doc_no", ""),
        "subject_mention": rec.get("subject_mention", ""),
        "harvest_date": rec.get("harvest_date", ""),
        "behavior_date": rec.get("behavior_date", ""),
        "decision_date": rec.get("decision_date", ""),
        "authority": rec.get("authority", ""),
        "text_full": rec.get("text_full", ""),
        "segmented": bool(rec.get("segmented")),
        "outcome": oc,
        "review": rec.get("review") or {},
        "parse_warnings": list(q.get("parse_warnings") or []),
        "completeness": q.get("completeness") or {},
        "facts_contains_conclusion": bool(q.get("facts_contains_conclusion")),
        "ocr": bool(q.get("ocr")),
        "_region": region,
        "_site": site or ("法宝:" + (rec.get("authority") or rec.get("province") or rec["id"])),
    }
    for k in SEGMENTS:
        out[k] = rec.get(k, "")
    return out


def load_parsed_source(spec: str, resolver: Resolver) -> tuple[list[dict], str]:
    """--parsed NAME=PATH：读 parsed-1 records.jsonl（或目录）→ 内部形状；返回 (记录, 描述)。"""
    name, _, path = spec.partition("=")
    p = Path(path)
    if p.is_dir():
        p = p / "records.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = [got for r in rows if (got := from_parsed1(r, resolver)) is not None]
    sha = hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else "-"
    desc = f"{name}: {p}（{len(rows)} 条 → 范围内 {len(out)}；sha256:{sha}）"
    print(f"[parsed] {desc}")
    return out, desc


# ---------- 主流程 ----------

def attach_region(out: dict, regions: dict[str, dict]) -> None:
    g = out.get("_region") or regions.get(out.get("_site"))
    if g and g.get("province_code"):
        out.update({"region": g.get("region_code", ""), "region_level": g.get("level", ""),
                    "province": g["province"], "province_code": g["province_code"]})


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")


def _demote_other_deliveries(registry: Path, current: Path) -> None:
    """新交付发布后，把登记表里其他 L3"现行"行标为"已取代"（LATEST 只有一个现行版本）。"""
    import csv as _csv
    if not registry.exists():
        return
    rows = list(_csv.DictReader(registry.open(encoding="utf-8-sig", newline="")))
    fields = list(rows[0].keys()) if rows else []
    changed = False
    for r in rows:
        if r.get("layer") == "L3" and r.get("status") == "现行" and Path(r["path"]) != current:
            r["status"] = "已取代"
            changed = True
    if changed:
        tmp = registry.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        tmp.replace(registry)


def main() -> int:
    ap = argparse.ArgumentParser(description="L2 统一构建：各来源 L1 → 脱敏/去重/事件分组 → 交付层")
    ap.add_argument("--parsed", action="append", default=[], metavar="NAME=PATH",
                    help="额外的 parsed-1 来源（可多次），如 pkulaw=$DATA/parsed/pkulaw/merged-20261016")
    ap.add_argument("--web", default="", help="网页 L1 旧形状（缺省 $DATA/admin/web_cases.pre_deid.jsonl）；"
                                              "给了 --parsed web=… 时不读")
    ap.add_argument("--out", default="", help="输出目录（缺省 $DATA/delivery/<日期>.r<n>/，自动取下一个空号）")
    ap.add_argument("--version", default="", help="版本号（写进 stats；缺省用输出目录名）")
    ap.add_argument("--force", action="store_true", help="允许写进已有内容的输出目录（默认拒绝：交付不覆盖，I-08）")
    args = ap.parse_args()

    today = date.today().isoformat()   # 保留：登记表时间戳口径
    root = data_root().parent
    if args.out:
        adir = Path(args.out)
    else:
        k = 1
        while (root / "delivery" / f"{today}.r{k}").exists():
            k += 1
        adir = root / "delivery" / f"{today}.r{k}"
    if adir.exists() and any(adir.iterdir()) and not args.force:
        print(f"[拒绝] {adir} 已有内容；交付按版本发布不覆盖，换一个 --out 或加 --force")
        return 2
    adir.mkdir(parents=True, exist_ok=True)
    regions = load_regions()

    def _in_sha(f: Path) -> str:
        return hashlib.sha256(f.read_bytes()).hexdigest()[:12] if f.is_file() else "-"

    resolver = Resolver(load_table())
    scope, inputs = [], []
    if not any(s.split("=", 1)[0] == "web" for s in args.parsed):
        web_src = Path(args.web) if args.web else (root / "admin" / "web_cases.pre_deid.jsonl")
        src = [json.loads(l) for l in web_src.read_text(encoding="utf-8").splitlines() if l.strip()]
        scope = [r for r in src if r.get("in_scope")]
        inputs.append(f"web: {web_src}（{len(src)} 条 → 范围内 {len(scope)}；sha256:{_in_sha(web_src)}）")
    for spec in args.parsed:
        rows, desc = load_parsed_source(spec, resolver)
        inputs.append(desc)
        scope += rows
    main_rows, outcome_rows, excluded = [], [], []
    b_trimmed = 0
    for rec in scope:
        out, trimmed = build_record(rec)
        b_trimmed += trimmed
        attach_region(out, regions)
        miss = inclusion(out)
        if not miss:
            main_rows.append(out)
        # I-04：只有结果的文件也要求本人可指认（subject_mention 承担）；多人一行的结果表等找不到本人的排除
        elif set(miss) <= {"②事实不足", "本人未在事实段出现"}:
            outcome_rows.append(out)
        else:
            excluded.append((out["id"], ";".join(miss)))
    main_rows, dropped_main, link_stats = dedupe_and_link(main_rows)
    outcome_rows, dropped_oc, _ = dedupe_and_link(outcome_rows)
    # 汇总条目与金标重复（同一文号）时只留金标那份
    main_hash = {r["doc_no_hash"] for r in main_rows if r["doc_no_hash"]}
    oc_keep = []
    for r in outcome_rows:
        if r["doc_no_hash"] and r["doc_no_hash"] in main_hash:
            dropped_oc.append((r["id"], "重复文号:见金标"))
        else:
            oc_keep.append(r)
    outcome_rows = oc_keep
    excluded += dropped_main + dropped_oc

    out_main = adir / f"admin_cases.schema-{SCHEMA_VERSION}.jsonl"
    out_oc = adir / "admin_outcomes_only.jsonl"
    write_jsonl(out_main, main_rows)
    write_jsonl(out_oc, outcome_rows)
    with open(adir / "admin_excluded.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "reason"])
        w.writerows(sorted(excluded))
    kept_ids = {r["id"] for r in main_rows} | {r["id"] for r in outcome_rows}
    # deid_map.jsonl 停产（修订案 D-003）：主管线零遮蔽，无遮蔽映射可记
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in (out_main, out_oc))
    (adir / "SHA256SUMS").write_text(sums, encoding="utf-8")

    def describe(rows):
        return {
            "records": len(rows),
            "by_source_type": dict(Counter(r["source_type"] for r in rows)),
            "by_province": dict(Counter(r["province"] or "未知" for r in rows).most_common()),
            "outcome_type": dict(Counter(r["outcome"].get("type") or "未解析" for r in rows)),
            "law_version": dict(Counter(r["outcome"].get("law_version") or "未知" for r in rows)),
            "has_amount": sum(bool(r["quality"]["completeness"].get("has_amount")) for r in rows),
            "segmented": sum(r["segmented"] for r in rows),
            "ocr": sum(r["quality"]["ocr"] for r in rows),
            "ambiguous_persons": sum(r["quality"]["ambiguous_persons"] for r in rows),
            "facts_contains_conclusion": sum("facts_contains_conclusion" in r["quality"]["parse_warnings"] for r in rows),
            "events": len({r["event_id"] for r in rows}),
            "linked": sum(bool(r["linked_ids"]) for r in rows),
        }
    stats = {"pipeline_version": PIPELINE_VERSION, "version": args.version or adir.name,
             "inputs": inputs, "in_scope": len(scope),
             "deid": "removed per D-003（规范修订案 2026-10-17）：主管线零遮蔽；r6_scan/deid_map 转外发衍生工具",
             "doc_no_plaintext": True,
             "main": describe(main_rows), "outcomes_only": describe(outcome_rows),
             "excluded": len(excluded),
             "excluded_reasons": dict(Counter(r.split(":")[0] if r.startswith("重复") else r for _, r in excluded)),
             "dedupe_main": link_stats,
             "b_class_trimmed": b_trimmed,
             "fine_masked_rescued": sum(bool(r["outcome"].get("fine_masked")) for r in main_rows + outcome_rows)}
    (adir / "build_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    # 版本指针 + 登记表（总览 §6；登记失败不阻断构建）
    try:
        if adir.parent.name == "delivery":
            (adir.parent / "LATEST").write_text(adir.name, encoding="utf-8")
        sys.path.insert(0, str(HERE.parent / "collect"))
        from common import REGISTRY, registry_add  # noqa: PLC0415
        registry_add("L3", adir, records=len(main_rows) + len(outcome_rows),
                     producer="harvest/build.py", pipeline_version=PIPELINE_VERSION,
                     status="现行", note="；".join(inputs))
        _demote_other_deliveries(REGISTRY, adir)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 登记表写入失败（忽略）：{exc}")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
