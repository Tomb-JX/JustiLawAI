"""G2.3a 开发诊断：本地学生原型只作推理探针，不生成参考标签。

对冻结切片 validation 按历史处罚类型取样；只发送 input.views，报告结构、
证据与丢弃，不计算字段准确率或写回 parsed-2。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "justilaw-api"))
from app.discretion import extract as ex  # noqa: E402
from app.discretion.schema import GROUPS, iter_fields  # noqa: E402
from dev_slice_first_run import DEFAULT_SLICE, audit, load_slice, text_input  # noqa: E402


def select(rows: list[dict], per_type: int) -> list[dict]:
    types: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["development_split"] == "validation":
            types[r["observed_outcome"]["type"]].append(r)
    return [r for typ in sorted(types) for r in sorted(types[typ], key=lambda x: x["id"])[:per_type]]


def diagnose(result: ex.ExtractionResult, row: dict) -> dict:
    source = row["source_text"]
    views = row["input"]["views"]
    valued = invalid_evidence = 0
    evidence_count = 0
    valued_by_field = Counter()
    evidence_by_field = Counter()
    groups = result.elements.model_dump(mode="json")
    for group in GROUPS:
        for name, item in groups[group].items():
            if item["value"] is None:
                continue
            valued += 1
            path = f"{group}.{name}"
            valued_by_field[path] += 1
            for ev in item["evidence"]:
                evidence_count += 1
                evidence_by_field[path] += 1
                if not any(ev["quote"] in v["text"] and
                           source[v["start"]:v["end"]] == v["text"] for v in views):
                    invalid_evidence += 1
    try:
        raw_items = json.loads(result.raw)["items"]
        raw_valid = isinstance(raw_items, list)
    except (ValueError, KeyError, TypeError):
        raw_items, raw_valid = [], False
    return {"id": row["id"], "ok": True, "raw_json_valid": raw_valid,
            "raw_items": len(raw_items), "valued_fields": valued,
            "valued_by_field": dict(valued_by_field),
            "evidence_by_field": dict(evidence_by_field),
            "evidence_quotes": evidence_count, "evidence_outside_allowed_view": invalid_evidence,
            "dropped": dict(Counter(d.get("reason", "unknown") for d in result.dropped)),
            "dropped_by_field_reason": {f"{path}|{reason}": n
                                        for (path, reason), n in Counter(
                                            (d.get("path", "unknown"), d.get("reason", "unknown"))
                                            for d in result.dropped).items()},
            "seconds": result.seconds, "eval_tokens": result.eval_tokens}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    ap.add_argument("--per-type", type=int, default=4)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows, manifest, hashes = load_slice(args.slice)
    checked = audit(rows, manifest)
    if checked["problems"]:
        raise SystemExit("开发切片独立核查失败，停止 M1 推理")
    chosen = select(rows, args.per_type)
    out = args.out or args.slice.parents[1] / "engine" / "development" / f"{args.slice.name}-m1-probe.json"
    if out.exists():
        raise FileExistsError("M1 探针报告不可原地覆盖；指定新 --out")
    report = {"slice": args.slice.name, "manifest_sha256": hashes["manifest.json"],
              "model": ex.DEFAULT_MODEL, "mode": "student_inference_diagnostic_only",
              "sample_method": f"validation 每处罚类型按 ID 取前 {args.per_type} 条",
              "sample_n": len(chosen), "ontology_fields": len(list(iter_fields())),
              "field_accuracy": None, "field_accuracy_reason": "reference_elements=null",
              "records": []}
    for index, row in enumerate(chosen, 1):
        try:
            result = ex.extract(text_input(row), row["input"]["target"])
            item = diagnose(result, row)
        except Exception as exc:
            item = {"id": row["id"], "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        report["records"].append(item)
        print(f"{index}/{len(chosen)} {row['id']} {'ok' if item['ok'] else 'failed'}", flush=True)
    valid = [r for r in report["records"] if r["ok"]]
    report["summary"] = {"completed": len(valid), "failed": len(chosen) - len(valid),
                         "raw_json_valid": sum(r["raw_json_valid"] for r in valid),
                         "raw_items": sum(r["raw_items"] for r in valid),
                         "valued_fields": sum(r["valued_fields"] for r in valid),
                         "valued_by_field": dict(sum((Counter(r["valued_by_field"]) for r in valid), Counter())),
                         "evidence_by_field": dict(sum((Counter(r["evidence_by_field"]) for r in valid), Counter())),
                         "evidence_quotes": sum(r["evidence_quotes"] for r in valid),
                         "evidence_outside_allowed_view": sum(r["evidence_outside_allowed_view"] for r in valid),
                         "dropped": dict(sum((Counter(r["dropped"]) for r in valid), Counter())),
                         "dropped_by_field_reason": dict(sum((Counter(r["dropped_by_field_reason"])
                                                              for r in valid), Counter()))}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"out": str(out), "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
