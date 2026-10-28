"""工单 C：两省剩余未标注记录的人工要素标注（封存检验集，Q-21 / C-44 后的独立检验用）。

  python build_workorder_c.py check   # 只核对：用同一方法重建工单 B 的 inputs，逐条一致才继续
  python build_workorder_c.py build   # 生成 RUN 目录（inputs、assignments、check.py、manifest）

选样只看事实段、当事人段、省份与日期，不看处罚结果：
- 来源：v5 冻结包 train + 四个验证集（不含 excluded）；省份为河北、江苏；
- 排除：已标注（331、工单 B 101、银标）、test40 同事件、与已标注记录同事件；无 S1 记录或无当事人写法；
- 日期：能确定行为日期，且在该省基准施行后、2026 年前决定（否则不在引擎范围，标了也用不上）；
- 同一事件在同一批；批内约 25 条。
"""
from __future__ import annotations

import ast
import hashlib
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402

R = pc.ROOT
V5 = R / "engine/training/m4-facts-silver-p9-v5-frozen-20261027"
SOURCES = ["train.jsonl", "old168.jsonl", "lake706_valid70.jsonl", "p3p7_valid119.jsonl", "p9_valid.jsonl"]
RUN = R / "s1_runs/manual-batches-20261028-workorder-c"
SEED, BATCH = 20261028, 25


def jl(p):
    return [json.loads(line) for line in open(p, encoding="utf-8")]


def _inp(r):
    x = r["input"]
    return x if isinstance(x, dict) else ast.literal_eval(x)


def s1_index():
    out = {}
    for f in pc.S1_FILES:
        for x in jl(R / f):
            out[x["id"]] = x
    return out


def make_input(rid, facts_text, s1):
    meta = s1["authority"] + ("\n" + s1["text_party"] if s1.get("text_party") else "")
    return {"id": rid, "target": s1["subject_mention"], "aliases": [], "facts_text": facts_text, "meta_text": meta}


def check():
    s1 = s1_index()
    rows = {r["id"]: r for f in SOURCES for r in jl(V5 / f)}
    b = jl(pc.TEST_RUN / "inputs.jsonl")
    bad = [x["id"] for x in b if make_input(x["id"], _inp(rows[x["id"]])["facts_text"], s1[x["id"]]) != x]
    print(f"工单 B 重建：{len(b) - len(bad)}/{len(b)} 一致", bad[:5])
    return not bad


def build():
    s1, ctx = s1_index(), {r["id"]: r for r in jl(pc.CTX)}
    used = {r["id"] for run in (pc.DEV_RUN, pc.TEST_RUN) for r in jl(run / "inputs.jsonl")}
    silver = jl(pc.SILVER)
    used |= {r["id"] for r in silver}
    test_events = {r["metadata"].get("event_id") for r in silver if r["metadata"].get("split") == "test"}
    all_rows = [(f, r) for f in SOURCES for r in jl(V5 / f)]
    used_events = {r["event_id"] for _, r in all_rows if r["id"] in used}
    audit, picked = Counter(), []
    for f, r in all_rows:
        x = s1.get(r["id"])
        c = ctx.get(r["id"], {})
        prov = pc.province(c.get("province_code"), c.get("authority_id") or (x or {}).get("authority"))
        if prov not in pc.START:
            continue
        facts = _inp(r).get("facts_text", "")
        bd, dd = pc.dates((x or {}).get("behavior_date"), c.get("decision_date") or (x or {}).get("decision_date"), facts)
        reason = ("used" if r["id"] in used else "test40_event" if r["event_id"] in test_events else
                  "same_event_as_used" if r["event_id"] in used_events else
                  "no_s1_or_target" if not x or not x.get("subject_mention") else
                  "no_date" if bd is None or dd is None else
                  "out_of_period" if bd < pc.START[prov] or dd >= date(2026, 1, 1) else "ok")
        audit[f"{prov}:{reason}"] += 1
        if reason == "ok":
            picked.append({"source": f, "province": prov, "event_id": r["event_id"], **make_input(r["id"], facts, x)})
    events = defaultdict(list)
    for p in picked:
        events[p["event_id"]].append(p)
    keys = sorted(events)
    random.Random(SEED).shuffle(keys)
    batches, cur = [], []
    for k in keys:
        if cur and len(cur) + len(events[k]) > BATCH:
            batches.append(cur)
            cur = []
        cur += events[k]
    if cur:
        batches.append(cur)
    RUN.mkdir(parents=True, exist_ok=False)
    (RUN / "assignments").mkdir()
    inputs = [{k: p[k] for k in ("id", "target", "aliases", "facts_text", "meta_text")} for b in batches for p in b]
    (RUN / "inputs.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in inputs), "utf-8")
    for i, b in enumerate(batches):
        (RUN / "assignments" / f"assign-{i:02d}.json").write_text(json.dumps([p["id"] for p in b], ensure_ascii=False), "utf-8")
        (RUN / f"batch-{i:02d}").mkdir()
    shutil.copy(pc.TEST_RUN / "check.py", RUN / "check.py")
    manifest = {
        "created": date.today().isoformat(), "purpose": "封存检验集（Q-21 / C-44 后的独立检验）；发单会话在预注册前不读标签",
        "selection": __doc__, "seed": SEED, "audit": dict(sorted(audit.items())),
        "n": len(inputs), "events": len(keys), "batches": [
            {"batch": f"{i:02d}", "n": len(b), "provinces": dict(Counter(p["province"] for p in b)),
             "chars": sum(len(p["facts_text"]) + len(p["meta_text"]) for p in b)} for i, b in enumerate(batches)],
        "by_source": dict(Counter(p["source"] for p in picked)), "by_province": dict(Counter(p["province"] for p in picked)),
        "inputs_sha256": hashlib.sha256((RUN / "inputs.jsonl").read_bytes()).hexdigest(),
        "check_py_sha256": hashlib.sha256((RUN / "check.py").read_bytes()).hexdigest(),
    }
    (RUN / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: manifest[k] for k in ("n", "events", "by_source", "by_province", "audit")}, ensure_ascii=False, indent=1))
    for b in manifest["batches"]:
        print(b)


if __name__ == "__main__":
    if check() and sys.argv[1:] == ["build"]:
        build()
