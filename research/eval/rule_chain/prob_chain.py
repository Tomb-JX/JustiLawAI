"""概率版规则链路 vs 引擎第一版（预注册 $DATA/engine/development/prob-chain-20261028/PREREG.md v1.1）。

缺失要素当潜变量：L1 江苏方式类别、L2 本人赌资。每个取值组合填入要素 → M2 → 处罚种类，按先验加权求和。
先验只用开发数据估计；只在"部分信息"记录（至少触发一个潜变量）上与第一版比较 RPS。

usage:
  python prob_chain.py dev   # 开发集留一事件交叉验证（开发参考，不进判据）
  python prob_chain.py test  # 检验集，只在代码冻结、工单 B 全部校验通过后运行一次
"""
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "justilaw-api"))
from app.discretion.decide import band_types, decide  # noqa: E402
from app.discretion.norm_layer import Facts, _flag, _measure_interval, assess  # noqa: E402
from app.discretion.norm_store import load  # noqa: E402
from app.discretion.schema import AmountRange, GamblingElements  # noqa: E402

ROOT = Path("D:/02_Dev/Data/justilaw-research")
RUNS = ROOT / "s1_runs"
DEV_RUN, TEST_RUN, FORM_RUN = (RUNS / "manual-batches-20261028-rulechain", RUNS / "manual-batches-20261028-probchain-test",
                               RUNS / "manual-batches-20261028-gamblingform")
TRAIN = ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl"
SILVER = ROOT / "parsed2/m4-pilot-203-silver-20261020/records.jsonl"
CTX = ROOT / "engine/development/m4-agency-prior-cv-v2-20261027/context.jsonl"
S1_FILES = ["unified_raw_refresh/20261018-s1-repaired/records.jsonl",
            "unified_raw_refresh/20261026-P3P7-additions/records.jsonl",
            "unified_raw_refresh/20261027-P9-additions/records.jsonl"]
OUT = ROOT / "engine/development/prob-chain-20261028"
START = {"130000": date(2021, 11, 17), "320000": date(2019, 2, 2)}
CITIES = {"130000": "河北 石家庄 保定 邯郸 邢台 沧州 衡水 廊坊 唐山 秦皇岛 张家口 承德 辛集 定州 雄安".split(),
          "320000": "江苏 南京 苏州 无锡 常州 南通 扬州 镇江 泰州 盐城 淮安 连云港 宿迁 徐州".split()}
ORDER = ["不予处罚", "罚款", "拘留", "拘留并处罚款"]          # RPS 的轻重顺序
CAT_FORM = {"cat1": "聚众赌博", "cat2": "其他"}               # 代表各类别的 gambling_form 取值
SMOOTH, MIN_VALUES = 5, 15
LIB = load()


def jl(p):
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def to_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def norm_type(t):
    return t if t in ORDER else "不予处罚"


def _lake_regions():
    lake = defaultdict(set)
    con = sqlite3.connect(str(ROOT / "lake/catalog/lake.db"))
    for a, rc in con.execute("select authority, region_code from documents where authority is not null and region_code is not null"):
        if re.fullmatch(r"\d{6}", rc or ""):
            lake[re.sub(r"\s+", "", a)].add(rc[:2] + "0000")
    con.close()
    return lake


LAKE = _lake_regions()


def province(code, authority):
    """同 eval_chain.province_of：元数据 → 湖表机关精确匹配（唯一省份）→ 机关名中的地名。"""
    if code in ("13", "32"):
        return code + "0000"
    if code in START:
        return code
    a = re.sub(r"\s+", "", authority or "")
    if a and len(LAKE.get(a, ())) == 1:
        return next(iter(LAKE[a]))
    return next((k for k, v in CITIES.items() if any(n in a for n in v)), None)


