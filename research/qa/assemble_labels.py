"""试标交付装配（金标质检线）：把代理试标产物装配进 labels/ 目录规范布局。

用法：python assemble_labels.py <trial-annotation-20261016 目录> <labels 输出目录> <交付版本名>
布局（data-program-500-gold.md §3 L5 行）：
  labels/schema-1.0.0/<版本>/annotator_A.jsonl      标注员 A 原标（分片拼接）
  labels/schema-1.0.0/<版本>/annotator_B.jsonl      标注员 B 原标
  labels/schema-1.0.0/<版本>/arbitrated.jsonl       仲裁后标签（proxy，不计金标）
  labels/schema-1.0.0/<版本>/arbitration_log.csv
  labels/schema-1.0.0/<版本>/agreement_report.{json,md}、disagreements.csv、arbitration_stats.json
  labels/schema-1.0.0/<版本>/SHA256SUMS
  labels/schema-1.0.0/<版本>/README.md（元数据：标注者、协议版本、输入哈希、偏离声明）
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

BASE = Path(r"D:\02_Dev\Data\justilaw-research")
PILOT = BASE / "admin" / "pilot50.jsonl"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def concat_jsonl(src_dir: Path, dst: Path) -> dict:
    recs: dict[str, dict] = {}
    for fp in sorted(src_dir.glob("chunk-*.jsonl")):
        for line in fp.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["id"] in recs:
                    raise SystemExit(f"重复 id {r['id']} 于 {fp}")
                recs[r["id"]] = r
    with dst.open("w", encoding="utf-8", newline="\n") as f:
        for r in recs.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    valued = sum(1 for r in recs.values() for j in r["fields"].values() if j.get("status") not in (None, "未提及"))
    return {"n_records": len(recs), "n_valued_fields": valued,
            "valued_by_record": round(valued / max(len(recs), 1), 1)}


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    trial, labels_root, version = Path(argv[1]), Path(argv[2]), argv[3]
    out = labels_root / "schema-1.0.0" / version
    out.mkdir(parents=True, exist_ok=True)

    stats_a = concat_jsonl(trial / "annotations" / "A", out / "annotator_A.jsonl")
    stats_b = concat_jsonl(trial / "annotations" / "B", out / "annotator_B.jsonl")

    copied = []
    for rel in ("arbitration/arbitrated.jsonl", "arbitration/arbitration_log.csv",
                "arbitration/arbitration_stats.json", "agreement/agreement_report.json",
                "agreement/agreement_report.md", "agreement/disagreements.csv"):
        src = trial / rel
        if src.exists():
            dst = out / Path(rel).name
            dst.write_bytes(src.read_bytes())
            copied.append(str(rel))

    # 协议版本与输入哈希
    protocol = trial / "protocol.md"
    gate = None
    agr = trial / "agreement" / "agreement_report.json"
    if agr.exists():
        gate = json.loads(agr.read_text(encoding="utf-8")).get("gate_G0_3")

    readme = [
        "# pilot50 代理试标标签（proxy，不计金标）", "",
        f"- 交付版本：{version}；装配日期：{date.today().isoformat()}",
        "- 性质：**代理试标**——G0.3 原要求法律组双人试标，真人缺位（用户 2026-10-16 决定），",
        "  由两个异构法律大模型子代理独立标注、第三模型逐条仲裁产生。**不作为金标计数，不进训练/测试集**。",
        "- 标注员 A：GLM-5.3（account:bigmodel-individual-coding-plan，max）；10 分片独立上下文",
        "- 标注员 B：DeepSeek-Flash（deepseek/deepseek-flash，max）；10 分片独立上下文",
        "- 仲裁：GLM-5.3-Flash（共享上下文逐条裁决）；法条核验：北大法宝 MCP（会话内，另行记账）",
        f"- 标注协议：qa/trial-annotation-20261016/protocol.md v1.1（sha256 {sha256(protocol)[:16]}…；含冒烟共识澄清 11 条）",
        f"- 输入：admin/pilot50.jsonl（sha256 {sha256(PILOT)[:16]}…，50 件 / 50 事件）",
        f"- A 原标：{stats_a['n_records']} 件，有值字段 {stats_a['n_valued_fields']}（均 {stats_a['valued_by_record']}/件）",
        f"- B 原标：{stats_b['n_records']} 件，有值字段 {stats_b['n_valued_fields']}（均 {stats_b['valued_by_record']}/件）",
        f"- 一致性门禁（代理口径）：{json.dumps(gate, ensure_ascii=False) if gate else '见 agreement_report.json'}",
        f"- 装配清单：{copied}",
        "- 产物升格条件：法律组真人复标或抽样复核后方可计入金标；正文哈希（text_sha256）变化时整体作废重标。",
    ]
    (out / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    with (out / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as f:
        for fp in sorted(out.iterdir()):
            if fp.is_file() and fp.name != "SHA256SUMS":
                f.write(f"{sha256(fp)}  {fp.name}\n")
    print(json.dumps({"out": str(out), "A": stats_a, "B": stats_b, "copied": len(copied)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
