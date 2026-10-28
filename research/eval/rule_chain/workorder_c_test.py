"""工单 C 一次性检验（连续任务 P4–P5）。预注册：$DATA/engine/development/workorder-c-test-20261029/PREREG.md

  python workorder_c_test.py prep   # 不读标签：核对快照、输入条数、模型文件
  python workorder_c_test.py run    # 预注册提交后只跑一次

H1 规则修正：修正版（当前规则：累计赌资 + P1 补编）vs 现行版（提交 8f44e80 的规则快照）
H2 实务参照：rap-ruleonly-v2（主候选）、rap-ruled-v2（全量）、rap-notext-v1（线上现行，配现行规则）、边际分布
H3 Q-27 第二阶段：within_band_elements 按第一阶段口径（规则为 3470df1 = 8f44e80 快照），616 单元训练，工单 C 检验
"""
from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402
from app.discretion import practice  # noqa: E402
from app.discretion.decide import band_types  # noqa: E402
from app.discretion.norm_layer import Facts, assess  # noqa: E402
from app.discretion.norm_store import load as load_lib  # noqa: E402
from app.discretion.schema import GamblingElements  # noqa: E402

RUN_C = pc.ROOT / "s1_runs/manual-batches-20261028-workorder-c"
V5 = pc.ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027"
V5_FILES = ["train.jsonl", "old168.jsonl", "lake706_valid70.jsonl", "p3p7_valid119.jsonl", "p9_valid.jsonl"]
SNAP = Path("C:/Users/17728/AppData/Local/Temp/claude/D--02-Dev-Projects---/ef3804f2-81e8-516f-9a79-1efaaceb20af"
            "/scratchpad/snap-8f44e80/justilaw-api/app/discretion/norms")
OUT = pc.ROOT / "engine/development/workorder-c-test-20261029"
DATA = Path(practice.__file__).parent / "data"
ORDER = practice.ORDER
SEED, MIN_N = 20261029, 40


def libs():
    return load_lib.__wrapped__(SNAP), load_lib.__wrapped__()        # 现行版（快照）、修正版（当前）


def load_c():
    """读工单 C 的标签（只在 run 中调用）。口径与 prob_chain.load_cases 相同。"""
    rows = {r["id"]: r for f in V5_FILES for r in pc.jl(V5 / f)}
    ctx = {r["id"]: r for r in pc.jl(pc.CTX)}
    s1 = {}
    for f in pc.S1_FILES:
        for x in pc.jl(pc.ROOT / f):
            s1[x["id"]] = x
    check, got = pc.load_check(RUN_C), pc.batch_rows(RUN_C)
    audit, cases = Counter(), []
    for rec in pc.jl(RUN_C / "inputs.jsonl"):
        rid = rec["id"]
        if rid not in got or check.errors_of(rec, got[rid]):
            audit["missing_or_check_fail"] += 1
            continue
        c, x, r = ctx.get(rid, {}), s1.get(rid, {}), rows[rid]
        tgt = r["target"] if isinstance(r["target"], dict) else ast.literal_eval(r["target"])
        prov = pc.province(c.get("province_code"), c.get("authority_id") or x.get("authority"))
        bd, dd = pc.dates(x.get("behavior_date"), c.get("decision_date") or x.get("decision_date"), rec["facts_text"])
        case = {"id": rid, "event_id": r["event_id"], "province": prov, "historical": pc.norm_type(tgt["type"]),
                "target_amounts": tgt, "agency": (r["event_id"] or "").split("|")[0], "dd": dd, "facts": None}
        if prov not in pc.START or bd is None or bd < pc.START[prov] or dd is None or dd >= date(2026, 1, 1):
            case["scope"] = "out_of_period"
        else:
            el = GamblingElements.model_validate({"meta": {"region": prov, "behavior_date": bd, "decision_date": dd},
                                                  **got[rid]["reference_elements"]})
            case["facts"] = Facts.from_elements(el)
            case["scope"] = "in_scope" if case["facts"].behavior_type in ("参与赌博", "为赌博提供条件") else "other_behavior"
        audit[case["scope"]] += 1
        cases.append(case)
    return cases, audit


