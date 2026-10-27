"""B: rule-chain evaluation entry. Elements -> (interpretation adapter) -> M2 bands -> type, vs text LR.

usage: python eval_chain.py --source silver|annot|both --out DIR
Interpretations (PREREG.md, 规则口径决定): primary / A_literal / B_below_to_fine.
annot = s1_runs/manual-batches-20261028-rulechain, only labels passing check.py are used.
"""
import argparse, json, re, sqlite3, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, r"D:/02_Dev/Projects/大创/justilaw-api")
from app.discretion.norm_layer import Facts, assess  # noqa: E402
from app.discretion.norm_store import load  # noqa: E402
from app.discretion.schema import AmountRange, GamblingElements  # noqa: E402

ROOT = Path("D:/02_Dev/Data/justilaw-research")
RUN = ROOT / "s1_runs/manual-batches-20261028-rulechain"
sys.path.insert(0, str(RUN))
import check  # noqa: E402

TRAIN = ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl"
SILVER = ROOT / "parsed2/m4-pilot-203-silver-20261020/records.jsonl"
S1_FILES = ["unified_raw_refresh/20261018-s1-repaired/records.jsonl",
            "unified_raw_refresh/20261026-P3P7-additions/records.jsonl",
            "unified_raw_refresh/20261027-P9-additions/records.jsonl"]
START = {"130000": date(2021, 11, 17), "320000": date(2019, 2, 2)}
NAME = {"130000": "河北", "320000": "江苏"}
CITIES = {"130000": "河北 石家庄 保定 邯郸 邢台 沧州 衡水 廊坊 唐山 秦皇岛 张家口 承德 辛集 定州 雄安".split(),
          "320000": "江苏 南京 苏州 无锡 常州 南通 扬州 镇江 泰州 盐城 淮安 连云港 宿迁 徐州".split()}
LABELS = ["不予处罚", "拘留", "拘留并处罚款", "罚款"]
MODES = ["primary_v2", "primary", "A_literal", "B_below_to_fine"]


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def norm_type(t):
    return t if t in LABELS else "不予处罚"


def band_types(band):
    names, pens = band["bands"], list(band["band_penalty"])
    if names and names[0] == "未达起罚标准":
        pens = ["-"] + pens
    out = set()
    for n, p in zip(names, pens):
        out.add("不予处罚" if n == "未达起罚标准" else
                "拘留并处罚款" if ("拘留" in p and "罚款" in p) else "拘留" if "拘留" in p else "罚款")
    return out


def rule_types(ref, prov, bd, dd, mode, lib):
    el = GamblingElements.model_validate({"meta": {"region": prov, "behavior_date": bd, "decision_date": dd}, **ref})
    f = Facts.from_elements(el)
    onsite = f.onsite_stake_total
    hebei_part = prov == "130000" and f.behavior_type == "参与赌博"
    if mode != "A_literal" and hebei_part:
        if f.personal_stake is not None:
            f.onsite_stake_total = None
        elif mode == "primary" and onsite is not None and f.participant_count:
            n = f.participant_count
            f.personal_stake = AmountRange(min=onsite.min / n, max=None if onsite.max is None else onsite.max / n)
            f.onsite_stake_total = None
    band = assess(f, lib).stake_threshold
    types = band_types(band)
    if mode != "A_literal" and hebei_part and onsite is not None and onsite.min >= 500 and "不予处罚" in types:
        types.discard("不予处罚")      # 一场赌资达到入罚线：托底第一档
        types.add("罚款")
    if mode == "B_below_to_fine" and prov == "130000" and "不予处罚" in types:
        types.discard("不予处罚")
        types.add("罚款")
    return sorted(types), band["status"], f


def province_of(meta_prov, authority, lake):
    if meta_prov:
        return meta_prov, "metadata"
    a = re.sub(r"\s+", "", authority or "")
    if a and len(lake.get(a, ())) == 1:
        return next(iter(lake[a])), "lake_exact"
    for code, names in CITIES.items():
        if any(n in a for n in names):
            return code, "authority_name"
    return None, "unknown"


