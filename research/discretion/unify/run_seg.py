"""New-run S1 entry point using the shared durable, budgeted call boundary.

Existing s1.Runner is retained for historical replay. This CLI defaults to a plan;
paid execution requires a separately reviewed, frozen smoke order.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path

from element_contract import digest, implementation_snapshot, is_model_quality_failure, is_full_mode_hard_stop
from durable_calls import DurableCalls, read_rows, append
from s1 import (SYSTEM_PROMPT, TEXT_SLIM_SYSTEM_PROMPT, build_user_prompt, validate,
                validate_meta_fields, validate_prior_sentence_ids, data_root, load_config,
                PROMPT_VERSION)
from cleanse import sentence_table
from progress import load_prices
from provider_contract import freeze_execution
from budget_scope import from_order
from task_result import failure_record
from fact_spans import candidate_fact_clauses, fact_view, FACT_CANDIDATE_VERSION

VERSION = "seg-v2-durable-6-meta-prior"


def request_for(rec, *, clause_refine=False, meta_refine=False, prior_refine=False,
                text_slim=False):
    sentences = sentence_table(rec["cleaned_text"])
    if sentences != rec.get("sentences"):
        raise ValueError("sentence_table_version_mismatch")
    base_prompt = TEXT_SLIM_SYSTEM_PROMPT if text_slim else SYSTEM_PROMPT
    if text_slim and (meta_refine or prior_refine):
        raise ValueError("text_slim 与 meta_refine/prior_refine 互斥（瘦身版不产这两字段）")
    system = base_prompt
    if rec.get("zones_det"):
        # This variant removes BOTH zoning instructions and the zones output example.
        fields = base_prompt[base_prompt.index("【字段（"):]
        start = fields.index('{"zones":')
        end = fields.index('"subject":', start)
        system = "你是行政文书字段抽取器。分区由已验证的确定性规则负责，只输出 JSON 字段。\n" + fields[:start] + "{" + fields[end:]
    user = build_user_prompt(rec["form"], rec["source_type"],
                             [rec["cleaned_text"][a:b] for a, b in sentences], rec.get("subject_mention", ""))
    if clause_refine:
        candidates = candidate_fact_clauses(rec["cleaned_text"], sentences, version="v2")
        system += ("\n【句内事实片段】对下列候选子句，只在事实行为被原文陈述时选择其 ID，"
                   "纯法律定性、处罚结论、证据、元数据和‘现查明’等栏目标题一律不选。"
                   "独立的日期子句不要单独选择；紧邻已选行为的纯日期由系统保留为上下文。"
                   "账号尾号与日期粘连的子句不要为了保留日期而整段选择。"
                   "关键词只是候选来源，不代表事实。"
                   "即使主 zone 标为 reasoning/evidence，事实子句仍可选；"
                   "整句事实不要因相邻法律结论而丢弃，整句结论也不得因出现赌博词而选入。"
                   "输出额外字段 fact_clause_ids（升序不重复整数数组；无事实选 []）。"
                   "同时输出 fact_clause_roles 对象，键为每个已选 ID 的字符串，值只能是"
                   "behavior_core（本人行为）、other_case_fact（自首等其他情节）或"
                   "context_time（明确的事实时间）；无选择则为 {}。"
                   "主 zones 仍必须完整铺满句表。")
        user += "\n候选子句（只选 ID，不计算字符偏移）：\n" + "\n".join(
            f"[C{c['id']}/S{c['sentence']}] {c['text']}" for c in candidates)
    if meta_refine:
        system += ("\n【本次必须】输出 meta_fields：meta 区每句按字段片段标注 "
                   "person/case/prior/outcome/other；quote 逐字来自该句。"
                   "处罚种类/结果/金额/依据/执行必须是 outcome，不得标成 person/case/prior。")
    if prior_refine:
        system += ("\n【本次必须】输出 prior_sentence_ids：只填陈述本人前科/曾受治安处罚/"
                   "曾被判刑/曾被处理的句子 ID，可在 meta/facts/reasoning 任何区；"
                   "不要填本案决定句；没有则 []。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validated_output(payload, rec, *, clause_refine=False, meta_refine=False, prior_refine=False):
    if not isinstance(payload, dict):
        raise ValueError("S1 输出必须为对象")
    output = copy.deepcopy(payload)
    if rec.get("zones_det"):
        output["zones"] = copy.deepcopy(rec["zones_det"])
    required = {"subject", "outcome", "dates", "review", "gambling", "confidence"}
    if required - output.keys():
        raise ValueError("S1_missing_fields:" + ",".join(sorted(required - output.keys())))
    oc = output.get("outcome")
    if (not isinstance(oc, dict) or type(oc.get("detention_days")) is not int
            or type(oc.get("fine")) not in (int, float)
            or oc["detention_days"] < 0 or oc["fine"] < 0 or not math.isfinite(oc["fine"])):
        raise ValueError("S1_invalid_outcome_numbers")
    issues = validate(output, n_sentences=len(rec["sentences"]))
    if issues:
        raise ValueError("S1_invalid:" + ";".join(issues))
    if clause_refine:
        if "fact_clause_ids" not in output:
            raise ValueError("S1_missing_fact_clause_ids")
        if "fact_clause_roles" not in output:
            raise ValueError("S1_missing_fact_clause_roles")
        # Candidate policy is frozen by this runner, never accepted from the model.
        output["fact_candidate_version"] = "v2"
        fact_view(rec, output)
    else:
        # clause-refine 关闭（叙述式 facts-only 文本路径）：facts 默认整段 facts 区
        # （fact_clause_ids=[]）——等价于 3.8 对叙述式几乎总输出 [] 的惰性回退
        # （706 实测叙述式 365/370 空、P3–P7 canary 28/28 空）。让较轻模型免去
        # candidate_fact_clauses 的 C号/S号 双编号子句引用（弱模型在此系统性混淆），
        # facts 纯度仍由下游 leak 闸 + S3 守。fact_view 校验整段回退可建。
        output.setdefault("fact_clause_ids", [])
        fact_view(rec, output)
    if meta_refine:
        validate_meta_fields(rec, output)
    if prior_refine:
        validate_prior_sentence_ids(rec, output)
    return output


def main():
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ids", type=Path, help="JSON array of frozen record IDs")
    p.add_argument("--clause-refine", action="store_true", help="试点：要求模型选择原文子句 ID")
    p.add_argument("--meta-refine", action="store_true", help="要求并校验字段级 meta_fields")
    p.add_argument("--prior-refine", action="store_true", help="要求并校验 prior_sentence_ids")
    p.add_argument("--text-slim", action="store_true",
                   help="湖文本 facts-only 路径瘦身提示词：去 meta_fields/prior_sentence_ids"
                        "（文本路径不消费），省 reasoning；与 --meta-refine/--prior-refine 互斥")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--order", type=Path)
    p.add_argument("--full", action="store_true",
                   help="user-authorized full S1 batch; bypass smoke12/12-record/4-yuan gates")
    p.add_argument("--provider", default="deepseek", help="full-mode provider config key")
    p.add_argument("--cap", type=float, default=1000.0, help="full-mode execution safety cap")
    p.add_argument("--max-calls", type=int, default=3000, help="full-mode call safety ceiling")
    p.add_argument("--max-input-bytes", type=int, default=200000, help="full-mode request byte ceiling")
    a = p.parse_args()
    if not a.out.resolve().is_relative_to((data_root() / "s1_runs").resolve()):
        p.error("只写新的 $DATA/s1_runs 批次")
    rows = [r for r in read_rows(a.batch) if (r.get("prefilter") or {}).get("release")]
    if a.ids:
        selected = json.loads(a.ids.read_text("utf-8"))
        by_id = {r["id"]: r for r in rows}
        if len(selected) != len(set(selected)) or set(selected) - set(by_id):
            p.error("ID 重复或不在放行输入")
        rows = [by_id[rid] for rid in selected]
    requests = {r["id"]: request_for(r, clause_refine=a.clause_refine, meta_refine=a.meta_refine,
                                     prior_refine=a.prior_refine, text_slim=a.text_slim) for r in rows}
    frozen = {"version": VERSION, "semantic_prompt_base": PROMPT_VERSION,
              "clause_refine": a.clause_refine, "meta_refine": a.meta_refine,
              "prior_refine": a.prior_refine, "text_slim": a.text_slim,
              "fact_candidate_version": FACT_CANDIDATE_VERSION if a.clause_refine else None,
              "implementation": implementation_snapshot(),
              "source_sha256": hashlib.sha256(a.batch.read_bytes()).hexdigest(),
              "ids": [r["id"] for r in rows], "request_hashes": {rid: digest(msg) for rid, msg in requests.items()}}
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = a.out / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text("utf-8")) != frozen:
        p.error("旧批次或不同请求，不允许覆盖 manifest")
    if not manifest.exists():
        manifest.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if not a.execute:
        print(json.dumps({"records": len(rows), "plan_hash": digest(frozen), "executed": False}))
        return
    if a.full:
        if a.order:
            p.error("--full 与 --order 二选一")
        cap, maximum = float(a.cap), int(a.max_calls)
        if not (cap > 0 and maximum > 0):
            p.error("--full 须提供正的 cap/max-calls")
        order = {
            "stage": "full",
            "plan_hash": digest(frozen),
            "free_replay_pass": True,
            "review_record": "user-authorized-full-2026-10-21",
            "executor_review": "zcode-full-s1",
            "engine_ack": "user-authorized-full",
            "provider": a.provider,
            "cap": cap,
            "max_calls": maximum,
            "max_input_bytes": a.max_input_bytes,
            "budget_scope": {"path": str((a.out / "budget").resolve()),
                             "cap": cap, "max_calls": maximum},
        }
    else:
        if not a.order:
            p.error("须提供冻结工单，默认不调模型")
        order = json.loads(a.order.read_text("utf-8"))
        if (order.get("plan_hash") != digest(frozen) or order.get("free_replay_pass") is not True
                or not all(order.get(k) for k in ("review_record", "executor_review", "engine_ack"))
                or order.get("stage") != "smoke12" or len(rows) > 12
                or not 0 < order.get("cap", 0) <= 4 or not 0 < order.get("max_calls", 0) <= 252):
            p.error("仅接受已复核首段小批工单；扩量须另审")
    providers, _, _ = load_config()
    primary = order["provider"]
    prices = load_prices(data_root() / "config/s1_prices.json")
    freeze_execution(a.out, order, providers, prices)
    calls = DurableCalls(a.out, providers, prices=prices, budget_scope=from_order(order, data_root()),
                         cap=order["cap"], max_calls=order["max_calls"],
                         max_input_bytes=order["max_input_bytes"], execute=True)
    lock = a.out / "RUNNING.lock"
    with lock.open("x", encoding="ascii") as f:
        f.write(str(os.getpid()))
    try:
        results = []
        for rec in rows:
            if implementation_snapshot() != frozen["implementation"]:
                raise RuntimeError("implementation_changed:中途不换代码或提示")
            rid = rec["id"]
            try:
                payload = calls.call(primary, requests[rid], context={"id": rid, "plan": digest(frozen)},
                                     validator=lambda value: validated_output(value, rec, clause_refine=a.clause_refine,
                                                                              meta_refine=a.meta_refine,
                                                                              prior_refine=a.prior_refine), repairs=1)
            except Exception as exc:
                append(a.out / 'diagnostics.jsonl', failure_record(rid, exc))
                # full 扩产：模型质量/传输/单条故障一律隔离该条继续；只有预算/契约/授权类硬停。
                if a.full and not is_full_mode_hard_stop(exc):
                    continue
                raise
            if implementation_snapshot() != frozen['implementation']:
                raise RuntimeError('implementation_changed_during_call')
            results.append({"id": rid, "ok": True, "output": validated_output(payload, rec, clause_refine=a.clause_refine,
                                                                              meta_refine=a.meta_refine,
                                                                              prior_refine=a.prior_refine),
                            "validation_errors": [], "request_hash": digest(requests[rid]),
                            "prompt_version": VERSION, "release_approved": False})
            # Commit each success before advancing. Restart revalidates cached raw.
            temp = a.out / "outputs.tmp"
            with temp.open("w", encoding="utf-8", newline="\n") as f:
                for row in results:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            temp.replace(a.out / "outputs.jsonl")
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
