"""Audit QA findings against source chunks; export no source text.

Usage: python aggregate_qa.py <qa-root> <output-dir>
Exit 0 only if coverage is attested, all findings are valid, and no error remains.
"""
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

CODE = re.compile(r"[A-Za-z0-9_.:-]+\Z")
FINDING = re.compile(r"findings-(\d{2})([a-z]?)\.jsonl\Z")
LEVELS = {"pass", "info", "warn", "error"}


def lines(path):
    for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            yield n, line


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, fields, records):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    root, out = map(Path, argv[1:])
    manifest_path = root / "input/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes = {"manifest.json": sha(manifest_path)}
    chunks, texts, input_errors, input_ids = {}, {}, [], []
    for spec in manifest["chunks"]:
        path = root / "input" / spec["chunk"]
        hashes[spec["chunk"]] = sha(path)
        ids = []
        for n, line in lines(path):
            try:
                record = json.loads(line)
                rid = record["id"]
                if not isinstance(rid, str) or not CODE.fullmatch(rid):
                    raise ValueError
                ids.append(rid)
                texts[rid] = record.get("text_full") or ""
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                input_errors.append({"file": path.name, "line": n, "reason": "invalid_input"})
        if len(ids) != spec["n"] or len(ids) != len(set(ids)):
            input_errors.append({"file": path.name, "line": 0, "reason": "count_or_duplicate"})
        chunks[path.stem[-2:]] = set(ids)
        input_ids.extend(ids)
    if len(input_ids) != manifest["n_total"] or len(set(input_ids)) != len(input_ids):
        input_errors.append({"file": "manifest.json", "line": 0, "reason": "total_or_duplicate"})

    accepted, rejected, finding_ids, coverage = [], [], set(), set()
    for path in sorted((root / "findings").glob("findings-*.jsonl")):
        hashes[path.name] = sha(path)
        match = FINDING.fullmatch(path.name)
        expected = chunks.get(match.group(1), set()) if match else set()
        for n, line in lines(path):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                # Salvage only the three safe metadata fields. The original
                # malformed row remains rejected until its payload is redone.
                values = {}
                for key in ("id", "check", "level"):
                    token = re.search(r'"' + key + r'"\s*:\s*"([A-Za-z0-9_.:-]+)"', line)
                    values[key] = token.group(1) if token else None
                if (values["id"] in expected and values["level"] in LEVELS
                        and values["check"] and CODE.fullmatch(values["check"])):
                    accepted.append({"id": values["id"], "check": values["check"],
                                     "level": values["level"], "file": path.name,
                                     "line": n, "repair": "metadata_only"})
                    finding_ids.add(values["id"])
                rejected.append({"file": path.name, "line": n, "id": values["id"] or "",
                                 "reason": "invalid_json_payload"})
                continue
            if not isinstance(item, dict):
                rejected.append({"file": path.name, "line": n, "id": "", "reason": "invalid_shape"})
                continue
            rid, check, level = item.get("id"), item.get("check"), item.get("level")
            if not isinstance(rid, str) or not CODE.fullmatch(rid):
                rejected.append({"file": path.name, "line": n, "id": "", "reason": "invalid_id"})
                continue
            repair = "none"
            if rid not in expected:
                evidence = item.get("evidence")
                candidates = [i for i in expected if isinstance(evidence, str)
                              and len(evidence.strip()) >= 12 and evidence.strip() in texts[i]]
                if len(candidates) == 1:
                    rid, repair = candidates[0], "unique_evidence"
                else:
                    rejected.append({"file": path.name, "line": n, "id": rid, "reason": "id_outside_chunk"})
                    continue
            if not isinstance(check, str) or not CODE.fullmatch(check) or level not in LEVELS:
                rejected.append({"file": path.name, "line": n, "id": rid, "reason": "invalid_check_or_level"})
                continue
            accepted.append({"id": rid, "check": check, "level": level, "file": path.name,
                             "line": n, "repair": repair})
            finding_ids.add(rid)

    coverage_path = root / "findings/coverage.jsonl"
    if coverage_path.exists():
        hashes[coverage_path.name] = sha(coverage_path)
        for n, line in lines(coverage_path):
            try:
                entry = json.loads(line)
                rid = entry["id"]
                expected_hash = hashlib.sha256(texts[rid].encode("utf-8")).hexdigest() if rid in texts else None
                if (expected_hash is None or entry.get("reviewed") is not True
                        or entry.get("checks_complete") is not True
                        or entry.get("text_sha256") != expected_hash):
                    raise ValueError
                coverage.add(rid)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                rejected.append({"file": coverage_path.name, "line": n, "id": "", "reason": "invalid_coverage"})
    missing = sorted(set(input_ids) - coverage)
    levels = Counter(x["level"] for x in accepted)
    valid = not input_errors and not rejected and not missing
    report = {
        "source_sha256": hashes, "n_expected": manifest["n_total"],
        "n_input_ids": len(set(input_ids)), "n_ids_with_findings": len(finding_ids),
        "n_coverage_attested": len(coverage), "missing_coverage_ids": missing,
        "n_accepted_findings": len(accepted), "n_rejected_findings": len(rejected),
        "n_id_repairs": sum(x["repair"] == "unique_evidence" for x in accepted),
        "n_metadata_salvaged": sum(x["repair"] == "metadata_only" for x in accepted),
        "levels": dict(levels), "input_errors": input_errors,
        "aggregation_valid": valid, "gate_pass": valid and levels["error"] == 0,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out / "accepted_findings.csv", ["id", "check", "level", "file", "line", "repair"], accepted)
    write_csv(out / "rejected_findings.csv", ["file", "line", "id", "reason"], rejected)
    write_csv(out / "recheck_ids.csv", ["id", "reason"],
              [{"id": rid, "reason": "coverage_unattested"} for rid in missing])
    returns = [
        {"id": rid, "category": "coverage_unattested", "version": "r1-content-qa-input",
         "text_sha256": hashlib.sha256(texts[rid].encode("utf-8")).hexdigest(),
         "closure": "complete_review_attestation_same_hash"}
        for rid in missing
    ]
    for item in accepted:
        if item["level"] == "pass":
            continue
        returns.append({
            "id": item["id"], "category": item["check"], "version": "r1-content-qa-input",
            "text_sha256": hashlib.sha256(texts[item["id"]].encode("utf-8")).hexdigest(),
            "closure": "reissue_valid_json_same_hash" if item["repair"] == "metadata_only"
                       else "review_and_close_finding_same_hash",
        })
    write_csv(out / "return_list.csv", ["id", "category", "version", "text_sha256", "closure"],
              sorted(returns, key=lambda item: (item["id"], item["category"])))
    (out / "qa_report.md").write_text(
        "# 内容抽检聚合校验\n\n"
        f"- 输入 ID：{len(set(input_ids))}/{manifest['n_total']}\n"
        f"- 有 findings 的 ID：{len(finding_ids)}；逐件覆盖证明：{len(coverage)}/{manifest['n_total']}\n"
        f"- 接受 {len(accepted)} 条元数据；隔离 {len(rejected)} 条原始行；唯一证据匹配修复 ID {report['n_id_repairs']} 条，非法 JSON 提取元数据 {report['n_metadata_salvaged']} 条\n"
        f"- error {levels['error']} / warn {levels['warn']} / info {levels['info']}\n"
        f"- 聚合有效：{'是' if valid else '否'}；门禁：{'通过' if report['gate_pass'] else '不通过'}\n"
        "- 隔离行与待复检 ID 见同目录 CSV；输出不含正文或证据。\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "n_input_ids", "n_ids_with_findings", "n_coverage_attested",
        "n_accepted_findings", "n_rejected_findings", "n_id_repairs", "n_metadata_salvaged",
        "aggregation_valid", "gate_pass")}, ensure_ascii=False))
    return 0 if report["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