def route(types):
    return "single" if len(types) == 1 else "candidates" if types else "none"


def h1(cases, lib_old, lib_new):
    out, changed = {}, 0
    for name, lib in (("现行版", lib_old), ("修正版", lib_new)):
        rows = [(route(t := band_types(assess(c["facts"], lib).stake_threshold)), t, c["historical"]) for c in cases]
        n = len(rows)
        single = [r for r in rows if r[0] == "single"]
        cand = [r for r in rows if r[0] == "candidates"]
        out[name] = {"n": n, "single_share": round(len(single) / n, 3),
                     "single_acc": round(sum(t[0] == y for _, t, y in single) / len(single), 3) if single else None,
                     "candidates_share": round(len(cand) / n, 3),
                     "candidates_coverage": round(sum(y in t for _, t, y in cand) / len(cand), 3) if cand else None,
                     "none_share": round(sum(r[0] == "none" for r in rows) / n, 3)}
    for c in cases:
        if band_types(assess(c["facts"], lib_old).stake_threshold) != band_types(assess(c["facts"], lib_new).stake_threshold):
            changed += 1
    o, nw = out["现行版"], out["修正版"]
    ok = (nw["single_share"] >= o["single_share"]
          and (o["single_acc"] is None or nw["single_acc"] is None or nw["single_acc"] >= o["single_acc"] - 0.05)
          and (o["candidates_coverage"] is None or nw["candidates_coverage"] is None
               or nw["candidates_coverage"] >= o["candidates_coverage"]))
    out["records_changed"] = changed
    out["verdict"] = "修正版非劣" if ok else "修正版未达非劣"
    return out


def h2(cases, lib_old, lib_new):
    models = {"ruleonly_v2": (practice.load_model(str(DATA / "rap-ruleonly-v2.json")), lib_new),
              "ruled_v2": (practice.load_model(str(DATA / "rap-ruled-v2.json")), lib_new),
              "notext_v1": (practice.load_model(str(DATA / "rap-notext-v1.json")), lib_old)}
    lc = models["ruleonly_v2"][0]["training"]["label_counts"]
    tot = sum(lc.values()) + 0.5 * len(ORDER)
    marginal = {t: (lc.get(t, 0) + 0.5) / tot for t in ORDER}
    recs = []
    for c in cases:
        r = {"event": c["event_id"], "y": c["historical"], "marginal": marginal}
        for name, (m, lib) in models.items():
            types = band_types(assess(c["facts"], lib).stake_threshold)
            out = practice.predict(c["facts"], types, c["province"], m)   # v2 的规则特征读当前规则（= lib_new）
            r[name] = out["distribution"] if out else marginal
        recs.append(r)
    names = ["ruleonly_v2", "ruled_v2", "notext_v1", "marginal"]
    res = {"n": len(recs)}
    for nm in names:
        pred = [max(r[nm], key=r[nm].get) for r in recs]
        recall = {t: round(sum(p == t for p, r in zip(pred, recs) if r["y"] == t) / max(1, sum(r["y"] == t for r in recs)), 3)
                  for t in ORDER if any(r["y"] == t for r in recs)}
        res[nm] = {"rps": round(float(np.mean([pc.rps(r[nm], r["y"]) for r in recs])), 4),
                   "acc": round(float(np.mean([p == r["y"] for p, r in zip(pred, recs)])), 3), "recall": recall}
    events = sorted({r["event"] for r in recs})
    idx = {e: [i for i, r in enumerate(recs) if r["event"] == e] for e in events}
    rng = np.random.default_rng(SEED)
    for a, b in (("ruleonly_v2", "notext_v1"), ("ruleonly_v2", "marginal"), ("ruled_v2", "notext_v1")):
        d = np.array([pc.rps(r[a], r["y"]) - pc.rps(r[b], r["y"]) for r in recs])
        boots = [d[[i for g in rng.integers(0, len(events), len(events)) for i in idx[events[g]]]].mean()
                 for _ in range(2000)]
        res[f"{a}-{b}"] = {"diff": round(float(d.mean()), 4),
                           "ci95": [round(float(q), 4) for q in np.quantile(boots, [0.025, 0.975])]}
    res["switch_online_to_ruleonly_v2"] = res["ruleonly_v2-notext_v1"]["ci95"][1] < 0.02
    res["practice_reference_effective"] = res["ruleonly_v2-marginal"]["ci95"][1] < 0
    return res


