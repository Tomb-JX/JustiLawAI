"""Build the within-band quantity distribution used by app/discretion/decide.py.

Source: frozen v5 train, decisions before 2026-01-01 (old-law amounts), all provinces, event-weighted
(each event counts once, split across its records). Values with share < 1% are dropped and the rest renormalised.
Within-band amounts did not transfer to unseen agencies (docs/05-research/2026-10-28-rule-chain-validation.md),
so the engine reports this distribution rather than a point prediction.
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("D:/02_Dev/Data/justilaw-research")
TRAIN = ROOT / "engine/training/m4-facts-silver-p9-v5-frozen-20261027/train.jsonl"
CONTEXT = ROOT / "engine/development/m4-agency-prior-cv-v2-20261027/context.jsonl"
OUT = Path(__file__).resolve().parents[3] / "justilaw-api/app/discretion/data/band_quantities.json"
FIELDS = {"罚款": ("fine",), "拘留": ("detention_days",), "拘留并处罚款": ("detention_days", "fine")}

rows = [json.loads(l) for l in TRAIN.open(encoding="utf-8")]
dates = {r["id"]: r.get("decision_date") for r in map(json.loads, CONTEXT.open(encoding="utf-8"))}
rows = [r for r in rows if (dates.get(r["id"]) or "") and dates[r["id"]] < "2026-01-01"]
size = Counter(r["event_id"] for r in rows)
bands = {}
for kind, fields in FIELDS.items():
    bands[kind] = {}
    for f in fields:
        w = defaultdict(float)
        for r in rows:
            t = r["target"]
            if t["type"] == kind and t.get(f) is not None:
                w[float(t[f])] += 1 / size[r["event_id"]]
        total = sum(w.values())
        kept = {v: x for v, x in w.items() if x / total >= 0.01}
        s = sum(kept.values())
        bands[kind][f] = {"events": round(total, 1),
                          "values": [[v, round(x / s, 3)] for v, x in sorted(kept.items(), key=lambda kv: -kv[1])]}
out = {"version": "band-quantities-1", "law_epoch": "psal-2012（2026-01-01 前决定）",
       "source": str(TRAIN), "source_sha256": hashlib.sha256(TRAIN.read_bytes()).hexdigest(),
       "weighting": "每个事件计 1（同事件多人平分）", "min_share": 0.01, "bands": bands}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(json.dumps({k: {f: v["values"][:4] for f, v in b.items()} for k, b in bands.items()}, ensure_ascii=False))
