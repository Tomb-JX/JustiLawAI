"""E-02：冻结切片处罚语义抽样与异常清单；只报告，不改原始记录。"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dev_slice_first_run import DEFAULT_SLICE, _NUM, _stated_number, load_slice

_NO_EXECUTION = re.compile(r"不予执行行政拘留|不执行行政拘留|行政拘留不执行")


def review(rows: list[dict]) -> dict:
    by_id = {r["id"]: r for r in rows}
    items: list[dict] = []

    def add(rid: str, field: str, finding: str, conclusion: str, suggestion: str):
        items.append({"id": rid, "field": field, "finding": finding,
                      "conclusion": conclusion, "suggestion": suggestion})

    for r in rows:
        rid = r["id"]
        oc = r["observed_outcome"]
        quote = r["observed_outcome_evidence"]["quote"]
        if oc["fine"] == 0 and re.search(r"(?:罚款.{0,12}元|[0-9一二三四五六七八九十百千万]+元罚款)", quote):
            add(rid, "observed_outcome.fine", "处罚引文含明确罚款，解析值为 0",
                "确认解析与引文不一致", "来源解析方复核金额与处罚类型，另起版本修复")
        if oc["detention_not_executed"] != "是" and _NO_EXECUTION.search(quote):
            add(rid, "observed_outcome.detention_not_executed", "引文明确不执行拘留，解析值为否",
                "确认解析与引文不一致", "来源解析方复核执行标志，另起版本修复")

    # 原文逐条核读：同一人匿名写法与决定全名，不能由字面规则认定同一人。
    if "P-1216" in by_id:
        add("P-1216", "subject/outcome attribution", "事实段为匿名写法，决定段为全名",
            "待独立复核", "核对原始文书中的本人对应关系；确认前隔离此条的处罚目标")
    if "P-1165" in by_id:
        add("P-1165", "observed_outcome.fine", "处罚引文末段给出合并执行罚款一千元，解析值为五百元",
            "确认解析与末段合并结果不一致", "来源解析方复核合并罚款与事件/本人归属，另起版本修复")
        add("P-1165", "observed_outcome.detention_days", "两段各拘留十日，末段合并执行二十日",
            "二十日与引文一致", "保留合并执行标志并复核同一本人及两行为")
    if "P-1082" in by_id:
        add("P-1082", "observed_outcome.detention_days", "决定段十五日另提折抵，不等于零日处罚",
            "十五日与引文一致", "另按执行标志问题复核实际执行")

    # “不可机械核对”主要是没有该处罚的零值；固定取样，逐条给结论。
    samples = []
    for field, pattern, word in (("detention_days", rf"(?:行政)?拘留\s*({_NUM})\s*[日天]", "拘留"),
                                 ("fine", rf"罚款\s*(?:人民币)?\s*({_NUM})\s*元", "罚款")):
        eligible = [r for r in rows if r["observed_outcome"][field] == 0 and
                    _stated_number(r["observed_outcome_evidence"]["quote"], pattern) is None]
        for r in sorted(eligible, key=lambda x: x["id"])[:8]:
            quote = r["observed_outcome_evidence"]["quote"]
            samples.append({"id": r["id"], "field": f"observed_outcome.{field}",
                            "conclusion": ("处罚引文未写该处罚，零值与引文相容"
                                           if word not in quote else "引文出现该处罚，需单独复核"),
                            "scope": "只核本条处罚引文，不扩展到整篇文书"})
    return {"records": len(rows), "issues": items, "sampled_uncheckable": samples,
            "issue_ids": sorted({x["id"] for x in items}),
            "source_unchanged": True,
            "qualification": "人工核读与有限文本规则；未推断未提供的别名或法律事实。"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows, _, hashes = load_slice(args.slice)
    result = {"task": "E-02", "manifest_sha256": hashes["manifest.json"], "review": review(rows)}
    out = args.out or args.slice.parents[1] / "engine" / "development" / f"{args.slice.name}-quality-review.json"
    if out.exists():
        raise FileExistsError("复核清单不可覆盖；指定新 --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"out": str(out), "issues": len(result["review"]["issues"]),
                      "issue_ids": result["review"]["issue_ids"],
                      "sampled_uncheckable": len(result["review"]["sampled_uncheckable"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
