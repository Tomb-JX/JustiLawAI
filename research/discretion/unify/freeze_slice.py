"""Freeze a development-only, source-parser cohort without modifying source batches.

Selection is fail-closed and versioned. It does not certify reference labels or r7.
No quota is filled by weakening the fact/answer isolation rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from element_contract import digest
from s1 import data_root

VERSION = "dev-slice-v2"
# Deliberately conservative, including existing conclusion/penalty expressions.
# Reject, do not erase offending text and pretend the remaining record was re-labelled.
LEAKS = {
    "decision_language": r"决定(?:给予|予以|如下|对)|给予.{0,12}(?:处罚|罚款|拘留)|处以",
    "penalty_amount": r"罚款|(?:行政)?拘留.{0,12}[日天]",
    "legal_conclusion": r"(?:已|已经)?构成.{0,12}(?:违法|赌博)|情节(?:严重|轻微|特别轻微)|从轻处罚|减轻处罚|不予处罚",
    "legal_basis": r"(?:依据|根据).{0,30}(?:法|条例|规定)|第[零〇一二三四五六七八九十百\d]+条|《[^》]*(?:法|条例|规定)》",
}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_span(text, part):
    """Require a unique source occurrence; ambiguous provenance is rejected."""
    if not part or not part.strip():
        raise ValueError("facts_empty")
    a = text.find(part)
    if a < 0:
        raise ValueError("view_not_source_substring")
    if text.find(part, a + 1) >= 0:
        raise ValueError("view_source_ambiguous")
    return a, a + len(part)


def leak_reasons(text):
    return [name for name, pattern in LEAKS.items() if re.search(pattern, text)]


def eligible(rec):
    reasons = []
    q = rec.get("quality") or {}
    if not str(q.get("tier", "")).startswith(("L1", "L2")) or q.get("in_scope") is not True:
        reasons.append("not_in_scope_L1_L2")
    text, facts, target = (rec.get("text_full") or "", rec.get("text_facts") or "",
                           rec.get("subject_mention") or "")
    if not target or target not in text:
        reasons.append("target_not_source_grounded")
    decision = rec.get("text_decision") or ""
    try:
        source_span(text, decision)
    except ValueError:
        reasons.append("observed_decision_not_unique_source_span")
    if not rec.get("event_key") or not rec.get("doc_no_hash"):
        reasons.append("missing_event_or_document_key")
    try:
        fs = source_span(text, facts)
    except ValueError as exc:
        reasons.append(str(exc))
        fs = None
    reasons += leak_reasons(facts)
    oc = rec.get("outcome") or {}
    typ, days, fine = oc.get("type"), oc.get("detention_days"), oc.get("fine")
    if (type(days) is not int or type(fine) not in (int, float)
            or days < 0 or fine < 0 or not math.isfinite(fine) or oc.get("fine_masked")):
        reasons.append("invalid_or_masked_observed_outcome")
    else:
        matches = {"拘留": days > 0 and fine == 0, "拘留并处罚款": days > 0 and fine > 0,
                   "罚款": days == 0 and fine > 0, "警告": days == 0 and fine == 0,
                   "不予处罚": days == 0 and fine == 0}
        if not matches.get(typ, False):
            reasons.append("observed_outcome_inconsistent")
    return sorted(set(reasons)), fs


def build_slice(inputs: list[Path], out: Path, *, allowed_root: Path | None = None):
    if allowed_root and not out.resolve().is_relative_to(allowed_root.resolve()):
        raise ValueError("切片只写 $DATA/parsed2")
    if out.exists():
        raise FileExistsError("冻结目录不可复用")
    source_hashes, source_rows, excluded, chosen = {}, [], [], []
    seen_ids = set()
    for path in inputs:
        content = path.read_bytes()
        source_hashes[str(path.resolve())] = hashlib.sha256(content).hexdigest()
        for line in content.decode("utf-8-sig").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            rid = r["id"]
            if rid in seen_ids:
                raise ValueError(f"duplicate_record_id:{rid}")
            seen_ids.add(rid)
            source_rows.append(r)
            reasons, span = eligible(r)
            if reasons:
                excluded.append({"id": rid, "source_batch": path.parent.name, "reasons": reasons,
                                 "text_orig_sha256": sha(r.get("text_full") or "")})
                continue
            party = r.get("text_party") or ""
            party_reasons = leak_reasons(party)
            try:
                ps = source_span(r["text_full"], party) if party and not party_reasons else None
            except ValueError:
                ps = None
                party_reasons.append("party_not_unique_substring")
            view = []
            if ps and not (ps[0] < span[1] and span[0] < ps[1]):
                view.append({"type": "meta", "start": ps[0], "end": ps[1], "text": party})
            view.append({"type": "facts", "start": span[0], "end": span[1], "text": r["text_facts"]})
            if r["subject_mention"] not in "\n".join(v["text"] for v in view):
                excluded.append({"id": rid, "source_batch": path.parent.name,
                                 "reasons": ["target_not_in_allowed_view"],
                                 "text_orig_sha256": sha(r["text_full"])})
                continue
            # Group on the complete source pool, including excluded siblings.
            chosen.append((r, path, view, party_reasons))
    # Union source event keys, document hashes and duplicate original texts. This is
    # conservative grouping, not an assertion that coarse source keys are perfect.
    parent = {r["id"]: r["id"] for r in source_rows}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    keys = {}
    for r in source_rows:
        for name, value in (("event", r.get("event_key")), ("doc", r.get("doc_no_hash")),
                            ("text", sha(r.get("text_full") or ""))):
            if value:
                key = (name, value)
                if key in keys:
                    parent[find(r["id"])] = find(keys[key])
                keys[key] = r["id"]
    groups = {}
    for r in source_rows:
        groups.setdefault(find(r["id"]), []).append(r["id"])
    group_ids = {rid: "dev-event-" + digest(sorted(ids))[:16]
                 for ids in groups.values() for rid in ids}
    records, entries = [], []
    for r, path, view, party_reasons in chosen:
        event = group_ids[r["id"]]
        bucket = int(digest({"seed": "dev-20261018-v1", "event": event})[:8], 16) % 10
        split = "train" if bucket < 6 else "validation" if bucket < 8 else "test"
        common = {"id": r["id"], "event_id": event, "development_split": split,
                  "source_batch": path.parent.name, "source": r.get("source"),
                  "form": (r.get("quality") or {}).get("form"),
                  "text_orig_sha256": sha(r["text_full"]), "view_hash": digest(view)}
        # Only the allowed view is the model input. Full text/outcome remain separate.
        records.append({**common, "input": {"target": r["subject_mention"], "views": view,
                                            "facts_text": r["text_facts"],
                                            "meta_text": "\n".join(v["text"] for v in view if v["type"] == "meta")},
                        "source_text": r["text_full"], "observed_outcome": r["outcome"],
                        "observed_outcome_evidence": {
                            "start": source_span(r["text_full"], r["text_decision"])[0],
                            "end": source_span(r["text_full"], r["text_decision"])[1],
                            "quote": r["text_decision"]},
                        "metadata": {k: r.get(k) for k in ("region", "province", "law_version",
                                                           "behavior_date", "decision_date")},
                        "reference_elements": None, "label_provenance": "source-parser-observation",
                        "human_review": False, "release_approved": False})
        entries.append({**common, "facts_sha256": sha(r["text_facts"]),
                        "outcome_sha256": digest(r["outcome"]), "party_excluded_reasons": party_reasons,
                        "allowed_spans": [[v["start"], v["end"]] for v in view]})
    counts = lambda values: dict(Counter(values))
    report = {"version": VERSION, "source_hashes": source_hashes,
              "selection_rules": LEAKS, "source_records": len(source_rows), "records": len(records),
              "events": len({r["event_id"] for r in records}), "entries": entries, "excluded": excluded,
              "exclusion_counts": counts(reason for row in excluded for reason in row["reasons"]),
              "forms": counts(r["form"] for r in records),
              "batches": counts(r["source_batch"] for r in records),
              "outcomes": counts(r["observed_outcome"]["type"] for r in records),
              "law_versions": counts(r["metadata"]["law_version"] for r in records),
              "development_splits": counts(r["development_split"] for r in records),
              "bias": ["P1/P1b 富要素定向采样，不代表全部行政赌博案件",
                       "输入沿用来源事实段并经保守泄漏规则过滤，不是独立人工分段真值",
                       "历史处罚为来源解析观察，需引擎独立核查；无要素参考，不能算字段准确率",
                       "事件按来源事件键/文号/重复正文保守合并，可能过合并；非正式封存测试集"],
              "release_approved": False, "reference_elements_available": False}
    out.mkdir(parents=True, exist_ok=False)
    for name, value in (("records.jsonl", records), ("excluded.jsonl", excluded)):
        with (out / name).open("x", encoding="utf-8", newline="\n") as f:
            for row in value:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    report["artifact_hashes"] = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                                 for name in ("records.jsonl", "excluded.jsonl")}
    with (out / "manifest.json").open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    for source, fingerprint in source_hashes.items():
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != fingerprint:
            raise RuntimeError("source_changed_during_freeze:不得交付该切片")
    return report


def main():
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    report = build_slice(a.inputs, a.out, allowed_root=data_root() / "parsed2")
    print(json.dumps({k: v for k, v in report.items() if k not in ("entries", "excluded", "selection_rules")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
