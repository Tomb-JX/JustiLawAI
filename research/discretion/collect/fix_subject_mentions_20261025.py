"""L2 离线修复（协调 2026-10-25 移交）：canonical 12 条句子片段式 subject_mention 截回姓名。

配合 pkulaw_ingest@0.4 的上游修法：本脚本只修数据侧历史值，**不动**已冻结的
S1 队列/审计快照（B-12 断路1，修复只向前——重跑漏斗时 prepare 脚本从 canonical 取新值）。

用法：
    python fix_subject_mentions_20261025.py           # dry-run，只打印将改动
    python fix_subject_mentions_20261025.py --apply   # 备份 .bak-20261025 后原位修补

修补对象（$JUSTILAW_DATA_DIR 下）：
    unified_raw_refresh/20261018-s1-repaired/records.jsonl   （引擎 --canonical 消费位）
    parsed/pkulaw/20261018-P2-r1/records.jsonl               （源批）
    parsed/pkulaw/20261018-P1b-r2/records.jsonl              （源批）
修复清单：ops/subject-mention-repair-20261025.jsonl（id/doc_no/old/new）
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from pkulaw_agent.session import data_dir  # noqa: F401  (与 download_l4 同源的 $DATA 解析)
from pkulaw_ingest import trim_person_name

TARGETS = (
    "unified_raw_refresh/20261018-s1-repaired/records.jsonl",
    "parsed/pkulaw/20261018-P2-r1/records.jsonl",
    "parsed/pkulaw/20261018-P1b-r2/records.jsonl",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    args = ap.parse_args()

    data = data_dir()
    repairs: dict[str, dict] = {}  # doc_no_hash -> {id, doc_no, old, new}

    for rel in TARGETS:
        p = data / rel
        if not p.exists():
            print(f"跳过（不存在）：{rel}")
            continue
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        changed = 0
        for r in rows:
            sm = r.get("subject_mention") or ""
            if len(sm) <= 6:
                continue
            fixed = trim_person_name(sm)
            if fixed == sm:
                continue
            changed += 1
            key = r.get("doc_no_hash") or r.get("id")
            rec = repairs.setdefault(key, {"id": r.get("id", ""), "doc_no": r.get("doc_no", ""),
                                           "old": sm, "new": fixed})
            print(f"  {rel.split('/')[0]:<24} {r.get('id','')[:10]:<12} {sm!r} -> {fixed!r}")
        if changed and args.apply:
            bak = p.with_suffix(".jsonl.bak-20261025")
            if not bak.exists():
                shutil.copy2(p, bak)
            out = []
            for r in rows:
                key = r.get("doc_no_hash") or r.get("id")
                sm = r.get("subject_mention") or ""
                if key in repairs and len(sm) > 6:
                    r["subject_mention"] = trim_person_name(sm)
                out.append(json.dumps(r, ensure_ascii=False))
            p.write_text("\n".join(out) + "\n", encoding="utf-8")
            print(f"  ✓ 已修补 {changed} 条 → {rel}（备份 {bak.name}）")
        elif changed:
            print(f"  [dry-run] {rel}：{changed} 条待修")

    man = data / "ops" / "subject-mention-repair-20261025.jsonl"
    print(f"\n共 {len(repairs)} 个唯一缺陷记录")
    if args.apply:
        man.parent.mkdir(parents=True, exist_ok=True)
        man.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in repairs.values()) + "\n",
                       encoding="utf-8")
        print(f"✓ 修复清单 → {man}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