def dates(bd, dd, facts_text):
    """预注册日期规则：行为日期缺失取事实段第一个完整日期，再缺取决定日期；决定日期缺失取行为日期。"""
    b = to_date(bd)
    if b is None:
        m = re.search(r"(20\d\d)年(\d{1,2})月(\d{1,2})日", facts_text or "")
        if m:
            try:
                b = date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:
                b = None
    d = to_date(dd)
    return b or d, d or b


def load_check(run):
    spec = importlib.util.spec_from_file_location(f"check_{run.name}", run / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def batch_rows(run):
    got = {}
    for b in sorted(run.glob("batch-*")):
        for p in sorted(b.glob("*.jsonl"), key=lambda p: (p.name != "labels.jsonl", p.name)):
            for line in p.read_text("utf-8").splitlines():
                try:
                    row = json.loads(line)
                    got[row["id"]] = row
                except Exception:  # noqa: BLE001
                    pass
    return got


def load_cases(split, train_by_id):
    """split = dev（66 银标 + 331）或 test（工单 B）。只保留校验通过的标签。"""
    audit, cases = Counter(), []
    ctx = {r["id"]: r for r in jl(CTX)}
    if split == "dev":
        for r in jl(SILVER):
            m = r["metadata"]
            if m.get("split") == "test":
                continue                                    # test40：不读
            cases.append({"id": r["id"], "event_id": m.get("event_id"), "facts_text": r["input"]["facts_text"],
                          "province": province(m.get("province_code"), m.get("authority")),
                          "bd": m.get("behavior_date"), "dd": m.get("decision_date"),
                          "historical": norm_type(r["observed_outcome"]["type"]), "ref": r["reference_elements"]})
    runs = [DEV_RUN] if split == "dev" else [TEST_RUN]
    s1 = {}
    for f in S1_FILES:
        for x in jl(ROOT / f):
            s1[x["id"]] = x
    for run in runs:
        check, recs, got = load_check(run), {r["id"]: r for r in jl(run / "inputs.jsonl")}, batch_rows(run)
        for rid, rec in recs.items():
            if rid not in got:
                audit["missing"] += 1
                continue
            errs = check.errors_of(rec, got[rid])
            if run == DEV_RUN:                              # 331 条按 schema 1.1.0（36 字段）标注，缺新字段不算错
                errs = [e for e in errs if not e.startswith("conduct.gambling_form: missing")]
            if errs:
                audit["check_fail"] += 1
                continue
            c, t = ctx[rid], train_by_id[rid]
            cases.append({"id": rid, "event_id": t["event_id"], "facts_text": rec["facts_text"],
                          "province": province(c.get("province_code"), c.get("authority_id")),
                          "bd": s1.get(rid, {}).get("behavior_date"), "dd": c.get("decision_date"),
                          "historical": norm_type(t["target"]["type"]), "ref": got[rid]["reference_elements"]})
    forms = {k: v["gambling_form"] for k, v in batch_rows(FORM_RUN).items()}
    form_check = load_check(FORM_RUN)
    form_recs = {r["id"]: r for r in jl(FORM_RUN / "inputs.jsonl")}
    for c in cases:
        fm = forms.get(c["id"])
        if fm and c["id"] in form_recs and not form_check.errors_of(form_recs[c["id"]], {"gambling_form": fm}):
            c["ref"].setdefault("conduct", {})["gambling_form"] = fm
            audit["form_from_A"] += 1
        bd, dd = dates(c["bd"], c["dd"], c["facts_text"])
        c["bd"], c["dd"] = bd, dd
        c["facts"] = None
        if c["province"] not in START:
            c["scope"] = "outside"
        elif bd is None:
            c["scope"] = "no_date"
        elif bd < START[c["province"]] or dd >= date(2026, 1, 1):
            c["scope"] = "out_of_period"
        else:
            el = GamblingElements.model_validate({"meta": {"region": c["province"], "behavior_date": bd,
                                                           "decision_date": dd}, **c["ref"]})
            f = Facts.from_elements(el)
            c["facts"] = f
            c["scope"] = "in_scope" if f.behavior_type in ("参与赌博", "为赌博提供条件") else "other_behavior"
        audit[c["scope"]] += 1
    return cases, audit


# ---------- 规则推导 ----------

def types_of(f):
    return band_types(assess(f, LIB).stake_threshold)


def with_(f, **kw):
    g = Facts(**{k: getattr(f, k) for k in f.__dataclass_fields__})
    for k, v in kw.items():
        setattr(g, k, v)
    return g


def cat1_methods():
    return set(LIB.provinces["320000"]["rules"]["参与赌博"]["measures"][0]["categories"][0]["methods"])


CAT1_METHODS = cat1_methods()


def form_unknown(c):
    f = c["facts"]
    return (c["province"] == "320000" and f.behavior_type == "参与赌博"
            and f.method not in CAT1_METHODS and f.gambling_form is None)


def bucket(n):
    return "未知" if n is None else "≤4" if n <= 4 else "5-9" if n <= 9 else "≥10"


def l1_cell(f):
    return (f.venue_type or "未知", bucket(f.participant_count))


def l1_label(c):
    """开发集上类别的来源：标注的 gambling_form；否则用历史处罚反推（只有一类与之相符时）。"""
    f = c["facts"]
    if c["province"] != "320000" or f.behavior_type != "参与赌博" or f.method in CAT1_METHODS:
        return None
    if f.gambling_form:
        return "cat1" if f.gambling_form in ("聚众赌博", "赌场赌博") else "cat2"
    if _measure_interval(f, "personal_or_per_capita") is None:
        return None
    ok = [k for k, form in CAT_FORM.items() if types_of(with_(f, gambling_form=form)) == [c["historical"]]]
    return ok[0] if len(ok) == 1 else None


def l2_needed(c):
    """需要本人赌资且不明/开口，并有部分线索 → (下界, 上界)；否则 None。"""
    f = c["facts"]
    if f.behavior_type != "参与赌博":
        return None
    key = "personal_or_per_capita" if c["province"] == "320000" else "personal_stake"
    got = _measure_interval(f, key)
    if c["province"] == "130000" and got is None and f.onsite_stake_total is not None:
        return None                                        # 河北个人不明按一场赌资门槛（primary_v2），无潜变量
    if got is not None and got[0][1] != float("inf"):
        return None                                        # 赌资确定
    lo = got[0][0] if got else 0.0
    hi = f.onsite_stake_total.upper if (got is None and f.onsite_stake_total is not None) else float("inf")
    elevate = [e["when"] for e in LIB.provinces[c["province"]]["rules"]["参与赌博"].get("elevate") or []]
    has_clue = got is not None or hi != float("inf") or any(_flag(f, w) is True for w in elevate)
    return (lo, hi) if has_clue else None


class Priors:
    def __init__(self, dev):
        lab = [(l1_cell(c["facts"]), c["l1"]) for c in dev if c.get("l1")]
        self.p0 = (sum(y == "cat1" for _, y in lab) + 1) / (len(lab) + 2)
        self.cells = defaultdict(lambda: [0, 0])
        for cell, y in lab:
            self.cells[cell][0] += y == "cat1"
            self.cells[cell][1] += 1
        self.values = defaultdict(list)
        for c in dev:
            f = c["facts"]
            if f.behavior_type == "参与赌博" and f.personal_stake is not None and f.personal_stake.max == f.personal_stake.min:
                v = f.personal_stake.min
                self.values[(c["province"], f.method == "网络赌博")].append(v)
                self.values[(c["province"], None)].append(v)

    def p_cat1(self, f):
        k, n = self.cells.get(l1_cell(f), (0, 0))
        return (k + SMOOTH * self.p0) / (n + SMOOTH)

    def stake_values(self, prov, f, lo, hi):
        vals = self.values.get((prov, f.method == "网络赌博"), [])
        if len(vals) < MIN_VALUES:
            vals = self.values.get((prov, None), [])
        return [v for v in vals if lo <= v <= hi]


def b_distribution(c, pri):
    """概率版：触发潜变量时返回种类分布，否则 None（与第一版相同）。"""
    f = c["facts"]
    l2 = l2_needed(c)
    stakes = [(None, 1.0)]
    if l2:
        vals = pri.stake_values(c["province"], f, *l2)
        if not vals:
            l2 = None
        else:
            stakes = [(AmountRange(min=v, max=v), 1 / len(vals)) for v in vals]
    cats = [(None, 1.0)]
    if form_unknown(c) and (l2 or _measure_interval(f, "personal_or_per_capita") is not None):
        p = pri.p_cat1(f)
        cats = [(CAT_FORM["cat1"], p), (CAT_FORM["cat2"], 1 - p)]
        diff = {tuple(types_of(with_(f, gambling_form=form, **({"personal_stake": s} if s else {}))))
                for form, _ in cats for s, _ in stakes}
        if len(diff) == 1:
            cats = [(None, 1.0)]                            # 两类门槛结论相同：不触发 L1
    if not l2 and cats[0][0] is None:
        return None, []
    dist, used = Counter(), (["L1"] if cats[0][0] else []) + (["L2"] if l2 else [])
    for form, pc in cats:
        for s, ps in stakes:
            kw = {**({"gambling_form": form} if form else {}), **({"personal_stake": s} if s else {})}
            ts = types_of(with_(f, **kw))
            if not ts:
                continue
            for t in ts:
                dist[t] += pc * ps / len(ts)
    total = sum(dist.values())
    return ({t: dist[t] / total for t in ORDER} if total else None), used


def a_distribution(c, proba):
    d = decide(c["facts"], proba, LIB)
    if d.route == "rule_single":
        return {t: float(t == d.candidates[0]) for t in ORDER}
    if d.route == "rule_candidates":
        z = sum(proba.get(t, 0) for t in d.candidates)
        return {t: (proba.get(t, 0) / z if t in d.candidates else 0.0) for t in ORDER}
    return {t: proba.get(t, 0.0) for t in ORDER}


def rps(dist, truth):
    cp = np.cumsum([dist[t] for t in ORDER])[:-1]
    ct = np.cumsum([float(t == truth) for t in ORDER])[:-1]
    return float(np.mean((cp - ct) ** 2))


def text_model(train, exclude):
    ids = {c["id"] for c in exclude}
    evs = {c["event_id"] for c in exclude}
    txt = {re.sub(r"\s+", "", c["facts_text"]) for c in exclude}
    keep = [r for r in train if r["id"] not in ids and r["event_id"] not in evs
            and re.sub(r"\s+", "", r["input"]["facts_text"]) not in txt]
    size = Counter(r["event_id"] for r in keep)
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True, min_df=2, max_features=100_000)
    lr = LogisticRegression(C=3.0, max_iter=2000, class_weight="balanced", random_state=20261027)
    lr.fit(vec.fit_transform(r["input"]["facts_text"] for r in keep), [norm_type(r["target"]["type"]) for r in keep],
           sample_weight=[1 / size[r["event_id"]] for r in keep])
    return lambda texts: [dict(zip(lr.classes_, p)) for p in lr.predict_proba(vec.transform(texts))], len(keep)