def load_cases(source, train_by_id):
    lake = defaultdict(set)
    con = sqlite3.connect(str(ROOT / "lake/catalog/lake.db"))
    for a, rc in con.execute("select authority, region_code from documents where authority is not null and region_code is not null"):
        if re.fullmatch(r"\d{6}", rc or ""):
            lake[re.sub(r"\s+", "", a)].add(rc[:2] + "0000")
    con.close()
    cases, audit = [], Counter()
    if source in ("silver", "both"):
        for r in jl(SILVER):
            if r["metadata"].get("split") == "test":
                continue  # test40: never read
            m = r["metadata"]
            prov, _ = province_of(m.get("province_code"), m.get("authority"), lake)
            cases.append({"id": r["id"], "src": "silver", "event_id": m.get("event_id"), "province": prov,
                          "bd": m.get("behavior_date"), "dd": m.get("decision_date"),
                          "historical": norm_type(r["observed_outcome"]["type"]),
                          "facts_text": r["input"]["facts_text"], "ref": r["reference_elements"]})
    if source in ("annot", "both"):
        recs = {r["id"]: r for r in jl(RUN / "inputs.jsonl")}
        s1 = {}
        for f in S1_FILES:
            for x in jl(ROOT / f):
                if x["id"] in recs:
                    s1[x["id"]] = x
        ctx = {json.loads(l)["id"]: json.loads(l) for l in open(
            ROOT / "engine/development/m4-agency-prior-cv-v2-20261027/context.jsonl", encoding="utf-8")}
        for nn in range(12):
            ids = json.loads((RUN / "assignments" / f"assign-{nn:02d}.json").read_text("utf-8"))
            got = {}
            for p in sorted((RUN / f"batch-{nn:02d}").glob("*.jsonl"), key=lambda p: (p.name != "labels.jsonl", p.name)):
                for line in p.read_text("utf-8").splitlines():
                    try:
                        row = json.loads(line)
                        got[row["id"]] = row
                    except Exception:  # noqa: BLE001
                        pass
            for rid in ids:
                if rid not in got:
                    audit["annot_missing"] += 1
                    continue
                if check.errors_of(recs[rid], got[rid]):
                    audit["annot_check_fail"] += 1
                    continue
                audit["annot_ok"] += 1
                c, s, t = ctx[rid], s1.get(rid, {}), train_by_id[rid]
                p2 = c.get("province_code")
                prov = (p2 + "0000") if p2 in ("13", "32") else province_of(None, c.get("authority_id"), lake)[0]
                cases.append({"id": rid, "src": "annot", "event_id": t["event_id"], "province": prov,
                              "bd": s.get("behavior_date"), "dd": c.get("decision_date"),
                              "historical": norm_type(t["target"]["type"]),
                              "facts_text": recs[rid]["facts_text"], "ref": got[rid]["reference_elements"]})
    return cases, audit


