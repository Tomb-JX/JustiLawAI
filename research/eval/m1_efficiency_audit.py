"""M1 效率检察辅助系统：从 m1_dev_slice_probe.py 输出分析提取效率。

读取 M1 探针 JSON，产出效率报告：延迟分布、token 效率、字段级瓶颈、
吞吐量估算与全量扩展预测。不调用模型，纯离线分析。

用法：python m1_efficiency_audit.py [--probe m1-validation-v3.json] [--scale N] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _percentile(values: list[float], pct: float) -> float:
    """计算百分位数（最近秩方法）。"""
    if not values:
        return 0.0
    s = sorted(values)
    k = int(len(s) * pct / 100)
    k = min(k, len(s) - 1)
    return s[k]


def audit(probe: dict, *, scale_to: int | None = None) -> dict:
    """从 M1 探针 JSON 产出效率报告。

    Args:
        probe: m1_dev_slice_probe.py 的完整输出 JSON。
        scale_to: 如果给定，按当前切片吞吐量估算处理 scale_to 条所需时间。
    """
    records = probe.get("records", [])
    summary = probe.get("summary", {})
    valid = [r for r in records if r.get("ok")]
    n = len(valid)
    if n == 0:
        return {"error": "no valid records"}

    # --- 延迟 ---
    seconds = [r["seconds"] for r in valid if "seconds" in r]
    total_time = sum(seconds)
    mean_time = total_time / len(seconds) if seconds else 0
    latency = {
        "records_with_timing": len(seconds),
        "total_seconds": round(total_time, 1),
        "mean_seconds": round(mean_time, 2),
        "p50_seconds": round(_percentile(seconds, 50), 2),
        "p90_seconds": round(_percentile(seconds, 90), 2),
        "p95_seconds": round(_percentile(seconds, 95), 2),
        "p99_seconds": round(_percentile(seconds, 99), 2),
        "min_seconds": round(min(seconds), 2) if seconds else None,
        "max_seconds": round(max(seconds), 2) if seconds else None,
    }
    # 最慢 5 条
    slow = sorted(valid, key=lambda r: r.get("seconds", 0), reverse=True)[:5]
    latency["slowest_records"] = [
        {"id": r["id"], "seconds": round(r["seconds"], 2),
         "valued_fields": r["valued_fields"], "eval_tokens": r.get("eval_tokens")}
        for r in slow
    ]

    # --- Token ---
    tokens = [r["eval_tokens"] for r in valid if "eval_tokens" in r]
    total_tokens = sum(tokens)
    token_stats = {
        "records_with_tokens": len(tokens),
        "total_tokens": total_tokens,
        "mean_tokens": round(total_tokens / len(tokens), 0) if tokens else 0,
        "tokens_per_second": round(total_tokens / total_time, 1) if total_time else None,
        "tokens_per_valued_field": round(total_tokens / sum(r["valued_fields"] for r in valid), 1)
        if sum(r["valued_fields"] for r in valid) else None,
    }

    # --- 吞吐量 ---
    throughput = {
        "records_per_second": round(n / total_time, 3) if total_time else None,
        "seconds_per_record": round(total_time / n, 2) if n else None,
    }

    # --- 字段级效率 ---
    valued_by_field = Counter()
    evidence_by_field = Counter()
    dropped_by_reason = Counter()
    dropped_by_field_reason = Counter()
    for r in valid:
        valued_by_field.update(r.get("valued_by_field", {}))
        evidence_by_field.update(r.get("evidence_by_field", {}))
        dropped_by_reason.update(r.get("dropped", {}))
        dropped_by_field_reason.update(r.get("dropped_by_field_reason", {}))

    # 每字段提取率 = 有值字段数 / 记录数
    field_extraction_rate = {
        path: round(count / n, 3)
        for path, count in sorted(valued_by_field.items(), key=lambda x: -x[1])
    }
    # 每字段丢弃率 = 该字段丢弃数 / (该字段有值 + 该字段丢弃)
    field_drop_detail = {}
    for key, count in dropped_by_field_reason.items():
        path, reason = key.split("|", 1) if "|" in key else (key, "unknown")
        entry = field_drop_detail.setdefault(path, {"total_dropped": 0, "reasons": {}})
        entry["total_dropped"] += count
        entry["reasons"][reason] = count

    field_efficiency = {}
    all_fields = sorted(set(valued_by_field) | set(field_drop_detail))
    for path in all_fields:
        v = valued_by_field.get(path, 0)
        e = evidence_by_field.get(path, 0)
        d = field_drop_detail.get(path, {}).get("total_dropped", 0)
        total_attempted = v + d
        field_efficiency[path] = {
            "valued": v,
            "evidence_quotes": e,
            "dropped": d,
            "extraction_rate": round(v / total_attempted, 3) if total_attempted else None,
            "evidence_per_valued": round(e / v, 2) if v else None,
            "drop_reasons": field_drop_detail.get(path, {}).get("reasons", {}),
        }

    # --- 瓶颈识别 ---
    # 提取率最低的 5 个字段
    bottleneck_fields = sorted(
        [(p, f) for p, f in field_efficiency.items() if f["dropped"] > 0],
        key=lambda x: -x[1]["dropped"]
    )[:5]
    bottlenecks = {
        "top_dropped_fields": [
            {"field": p, "dropped": f["dropped"],
             "extraction_rate": f["extraction_rate"],
             "reasons": f["drop_reasons"]}
            for p, f in bottleneck_fields
        ],
        "total_dropped": sum(dropped_by_reason.values()),
        "drop_reasons": dict(dropped_by_reason),
    }

    # --- 全量扩展估算 ---
    scaling = None
    if scale_to and n > 0:
        est_seconds = total_time / n * scale_to
        est_tokens = int(total_tokens / n * scale_to)
        scaling = {
            "target_records": scale_to,
            "estimated_total_hours": round(est_seconds / 3600, 1),
            "estimated_total_tokens": est_tokens,
            "estimated_total_days_8h": round(est_seconds / 3600 / 8, 1),
        }

    # --- 汇总 ---
    return {
        "task": "M1-efficiency-audit",
        "probe_source": probe.get("slice", "unknown"),
        "model": probe.get("model", "unknown"),
        "sample_method": probe.get("sample_method", "unknown"),
        "sample_n": n,
        "failed": probe.get("summary", {}).get("failed", 0),
        "latency": latency,
        "tokens": token_stats,
        "throughput": throughput,
        "field_extraction_rate": field_extraction_rate,
        "field_efficiency": field_efficiency,
        "bottlenecks": bottlenecks,
        "scaling_estimate": scaling,
        "conventions": {
            "background_execution": "模型调用命令统一使用 run_in_background，不阻塞前台会话",
            "probe_mode": "M1 探针只作学生端诊断，不产标签；字段准确率在 reference_elements 到位前标暂缺",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M1 效率检察辅助系统")
    ap.add_argument("--probe", type=Path, required=True,
                    help="m1_dev_slice_probe.py 的输出 JSON")
    ap.add_argument("--scale", type=int, default=None,
                    help="估算处理 N 条记录所需时间与 token")
    ap.add_argument("--out", type=Path, default=None,
                    help="输出 JSON 路径（不给则打印摘要）")
    args = ap.parse_args()
    probe = json.loads(args.probe.read_text("utf-8"))
    report = audit(probe, scale_to=args.scale)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(f"效率报告已写入: {args.out}", file=sys.stderr)

    # 打印摘要
    lat = report["latency"]
    tok = report["tokens"]
    thr = report["throughput"]
    bn = report["bottlenecks"]
    print(f"=== M1 效率审计 ({report['sample_n']} 条, {report['model']}) ===")
    print(f"延迟: 总 {lat['total_seconds']}s, 均 {lat['mean_seconds']}s, "
          f"P50={lat['p50_seconds']}s P90={lat['p90_seconds']}s P95={lat['p95_seconds']}s")
    print(f"Token: 总 {tok['total_tokens']}, 均 {tok['mean_tokens']}, "
          f"{tok['tokens_per_second']} tok/s, {tok['tokens_per_valued_field']} tok/field")
    print(f"吞吐: {thr['records_per_second']} rec/s, {thr['seconds_per_record']} s/rec")
    print(f"丢弃: 总 {bn['total_dropped']} 项, 原因: {bn['drop_reasons']}")
    if bn["top_dropped_fields"]:
        print("瓶颈字段:")
        for f in bn["top_dropped_fields"]:
            print(f"  {f['field']}: dropped={f['dropped']}, rate={f['extraction_rate']}, reasons={f['reasons']}")
    if report["scaling_estimate"]:
        s = report["scaling_estimate"]
        print(f"全量估算 ({s['target_records']} 条): {s['estimated_total_hours']}h "
              f"({s['estimated_total_days_8h']} 天×8h), {s['estimated_total_tokens']} tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())