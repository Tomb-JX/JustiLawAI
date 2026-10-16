"""脱敏前案例 → 交付引擎的行政案例文件（文本处理规范 docs/04-plan/text-processing-spec.md §4.2–§4.6）。

步骤：
  1. 逐件脱敏（deid.py）：正本 text_full 脱敏，各段按位置投影成正本的切片并记起止位置；找不到原样的段单独脱敏、起止记空。
  2. R6 第一次扫描（r6_scan.py）：有硬命中的案例不交付，列入排除清单（原因 R6:类别）。
  3. 区划（regions.py 产出的 regions.csv，人工覆盖 regions_manual.csv）。
  4. 纳入判定（规范 §4.5）：② 事实 ≥30 字且含赌博行为描述、③ 处罚结果已解析、④ 能定位到省、本人可指认（有"甲"）。
     ③④ 满足但事实不够的（汇总条目、只有案件名的字段表）进 admin_outcomes_only.jsonl（D6 建议 B），不进金标。
  5. 去重与关联（规范 §4.4）：文号哈希相同 → 只留一份；近重复（事实 + 决定段字符 5-gram Jaccard ≥ 0.8）、
     同站同日且事实相似（3-gram Jaccard ≥ 0.5）的多人同案、复议与原处罚（复议正文引用的原处罚文号）→ 归入同一 event_id，
     划分训练/测试时整组同侧（R7、G1.3）。linked_ids 只记复议 ↔ 原处罚。
  6. 写出 admin_cases.schema-1.0.0.jsonl、admin_outcomes_only.jsonl、admin_excluded.csv、build_stats.json、SHA256SUMS；
     deid_map.jsonl（代号 → 原文位置与长度，不含原名）同目录存放，不入库。最后对两个交付文件整体再做一次 R6。

用法（仓库根目录）：python research/discretion/harvest/build.py
输入：$JUSTILAW_DATA_DIR/admin/web_cases.pre_deid.jsonl（parse.py 产出）
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))

import r6_scan  # noqa: E402
from deid import deidentify, doc_hash, parse_meta_date  # noqa: E402
from regions import load_regions  # noqa: E402
from search import data_root  # noqa: E402
from triage import DOC_NO  # noqa: E402

SCHEMA_VERSION = "1.0.0"
PIPELINE_VERSION = "harvest-0.3"
SEGMENTS = ("text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review")
TYPE_RANK = {"处罚决定书": 3, "行政复议决定书": 3, "执法公示": 1}
GAMBLING_FACT = re.compile(r"赌|抽头|抽水|六合彩|私彩|牌九|麻将|扑克|炸金花|押宝|牛牛|三公|推筒|跑胡子|下注|投注|彩票")


# ---------- 单件 ----------

def deid_record(rec: dict) -> tuple[dict, list]:
    """脱敏一件；返回 (交付记录, deid_map)。"""
    behavior = parse_meta_date(rec.get("behavior_date", ""))
    full = rec.get("text_full") or ""
    d = deidentify(full, behavior=behavior)
    out_segments, offsets = {}, {}
    for f in SEGMENTS:
        seg = (rec.get(f) or "").strip()
        if not seg:
            out_segments[f], offsets[f] = "", None
            continue
        pos = full.find(seg)
        if pos >= 0:
            a, b = d.project(pos, is_end=False), d.project(pos + len(seg), is_end=True)
            out_segments[f], offsets[f] = d.text[a:b], [a, b]
        else:  # 字段式公示拼出来的决定段等：单独脱敏，沿用代号表
            out_segments[f], offsets[f] = deidentify(seg, behavior=behavior, persons=d.persons).text, None
    authority = deidentify(rec.get("authority") or "", persons=d.persons).text if rec.get("authority") else ""
    oc = dict(rec.get("outcome") or {})
    internal = {k: oc.pop(k) for k in ("detention_items", "from_execution_clause") if k in oc}
    no = rec.get("doc_no") or ""
    out = {
        "id": rec["id"],
        "event_id": "",
        "linked_ids": [],
        "subject_alias": "甲" if d.subject else "",
        "source_type": rec.get("source_type", ""),
        "source_ref": f"manifest_web.csv#{rec['id'].split('-')[0]}-{rec['id'].split('-')[1]}",
        "doc_no_hash": doc_hash(no) if no else "",
        "harvest_date": rec.get("harvest_date", ""),
        "deidentified": "是",
        "behavior_date": rec.get("behavior_date", ""),
        "decision_date": rec.get("decision_date", ""),
        "authority": authority,
        "region": "", "region_level": "", "province": "", "province_code": "",
        "text_full": d.text,
        **out_segments,
        "segmented": bool(rec.get("segmented")),
        "segments": offsets,
        "outcome": oc,
        "review": rec.get("review") or {},
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "text_sha256": hashlib.sha256(d.text.encode("utf-8")).hexdigest(),
        "quality": {"ocr": bool(rec.get("ocr")), "completeness": rec.get("completeness") or {},
                    "parse_warnings": rec.get("parse_warnings") or [], "ambiguous_persons": d.ambiguous_persons,
                    "persons": len(set(d.persons.values())), "deid_counts": d.counts, **internal},
    }
    # 复议引用的原处罚文号（脱敏前取，只留哈希）用于关联
    out["_cited"] = sorted({doc_hash(m.group(1)) for m in DOC_NO.finditer(full) if m.group(1) != no})
    out["_site"] = rec.get("site", "")
    return out, d.deid_map()


def inclusion(out: dict) -> list[str]:
    """不满足的纳入条件（空表示可进金标）。"""
    miss = []
    facts = out.get("text_facts") or ""
    # 结果表一行既当事实又当决定（海南定安等）：事实没有单独成段，不进金标
    if len(re.sub(r"\s", "", facts)) < 30 or not GAMBLING_FACT.search(facts) or facts == out.get("text_decision"):
        miss.append("②事实不足")
    if not (out.get("outcome") or {}).get("type"):
        miss.append("③结果未解析")
    if not out.get("province_code"):
        miss.append("④无区划")
    if not out.get("subject_alias"):
        miss.append("本人不可指认")
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
    for a, b, _ in near:
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


# ---------- 主流程 ----------

def attach_region(out: dict, regions: dict[str, dict]) -> None:
    g = regions.get(out["_site"])
    if g and g.get("province_code"):
        out.update({"region": g["region_code"], "region_level": g["level"], "province": g["province"],
                    "province_code": g["province_code"]})


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")


def main() -> int:
    root = data_root().parent
    adir = root / "admin"
    src = [json.loads(l) for l in (adir / "web_cases.pre_deid.jsonl").read_text(encoding="utf-8").splitlines()]
    scope = [r for r in src if r.get("in_scope")]
    regions = load_regions()
    wl = r6_scan.load_whitelist()
    main_rows, outcome_rows, excluded, maps = [], [], [], []
    r6_soft = Counter()
    for rec in scope:
        out, dmap = deid_record(rec)
        attach_region(out, regions)
        hits = r6_scan.scan_record(out, wl)
        hard = [h for h in hits if h.hard]
        r6_soft.update(h.cat for h in hits if not h.hard)
        out["quality"]["r6_soft"] = sum(not h.hard for h in hits)
        if hard:
            excluded.append((out["id"], "R6:" + ",".join(sorted({h.cat for h in hard}))))
            continue
        miss = inclusion(out)
        if not miss:
            main_rows.append(out)
        elif miss == ["②事实不足"] or set(miss) <= {"②事实不足", "本人不可指认"}:
            outcome_rows.append(out)
        else:
            excluded.append((out["id"], ";".join(miss)))
            continue
        maps.append({"id": out["id"], "deid_map": dmap})
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
    write_jsonl(adir / "deid_map.jsonl", [m for m in maps if m["id"] in kept_ids])
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
    stats = {"pipeline_version": PIPELINE_VERSION, "in_scope": len(scope), "main": describe(main_rows),
             "outcomes_only": describe(outcome_rows), "excluded": len(excluded),
             "excluded_reasons": dict(Counter(r.split(":")[0] if r.startswith(("R6", "重复")) else r for _, r in excluded)),
             "dedupe_main": link_stats, "r6_first_pass_soft": dict(r6_soft)}
    # R6 第二次：交付文件整体扫描
    rc = r6_scan.main([str(out_main), str(out_oc)])
    stats["r6_second_pass"] = json.loads((adir / "r6_report.json").read_text(encoding="utf-8"))["hard_hit_records"]
    (adir / "build_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