def summarize(rows, seed=20261028):
    if not rows:
        return {"n": 0}
    ev = defaultdict(list)
    for r in rows:
        ev[r["event_id"]].append(r)
    units = list(ev.values())
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(2000):
        s = [r for j in rng.integers(0, len(units), len(units)) for r in units[j]]
        diffs.append(np.mean([r["rps_B"] - r["rps_A"] for r in s]))
    top = lambda d: max(ORDER, key=lambda t: d[t])  # noqa: E731
    m = lambda k: round(float(np.mean([r[k] for r in rows])), 4)  # noqa: E731
    acc = lambda k: round(float(np.mean([top(r[k]) == r["historical"] for r in rows])), 3)  # noqa: E731
    return {"n": len(rows), "events": len(units), "latents": dict(Counter("+".join(r["latents"]) for r in rows)),
            "rps_A": m("rps_A"), "rps_B": m("rps_B"), "rps_C": m("rps_C"),
            "rps_diff_B_minus_A": round(float(np.mean(diffs)), 4),
            "rps_diff_CI95": [round(float(x), 4) for x in np.quantile(diffs, [0.025, 0.975])],
            "acc_A": acc("dist_A"), "acc_B": acc("dist_B"), "acc_C": acc("dist_C")}


def verdict(s):
    if s["n"] == 0:
        return "无主分析记录"
    sign = "方向支持" if s["rps_diff_B_minus_A"] < 0 else "方向不支持"
    if s["n"] < 60:
        return f"{sign}（主分析子集 {s['n']} < 60，只作方向信号）"
    ok = s["rps_diff_CI95"][1] < 0 and s["acc_B"] >= s["acc_A"] - 0.03
    return "概率版得到支持" if ok else "不支持"


