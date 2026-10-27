"""A: within-band quantity prediction given the (historical) band. See PREREG_A.md."""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, r"D:/02_Dev/Projects/大创/research/eval")
from m4_amount_feature_cv import amount_features  # noqa: E402

ROOT = Path("D:/02_Dev/Data/justilaw-research")
OUT = Path("D:/02_Dev/Data/justilaw-research/engine/development/rule-chain-20261028")
TASKS = [("罚款", "fine"), ("拘留", "detention_days"), ("拘留并处罚款", "detention_days"), ("拘留并处罚款", "fine")]
CITIES = {"13": "河北 石家庄 保定 邯郸 邢台 沧州 衡水 廊坊 唐山 秦皇岛 张家口 承德 辛集 定州 雄安".split(),
          "32": "江苏 南京 苏州 无锡 常州 南通 扬州 镇江 泰州 盐城 淮安 连云港 宿迁 徐州".split()}
MODELS = ["M0_mode", "M1_agency", "M2_text", "M3_text_amount", "M4_text_x_agency"]

rows = [json.loads(l) for l in open(ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl", encoding="utf-8")]
ctx = {json.loads(l)["id"]: json.loads(l) for l in open(
    ROOT / "engine/development/m4-agency-prior-cv-v2-20261027/context.jsonl", encoding="utf-8")}


def province(r):
    c = ctx[r["id"]]
    p = c.get("province_code")
    if p in CITIES:
        return p
    a = c.get("authority_id") or ""
    return next((k for k, v in CITIES.items() if any(n in a for n in v)), p)


def nearest(v, classes):
    return min(classes, key=lambda c: (abs(c - v), c))


def boot(hit_a, hit_b, events, draws=2000, seed=20261028):
    g = defaultdict(list)
    for i, e in enumerate(events):
        g[e].append(i)
    units = list(g.values())
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(draws):
        s = [i for j in rng.integers(0, len(units), len(units)) for i in units[j]]
        d.append(hit_a[s].mean() - hit_b[s].mean())
    return [round(float(x), 3) for x in np.quantile(d, [0.025, 0.975])]


def run_task(band, field, axis):
    sub = [r for r in rows if r["target"]["type"] == band and r["target"].get(field) is not None
           and (ctx[r["id"]].get("decision_date") or "0") < "2026-01-01"]
    y = np.array([float(r["target"][field]) for r in sub])
    texts = [r["input"]["facts_text"] for r in sub]
    events = [r["event_id"] for r in sub]
    agencies = [ctx[r["id"]].get("authority_id") or "missing" for r in sub]
    dates = [ctx[r["id"]].get("decision_date") or "" for r in sub]
    prov = [province(r) for r in sub]
    size = Counter(events)
    w = np.array([1 / size[e] for e in events])
    amt = np.array([amount_features(t) for t in texts])
    if axis == "forward":
        tr = np.array([i for i, d in enumerate(dates) if d and d < "2024-01-01"])
        va = np.array([i for i, d in enumerate(dates) if d and "2024-01-01" <= d < "2026-01-01"])
        splits = [(tr, va)]
    else:
        groups = events if axis == "event" else agencies
        splits = list(GroupKFold(n_splits=3).split(texts, y, groups))
    pred = {m: np.zeros((len(sub), 2)) for m in MODELS}
    evaluated = []
    for tr, va in splits:
        cnt = Counter(y[tr])
        classes = sorted(v for v, n in cnt.items() if n >= 10) or [cnt.most_common(1)[0][0]]
        ytr = np.array([nearest(v, classes) for v in y[tr]])
        gl = Counter()
        for i, v in zip(tr, ytr):
            gl[v] += w[i]
        tot = sum(gl.values())
        p_gl = np.array([(gl[c] + 0.5) / (tot + 0.5 * len(classes)) for c in classes])
        ag = defaultdict(Counter)
        for i, v in zip(tr, ytr):
            ag[agencies[i]][v] += w[i]

        def p_agency(a):
            c = ag.get(a)
            if not c or a == "missing":
                return p_gl
            n = sum(c.values())
            return np.array([(c[k] + 20 * p_gl[j]) / (n + 20) for j, k in enumerate(classes)])

        vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True, min_df=2, max_features=100_000)
        xt, xv = vec.fit_transform(texts[i] for i in tr), vec.transform(texts[i] for i in va)
        sc = StandardScaler().fit(amt[tr])
        xt2 = hstack([xt, csr_matrix(sc.transform(amt[tr]))]).tocsr()
        xv2 = hstack([xv, csr_matrix(sc.transform(amt[va]))]).tocsr()
        probs = {}
        for name, a_, b_ in (("M2_text", xt, xv), ("M3_text_amount", xt2, xv2)):
            if len(set(ytr)) < 2:
                probs[name] = np.tile(p_gl, (len(va), 1))
                continue
            m = LogisticRegression(C=1.0, max_iter=2000, random_state=20261028)
            m.fit(a_, ytr, sample_weight=w[tr])
            p = np.zeros((len(va), len(classes)))
            for j, c in enumerate(m.classes_):
                p[:, classes.index(c)] = m.predict_proba(b_)[:, j]
            probs[name] = p
        probs["M0_mode"] = np.tile(p_gl, (len(va), 1))
        probs["M1_agency"] = np.array([p_agency(agencies[i]) for i in va])
        fused = probs["M2_text"] * (probs["M1_agency"] / p_gl) ** 0.5
        probs["M4_text_x_agency"] = fused / fused.sum(1, keepdims=True)
        cls = np.array(classes)
        for name, p in probs.items():
            order = np.argsort(-p, axis=1)
            pred[name][va, 0] = cls[order[:, 0]]
            pred[name][va, 1] = cls[order[:, 1]] if len(classes) > 1 else cls[order[:, 0]]
        evaluated.extend(va.tolist())
    ev = np.array(sorted(evaluated))
    two = np.array([i for i in ev if prov[i] in ("13", "32")])
    out = {"n": int(len(ev)), "events": len({events[i] for i in ev}), "n_two_prov": int(len(two)),
           "value_share_top3": [(v, round(c / len(ev), 2)) for v, c in Counter(y[ev]).most_common(3)]}
    base_hit = (pred["M0_mode"][ev, 0] == y[ev]).astype(float)
    for name in MODELS:
        hit = (pred[name][ev, 0] == y[ev]).astype(float)
        top2 = ((pred[name][ev, 0] == y[ev]) | (pred[name][ev, 1] == y[ev])).mean()
        res = {"hit": round(hit.mean(), 3), "mae": round(float(np.abs(pred[name][ev, 0] - y[ev]).mean()), 1),
               "top2": round(float(top2), 3)}
        if len(two):
            res["hit_two_prov"] = round(float((pred[name][two, 0] == y[two]).mean()), 3)
        if name != "M0_mode":
            res["delta_vs_M0_CI"] = boot(hit, base_hit, [events[i] for i in ev])
        out[name] = res
    return out


report = {}
for band, field in TASKS:
    key = f"{band}:{field}"
    report[key] = {axis: run_task(band, field, axis) for axis in ("event", "agency", "forward")}
    print(key, json.dumps(report[key], ensure_ascii=False))
(OUT / "within_band_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
