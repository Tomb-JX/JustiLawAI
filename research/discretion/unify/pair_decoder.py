"""Personal stake by joint decoding over person–amount pair scores (no LLM at inference).

The frozen binding-v1 pair encoder scores every (person proposal, amount candidate) pair; this
module turns the scores of one record into a decision with three structural constraints instead
of the v1 three-route consensus:

  1. exclusive ownership: an amount belongs to the person whose holds-score is highest;
  2. a total is not personal: an amount equal to the sum of two or more other distinct amount
     values of the record (within 0.5%) is a total;
  3. stake definition (两高 2005 解释第八条): several stake values of the target -> the largest.

Decision: a target-owned amount with score ≥ tau_fill -> fill (largest); every amount's target
score < tau_absent -> absent; otherwise to a person. A record without amount candidates is absent.
Thresholds are chosen on dev only (criteria lf-20261028/CRITERIA-pair-decoder.md).
"""
from __future__ import annotations

from pathlib import Path

from binding_service import PairScorer
from evaluate_relation_model_labels import amount_key
from experiment_relation_edges import amounts_of
from export_pair_examples import window
from run_pair_relation_labels import persons_of
from supply_packet import build_packet

STAKE_CLASSES = ("holds", "each_share")
TOLERANCE = 0.005
MAX_SUMS = 200000


def score_records(records: list[dict], model_dir: Path, threads: int = 8) -> list[dict]:
    """Per record: candidates (value key, float value) and per person the stake score of each candidate."""
    scorer = PairScorer(model_dir, threads=threads)
    items, texts, index = [], [], []
    for r in records:
        packet = build_packet(r["text_full"], r, record_id=r["id"])
        it = {"id": r["id"], "record": r, "packet": packet, "persons": persons_of(packet, r)}
        cands = amounts_of(packet)
        items.append({"id": r["id"], "cands": [{"key": amount_key(q["engine_projection"]),
                                                "value": float(q["engine_projection"]["min"])} for q in cands],
                      "persons": [{"target": p["kind"] == "target"} for p in it["persons"]], "scores": {}})
        for qi, q in enumerate(cands):
            for pi, p in enumerate(it["persons"]):
                texts.append(window(it, q, p)["text"])
                index.append((len(items) - 1, qi, pi))
    for (ri, qi, pi), probs in zip(index, scorer.probs(texts)):
        items[ri]["scores"][(qi, pi)] = sum(probs[c] for c in STAKE_CLASSES)
    return items


def is_total(values: list[float], k: int) -> bool:
    """values[k] equals the sum of a subset of the other distinct values (subset size ≥ 2 follows)."""
    v = values[k]
    others = sorted({x for i, x in enumerate(values) if i != k and x != v and x < v})
    sums = {0.0}
    for x in others:
        sums |= {s + x for s in sums if s + x <= v * (1 + TOLERANCE)}
        if len(sums) > MAX_SUMS:
            return False
    return any(abs(s - v) <= v * TOLERANCE for s in sums if s > 0)


def decide(item: dict, tau_fill: float, tau_absent: float) -> str | None:
    """Value key, "absent", or None (to a person)."""
    cands = item["cands"]
    if not cands:
        return "absent"
    target = [i for i, p in enumerate(item["persons"]) if p["target"]]
    if not target:
        return None
    t = target[0]
    values = [c["value"] for c in cands]
    owned, best = [], 0.0
    for qi, c in enumerate(cands):
        st = item["scores"].get((qi, t), 0.0)
        best = max(best, st)
        rival = max((s for (q, p), s in item["scores"].items() if q == qi and p != t), default=0.0)
        if st >= tau_fill and st > rival and not is_total(values, qi):
            owned.append(c)
    if owned:
        return max(owned, key=lambda c: c["value"])["key"]
    return "absent" if best < tau_absent else None