def summarize(sel, mode):
    n = len(sel)
    if not n:
        return {"n": 0}
    key = f"chain_{mode}"
    acc = lambda k, s: round(sum(c[k] == c["historical"] for c in s) / max(len(s), 1), 3)
    single = [c for c in sel if len(c[f"types_{mode}"]) == 1]
    ev = defaultdict(list)
    for c in sel:
        ev[c["event_id"]].append(c)
    units = list(ev.values())
    rng = np.random.default_rng(20261028)
    deltas = []
    for _ in range(2000):
        s = [c for j in rng.integers(0, len(units), len(units)) for c in units[j]]
        deltas.append(np.mean([c[key] == c["historical"] for c in s]) - np.mean([c["text_pred"] == c["historical"] for c in s]))
    return {"n": n, "events": len(units), "agencies": len({c["event_id"].split("|")[0] for c in sel}),
            "historical": dict(Counter(c["historical"] for c in sel)),
            "text_acc": acc("text_pred", sel), "chain_acc": acc(key, sel),
            "delta_CI": [round(float(x), 3) for x in np.quantile(deltas, [0.025, 0.975])],
            "rule_single_n": len(single), "rule_single_acc": acc(key, single), "text_acc_on_single": acc("text_pred", single),
            "candidate_contains_hist": sum(c["historical"] in c[f"types_{mode}"] for c in sel if c[f"types_{mode}"]),
            "routes": dict(Counter("single" if len(c[f"types_{mode}"]) == 1 else "multi" if c[f"types_{mode}"] else "none" for c in sel))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["silver", "annot", "both"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    train = jl(TRAIN)
    by_id = {r["id"]: r for r in train}
    cases, audit = load_cases(a.source, by_id)
    lib = load()
    for c in cases:
        bd, dd = d(c["bd"]), d(c["dd"])
        if c["province"] not in START:
            c["scope"] = "outside_two_provinces"
        elif bd is None or dd is None:
            c["scope"] = "date_missing"
        elif dd >= date(2026, 1, 1):
            c["scope"] = "new_law_2026"
        elif bd < START[c["province"]]:
            c["scope"] = "before_benchmark"
        else:
            c["scope"] = "in_scope"
            try:
                for mode in MODES:
                    c[f"types_{mode}"], c[f"status_{mode}"], _ = rule_types(c["ref"], c["province"], c["bd"], c["dd"], mode, lib)
            except Exception as exc:  # noqa: BLE001
                c["scope"] = "m2_error"
                c["error"] = f"{type(exc).__name__}: {exc}"[:300]
        audit[f"{c['src']}:{c['scope']}"] += 1
    # text model: v5 train minus every evaluated id / event / identical facts text
    ids = {c["id"] for c in cases}
    evs = {c["event_id"] for c in cases} | {by_id[i]["event_id"] for i in ids if i in by_id}
    txt = {re.sub(r"\s+", "", c["facts_text"]) for c in cases}
    keep = [r for r in train if r["id"] not in ids and r["event_id"] not in evs
            and re.sub(r"\s+", "", r["input"]["facts_text"]) not in txt]
    audit["text_train_rows"] = len(keep)
    size = Counter(r["event_id"] for r in keep)
    vec = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True, min_df=2, max_features=100_000)
    lr = LogisticRegression(C=3.0, max_iter=2000, class_weight="balanced", random_state=20261027)
    lr.fit(vec.fit_transform(r["input"]["facts_text"] for r in keep), [norm_type(r["target"]["type"]) for r in keep],
           sample_weight=[1 / size[r["event_id"]] for r in keep])
    P = lr.predict_proba(vec.transform(c["facts_text"] for c in cases))
    for c, p in zip(cases, P):
        proba = dict(zip(lr.classes_, p))
        c["text_pred"] = max(proba, key=proba.get)
        for mode in MODES:
            t = c.get(f"types_{mode}") or []
            c[f"chain_{mode}"] = t[0] if len(t) == 1 else max(t, key=lambda k: proba.get(k, 0)) if t else c["text_pred"]
    ins = [c for c in cases if c["scope"] == "in_scope"]
    report = {"source": a.source, "audit": dict(audit), "modes": {}}
    for mode in MODES:
        report["modes"][mode] = {"all_in_scope": summarize(ins, mode),
                                 **{NAME[p]: summarize([c for c in ins if c["province"] == p], mode) for p in START},
                                 **({"by_source": {s: summarize([c for c in ins if c["src"] == s], mode)
                                                   for s in ("silver", "annot")}} if a.source == "both" else {})}
    report["outside_text_only"] = {"n": sum(c["scope"] == "outside_two_provinces" for c in cases),
                                   "text_acc": round(np.mean([c["text_pred"] == c["historical"] for c in cases
                                                              if c["scope"] == "outside_two_provinces"] or [0]), 3)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    (a.out / "cases.jsonl").write_text("".join(json.dumps({k: v for k, v in c.items() if k != "ref"}, ensure_ascii=False, default=str) + "\n"
                                               for c in cases), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