def h3(cases, lib_old):
    import within_band_elements as wbe
    pc.LIB = lib_old                                      # 与第一阶段同一规则版本（3470df1 = 8f44e80）
    train_rows = wbe.units(wbe.load())
    test_rows = wbe.units(cases)
    recs = []
    for comp, rows in test_rows.items():
        tr = train_rows[comp]
        if not rows or not tr:
            continue
        kind, field = comp
        anc = wbe.anchors(kind, field)
        Xtr = np.array([wbe.features(r["case"]) for r in tr])
        ytr = np.array([r["y"] for r in tr])
        Xte = np.array([wbe.features(r["case"]) for r in rows])
        preds = {m: wbe.fit_predict(m, Xtr, ytr, Xte, len(anc)) for m in ("M0b", "M1", "M3")}
        for j, r in enumerate(rows):
            c, y = r["case"], r["y"]
            ps = {"M0": wbe.smooth(wbe.engine_dist(c, kind, field, anc)), **{m: wbe.smooth(preds[m][j]) for m in preds}}
            recs.append({"component": f"{kind}:{field}", "agency": c["agency"], "y": y,
                         **{f"rps_{m}": wbe.rps(p, y) for m, p in ps.items()},
                         **{f"ll_{m}": float(-np.log(p[y])) for m, p in ps.items()},
                         **{f"hit_{m}": int(np.argmax(p) == y) for m, p in ps.items()}})
    if not recs:
        return {"n": 0}
    s = wbe.summarize(recs)
    d = s["M1-M0b"]
    s["verdict_stage2"] = ("通过" if d["ci95"][1] < 0 and s["M1"]["rps"] <= s["M0"]["rps"] else "未通过")
    s["units"] = dict(Counter(r["component"] for r in recs))
    return s


def main():
    mode = sys.argv[1]
    lib_old, lib_new = libs()
    if mode == "prep":
        print("快照省份:", sorted(lib_old.provinces), "修正版省份:", sorted(lib_new.provinces))
        print("工单 C 输入条数:", len(pc.jl(RUN_C / "inputs.jsonl")))
        for n in ("rap-ruleonly-v2.json", "rap-ruled-v2.json", "rap-notext-v1.json"):
            m = practice.load_model(str(DATA / n))
            print(n, m["version"], "stale" if m.get("stale") else "ok")
        return
    if mode != "run":
        raise SystemExit("prep | run")
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "report.json").exists():
        raise SystemExit("已运行过一次（report.json 存在），按预注册不得重跑")
    cases, audit = load_c()
    ins = [c for c in cases if c["scope"] == "in_scope"]
    rep = {"audit": dict(audit), "n_in_scope": len(ins), "provinces": dict(Counter(c["province"] for c in ins)),
           "labels": dict(Counter(c["historical"] for c in ins))}
    rep["descriptive_only"] = len(ins) < MIN_N
    rep["H1"] = h1(ins, lib_old, lib_new)
    rep["H2"] = h2(ins, lib_old, lib_new)
    rep["H3"] = h3(ins, lib_old)
    if rep["descriptive_only"]:
        rep["note"] = f"范围内 {len(ins)} 条 < {MIN_N}，按预注册只作描述，不作判定"
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
