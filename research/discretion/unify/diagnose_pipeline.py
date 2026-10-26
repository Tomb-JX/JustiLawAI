"""Offline graph/normalizer/section/36-field report for frozen development inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from durable_calls import append, read_rows
from element_contract import engine_contract, contract_snapshot, validate_located
from evidence_graph import build_graph, classify_graph_bindings
from field_rules import field_catalog
from normalization import backend_fingerprint
from observability import diagnose, summarize
from section_refs import fine_references
from s1 import data_root

VERSION = "pipeline-diagnostics-1"


def diagnose_batch(source: Path, out: Path):
    if out.exists():
        raise FileExistsError("diagnostic_batch_immutable")
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
    engine = engine_contract()
    contract, catalog = contract_snapshot(engine), field_catalog(engine)
    backend = backend_fingerprint()
    rows, fields, ids = [], [], set()
    totals = Counter()
    for record in read_rows(source):
        rid = record["id"]
        if rid in ids:
            raise ValueError("duplicate_input_id")
        ids.add(rid)
        original = record.get("source_text") or record.get("text_full") or ""
        if not original:
            continue
        expected_hash = record.get("text_orig_sha256")
        if expected_hash and hashlib.sha256(original.encode("utf-8")).hexdigest() != expected_hash:
            raise ValueError("diagnostic_input_hash_mismatch")
        inp = record.get("input") or {}
        views = inp.get("views") or record.get("facts_view") or []
        if not views:
            # Construct views from segmented text fields (P1 format)
            for field, vtype in (("text_facts", "facts"), ("text_party", "meta")):
                text = record.get(field) or ""
                if text and text in original:
                    start = original.index(text)
                    views.append({"id": f"{vtype}.1", "start": start, "end": start + len(text),
                                  "text": text, "type": vtype})
        if not views:
            raise ValueError("missing_exact_allowed_view")
        target = inp.get("target") or record.get("subject_mention")
        try:
            graph = build_graph(original, views, target, record.get("subject_aliases") or (), event_id=record.get("event_id"))
        except ValueError:
            # Skip records where target is not in text (deidentified/mismatched)
            continue
        classify_graph_bindings(graph, aliases=record.get("subject_aliases") or ())
        execution = "valid" if record.get("elements_status") == "candidate_validated" else "not_available"
        if execution == 'valid':
            try:
                validate_located(record.get('elements'), original, engine, [(v['start'],v['end']) for v in views])
            except (ValueError, TypeError):
                execution = 'invalid'
        diag_record = {**record, "input": {**inp, "views": views}}
        observed = diagnose(diag_record, graph, catalog, execution=execution)
        full_views = [{"type": "audit-fulltext", "start": 0, "end": len(original), "text": original}]
        references = fine_references(original, full_views)
        rows.append({"id": rid, "graph": graph, "section_references_audit_only": references,
                     "semantic_approved": False, "release_approved": False})
        fields.append({"id": rid, "source": record.get("source") or record.get("source_metadata", {}).get("source"),
                       "form": record.get("form", "unknown"), "fields": observed})
        for node in graph["nodes"]:
            totals["kind:" + node["kind"]] += 1
            totals["normalizer:" + node["normalized"]["resolution"]] += 1
            totals["binding:" + node["binding"]] += 1
            if "e05_binding" in node:
                totals["e05_binding:" + node["e05_binding"]] += 1
            if node["normalized"].get("reason"):
                totals["reason:" + node["normalized"]["reason"]] += 1
    report = {"version": VERSION, "records": len(rows), "candidate_diagnostics": dict(totals),
              "field_accuracy": None, "semantic_rules_approved": False, "release_approved": False,
              "source": str(source.resolve()), "source_sha256": fingerprint,
              "contract": contract, "catalog_hash": catalog["hash"], "normalizer": backend,
              "notes": ["候选召回、规则关联和解析成功均不是语义准确率",
                        "全文细引用只供隔离审计，不进入教师事实输入",
                        "新归一化旁路保留精度与开闭端点，未覆盖引擎现有字段"]}
    if (hashlib.sha256(source.read_bytes()).hexdigest() != fingerprint or contract_snapshot(engine) != contract):
        raise RuntimeError("source_or_contract_changed_during_diagnosis")
    out.mkdir(parents=True, exist_ok=False)
    for name, payload in (("candidate-graphs.jsonl", rows), ("field-diagnostics.jsonl", fields)):
        for row in payload:
            append(out / name, row)
    for name, payload in (("field-catalog.json", catalog), ("observability.json", summarize(fields, catalog))):
        (out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    report["artifact_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir())}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main():
    __import__("sys").stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if not args.out.resolve().is_relative_to((data_root() / "parsed2").resolve()):
        p.error("diagnostics 只写新的 $DATA/parsed2 子目录")
    report = diagnose_batch(args.input, args.out)
    print(json.dumps({k: report[k] for k in ("version", "records", "candidate_diagnostics", "field_accuracy")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
