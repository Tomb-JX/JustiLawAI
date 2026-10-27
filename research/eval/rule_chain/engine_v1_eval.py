"""Engine v1 end-to-end on the 397 two-province records with manual elements.

type: rule single -> rule; rule candidates -> text within candidates; no rule output -> text  (eval_chain primary_v2)
quantity: global within-band distribution (train rows outside the evaluated events), mode + top-2  (PREREG_A verdict)
baseline: text type + the same quantity distribution.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path("D:/02_Dev/Data/justilaw-research")
HERE = Path("D:/02_Dev/Data/justilaw-research/engine/development/rule-chain-20261028")
train = [json.loads(l) for l in open(ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl", encoding="utf-8")]
tgt = {r["id"]: r["target"] for r in train}
silver = {json.loads(l)["id"]: json.loads(l)["observed_outcome"] for l in open(
    ROOT / "parsed2/m4-pilot-203-silver-20261020/records.jsonl", encoding="utf-8")}
cases = [c for c in map(json.loads, open(HERE / "out_both/cases.jsonl", encoding="utf-8")) if c["scope"] == "in_scope"]
evs = {c["event_id"] for c in cases} | {r["event_id"] for r in train if r["id"] in {c["id"] for c in cases}}
pool = [r["target"] for r in train if r["event_id"] not in evs]

FIELDS = {"罚款": ("fine",), "拘留": ("detention_days",), "拘留并处罚款": ("detention_days", "fine"), "不予处罚": ()}
dist = {(t, f): Counter(x[f] for x in pool if x["type"] == t and x.get(f) is not None)
        for t, fs in FIELDS.items() for f in fs}


def truth(c):
    o = tgt.get(c["id"]) or silver[c["id"]]
    return {"type": c["historical"], "detention_days": o.get("detention_days"), "fine": o.get("fine")}


def score(pred_type, t):
    """exact: type and every in-band quantity equal the mode; top2: every quantity within the band's two most common values."""
    if pred_type != t["type"]:
        return 0, 0
    exact = top2 = 1
    for f in FIELDS[pred_type]:
        common = [v for v, _ in dist[(pred_type, f)].most_common(2)]
        true = t[f]
        exact &= int(true is not None and float(true) == float(common[0]))
        top2 &= int(true is not None and float(true) in map(float, common))
    return exact, top2


def block(sel):
    n = len(sel)
    out = {"n": n}
    for name, key in (("engine_v1", "chain_primary_v2"), ("text_baseline", "text_pred")):
        e = t2 = ty = 0
        for c in sel:
            t = truth(c)
            ty += c[key] == t["type"]
            a, b = score(c[key], t)
            e += a
            t2 += b
        out[name] = {"type_acc": round(ty / n, 3), "full_exact": round(e / n, 3), "full_top2": round(t2 / n, 3)}
    return out


report = {"all": block(cases), "江苏": block([c for c in cases if c["province"] == "320000"]),
          "河北": block([c for c in cases if c["province"] == "130000"]),
          "band_distributions": {f"{t}:{f}": [(v, round(k / sum(d.values()), 2)) for v, k in d.most_common(4)]
                                 for (t, f), d in dist.items()}}
(HERE / "engine_v1_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
print(json.dumps(report, ensure_ascii=False, indent=1))
