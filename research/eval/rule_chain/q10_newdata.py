"""Q-10：D-005 两处事后修订在新数据（工单 B）上的检验（预注册
$DATA/engine/development/q10-newdata-20261028/PREREG.md，sha256 前缀 95c56a63cbb0671e，v1.1 修订 ① 判据，见预注册修订记录）。

① 河北升档 + 赌资不明：v2（候选{不予, 第三档}，候选内文本挑）vs literal（直接第三档）。
② 江苏 gambling_form：有/无该字段时的规则唯一覆盖率与唯一子集准确率。
附带：唯一子集规则 vs 文本（C-01 复现）；整体引擎第一版 vs 纯文本。
工单 B 全部校验通过后只运行一次：python q10_newdata.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prob_chain as pc  # noqa: E402

OUT = pc.ROOT / "engine/development/q10-newdata-20261028"
SEED = 20261028
UPGRADE_UNKNOWN = "明确情节升档、赌资门槛未知"


def boot_diff(a, b, events, draws=2000):
    if not len(a):
        return None
    groups = {}
    for i, e in enumerate(events):
        groups.setdefault(e, []).append(i)
    units = list(groups.values())
    rng = np.random.default_rng(SEED)
    d = []
    for _ in range(draws):
        s = [i for j in rng.integers(0, len(units), len(units)) for i in units[j]]
        d.append(a[s].mean() - b[s].mean())
    return [round(float(x), 3) for x in np.quantile(d, [0.025, 0.975])]


def route(types, proba):
    if len(types) == 1:
        return types[0], "rule_single"
    if types:
        return max(types, key=lambda k: proba.get(k, 0.0)), "rule_candidates"
    return max(proba, key=proba.get), "model_fallback"


def acc(rows, key):
    return round(float(np.mean([r[key] == r["truth"] for r in rows])), 3) if rows else None


def main():
    train = pc.jl(pc.TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, _ = pc.load_cases("dev", by_id)
    test, audit = pc.load_cases("test", by_id)
    dev_events = {c["event_id"] for c in dev}
    audit["shares_event_with_dev"] = sum(c["event_id"] in dev_events for c in test)
    cases = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in dev_events]
    predict, n_train = pc.text_model(train, dev + test)
    probas = predict([c["facts_text"] for c in cases]) if cases else []
    rows = []
    for c, proba in zip(cases, probas):
        st = pc.assess(c["facts"], pc.LIB).stake_threshold
        types = pc.band_types(st)
        pred, how = route(types, proba)
        row = {"id": c["id"], "event": c["event_id"], "province": c["province"], "truth": c["historical"],
               "text": max(proba, key=proba.get), "engine": pred, "route": how, "types": types,
               "status": st.get("status")}
        if c["province"] == "130000" and c["facts"].behavior_type == "参与赌博" and st.get("status") == UPGRADE_UNKNOWN:
            row["s1"] = True
            row["literal"] = next((t for t in types if t != "不予处罚"), pred)
            row["truth_in_v2_set"] = c["historical"] in types
        if c["province"] == "320000":
            st0 = pc.assess(pc.with_(c["facts"], gambling_form=None), pc.LIB).stake_threshold
            t0 = pc.band_types(st0)
            row["types_no_form"] = t0
            row["engine_no_form"] = route(t0, proba)[0]
        rows.append(row)

    def unique_block(sel):
        u = [r for r in sel if r["route"] == "rule_single"]
        a = np.array([r["engine"] == r["truth"] for r in u], float)
        b = np.array([r["text"] == r["truth"] for r in u], float)
        return {"n": len(sel), "unique": len(u), "rule_acc": acc(u, "engine"), "text_acc": acc(u, "text"),
                "rule_minus_text_ci95": boot_diff(a, b, [r["event"] for r in u]),
                "engine_acc_all": acc(sel, "engine"), "text_acc_all": acc(sel, "text")}

    s1 = [r for r in rows if r.get("s1")]
    js = [r for r in rows if r["province"] == "320000"]
    js_u0 = [r for r in js if len(r["types_no_form"]) == 1]
    report = {
        "prereg_sha256_prefix": "95c56a63cbb0671e", "audit": dict(audit), "text_train_rows": n_train,
        "q10_1_hebei_upgrade_unknown": {
            "n": len(s1), "truth": {t: sum(r["truth"] == t for r in s1) for t in pc.ORDER},
            "v2_acc": acc(s1, "engine"), "literal_acc": acc(s1, "literal"),
            "truth_in_v2_set": round(float(np.mean([r["truth_in_v2_set"] for r in s1])), 3) if s1 else None,
            "third_band_share": round(float(np.mean([r["truth"] == "拘留并处罚款" for r in s1])), 3) if s1 else None},
        "q10_2_jiangsu_form": {
            "n": len(js),
            "unique_with_form": sum(r["route"] == "rule_single" for r in js),
            "unique_without_form": len(js_u0),
            "coverage_gain": round((sum(r["route"] == "rule_single" for r in js) - len(js_u0)) / len(js), 3) if js else None,
            "with_form": unique_block(js),
            "engine_acc_all_without_form": acc(js, "engine_no_form")},
        "c01_replication": {"all": unique_block(rows),
                            "130000": unique_block([r for r in rows if r["province"] == "130000"]),
                            "320000": unique_block(js)},
    }
    v = {}
    q1 = report["q10_1_hebei_upgrade_unknown"]
    v["①"] = ("方向报告（S1 < 10）" if q1["n"] < 10 else
              "维持" if q1["third_band_share"] >= 0.5 else "赌资不明时升档不足以定第三档：ADR-003 候选集应纳入第一、二档种类")
    q2 = report["q10_2_jiangsu_form"]
    v["②"] = ("只描述（江苏 < 30）" if q2["n"] < 30 else
              "字段有效" if (q2["coverage_gain"] >= 0.10 and q2["with_form"]["unique"] >= 10
                             and q2["with_form"]["rule_acc"] >= q2["with_form"]["text_acc"]) else "未达判据")
    c = report["c01_replication"]["all"]
    v["附带"] = ("只描述（唯一子集 < 20）" if c["unique"] < 20 else
               "C-01 复现" if c["rule_minus_text_ci95"][0] > 0 else "C-01 未复现")
    report["verdict"] = v
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "rows.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
