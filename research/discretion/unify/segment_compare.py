"""分段级双轨对照（架构 v2 §4 灰度路径的"边界 F1"落地）：模型分段 vs parse.py 正则分段。

两侧坐标都归一到原文空间再比：
- 正则侧：parsed-1 的 segments 起止（原文坐标，L1/L2 实测 100% 齐）；
- 模型侧：S1 引文 → S2 定位（cleaned 坐标）→ OffsetIndex 映射回原文坐标。
指标：逐类型/逐记录的 precision、recall、F1（字符交集口径），并给"正则侧有而模型侧空"的分段缺失统计。

用法：
  python research/discretion/unify/segment_compare.py \
      --batch <parsed-1 records.jsonl> --run <s1_runs/<id>> [--out dir]
产物：segment_stats.json（逐类型 F1 表）＋ segment_divergences.csv（逐记录逐类型 IoU<0.5 的件）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locate import OffsetIndex, locate  # noqa: E402

SEG_TYPES = ["facts", "evidence", "reasoning", "decision", "review"]


def model_spans(output: dict, cleaned: str, index: OffsetIndex) -> dict[str, tuple[int, int] | None]:
    """S1 引文 → 原文坐标（仅接受唯一/空白归一命中；多处以首处计并标注）。"""
    spans: dict[str, tuple[int, int] | None] = {}
    for s in (output.get("segments") or []):
        typ = s.get("type")
        if typ not in SEG_TYPES:
            continue
        loc = locate(cleaned, s.get("quote") or "", index)
        if loc.clean_start >= 0 and loc.status in ("exact_unique", "exact_multi", "ws_unique"):
            spans[typ] = (loc.orig_start, loc.orig_end)
        else:
            spans[typ] = None
    return spans


def regex_spans(rec: dict) -> dict[str, tuple[int, int]]:
    segs = rec.get("segments") or {}
    out = {}
    for typ in SEG_TYPES:
        pos = segs.get(f"text_{typ}")
        if isinstance(pos, list) and len(pos) == 2 and pos[1] > pos[0]:
            out[typ] = (pos[0], pos[1])
    return out


def prf(model: tuple[int, int] | None, regex: tuple[int, int] | None) -> dict:
    """字符级 P/R/F1。model=None 记召回缺失；regex=None 记精确缺失（互有缺失单独计数）。"""
    if model is None and regex is None:
        return {"p": None, "r": None, "f1": None, "both_missing": True}
    if model is None:
        return {"p": 0.0, "r": None, "f1": 0.0, "model_missing": True}
    if regex is None:
        return {"p": None, "r": 0.0, "f1": None, "regex_missing": True}
    inter = max(0, min(model[1], regex[1]) - max(model[0], regex[0]))
    p = inter / (model[1] - model[0]) if model[1] > model[0] else 0.0
    r = inter / (regex[1] - regex[0]) if regex[1] > regex[0] else 0.0
    f1 = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return {"p": round(p, 4), "r": round(r, 4), "f1": round(f1, 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="parsed-1 records.jsonl（正则侧）")
    ap.add_argument("--run", required=True, help="s1_runs/<id>（模型侧）")
    ap.add_argument("--unified", required=True, help="unified_raw records.jsonl（模型侧 cleaned_text）")
    ap.add_argument("--edits", default="", help="edits.rle.jsonl（缺省取 --unified 同目录）")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    recs = {r["id"]: r for r in (json.loads(l) for l in open(a.batch, encoding="utf-8"))}
    unified = {r["id"]: r for r in (json.loads(l) for l in open(a.unified, encoding="utf-8"))}
    edits_path = Path(a.edits) if a.edits else Path(a.unified).parent / "edits.rle.jsonl"
    edits = {}
    for l in open(edits_path, encoding="utf-8"):
        e = json.loads(l)
        edits[e["id"]] = e
    outs = [json.loads(l) for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8")]
    outs = [o for o in outs if o.get("ok")]

    per_type: dict[str, list[float]] = defaultdict(list)
    rows = []
    missing = defaultdict(int)
    n_compared = 0
    for o in outs:
        rec = recs.get(o["id"])
        uni = unified.get(o["id"])
        if rec is None or uni is None:
            continue
        index = OffsetIndex(edits[o["id"]])
        ms = model_spans(o["output"], uni.get("cleaned_text") or "", index)
        rs = regex_spans(rec)
        if not rs:
            continue   # 正则侧无分段坐标（未分段件）——不计入分母，单独计数
        n_compared += 1
        for typ in SEG_TYPES:
            m, r = ms.get(typ), rs.get(typ)
            if m is None:
                missing[typ] += 1
            res = prf(m, r)
            if res.get("f1") is not None:
                per_type[typ].append(res["f1"])
            rows.append({"id": o["id"], "type": typ, **res})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "segment_divergences.csv", "w", encoding="utf-8-sig", newline="") as f:
        fields = ["id", "type", "p", "r", "f1"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    stats = {
        "n_records_compared": n_compared,
        "by_type": {typ: {
            "n": len(v),
            "f1_mean": round(sum(v) / len(v), 4) if v else None,
            "f1_ge_08": sum(1 for x in v if x >= 0.8),
        } for typ, v in sorted(per_type.items())},
        "model_missing": dict(missing),
        "note": "模型侧=引文定位原文坐标；正则侧=parsed-1 segments。IoU<0.5 明细见 csv。正则分段是参照非真值",
    }
    (out / "segment_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