def main():
    split = sys.argv[1]
    if split not in ("dev", "test"):
        raise SystemExit(__doc__)
    train = jl(TRAIN)
    by_id = {r["id"]: r for r in train}
    dev, dev_audit = load_cases("dev", by_id)
    dev_in = [c for c in dev if c["scope"] == "in_scope"]
    for c in dev_in:
        c["l1"] = l1_label(c)
    test_pool = [{"id": r["id"], "event_id": by_id[r["id"]]["event_id"], "facts_text": r["facts_text"]}
                 for r in jl(TEST_RUN / "inputs.jsonl")]
    predict, n_train = text_model(train, dev + test_pool)
    if split == "dev":
        evaluated, audit = dev_in, dev_audit
    else:
        test, audit = load_cases("test", by_id)
        dev_events = {c["event_id"] for c in dev}
        evaluated = [c for c in test if c["scope"] == "in_scope" and c["event_id"] not in dev_events]
        audit["shares_event_with_dev"] = sum(c["scope"] == "in_scope" and c["event_id"] in dev_events for c in test)
    probas = predict([c["facts_text"] for c in evaluated])
    full_pri = Priors(dev_in)
    rows = []
    for c, proba in zip(evaluated, probas):
        pri = full_pri if split == "test" else Priors([x for x in dev_in if x["event_id"] != c["event_id"]])
        dist_b, latents = b_distribution(c, pri)
        if dist_b is None:
            continue
        dist_a, dist_c = a_distribution(c, proba), {t: proba.get(t, 0.0) for t in ORDER}
        rows.append({"id": c["id"], "event_id": c["event_id"], "province": c["province"], "historical": c["historical"],
                     "latents": latents, "dist_A": dist_a, "dist_B": dist_b, "dist_C": dist_c,
                     "rps_A": rps(dist_a, c["historical"]), "rps_B": rps(dist_b, c["historical"]),
                     "rps_C": rps(dist_c, c["historical"])})
    overall = summarize(rows)
    report = {"split": split, "prereg": "PREREG.md v1.1", "audit": dict(audit), "text_train_rows": n_train,
              "in_scope": len(evaluated),
              "priors": {"l1_labelled": sum(bool(c.get("l1")) for c in dev_in), "l1_p0": round(full_pri.p0, 3),
                         "stake_values": {f"{k[0]}:{k[1]}": len(v) for k, v in full_pri.values.items()}},
              "partial_subset": overall, "verdict": verdict(overall),
              "by_province": {p: summarize([r for r in rows if r["province"] == p]) for p in START}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"report_{split}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    if split == "dev":                                      # 检验集逐条结果不落盘给主会话看，只出汇总
        (OUT / "rows_dev.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
