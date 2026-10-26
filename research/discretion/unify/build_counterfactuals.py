"""Counterfactual variants of real records whose expected answers follow from the edit itself.

No reviewer is involved: each edit fixes what a correct binder must do.

- relabel        : every occurrence of the referenced amount v becomes an unseen v'; fields whose
                   reference was v must now give v', the others must not change.
- delete_evidence: the clause holding the referenced personal stake is removed (only when no other
                   occurrence of v is left); the personal stake must no longer be v.
- rename_target  : the target's surname is changed everywhere it refers to the target; nothing
                   may change.
- rename_others  : other masked persons get new surnames; nothing may change.

Edits keep offsets source-exact: views are shifted, view text, facts/meta text, view hash and
source hash are recomputed. A variant is skipped when an edit would cross a view boundary.
Expectations compare against the reference (`value`, `not_value`) or against the binder's own
output on the unedited record (`same_as_base`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from element_contract import digest
from evaluate_relation_model_labels import amount_key
from experiment_relation_edges import amounts_of, load_batch
from ownership import MASKED_NAME
from supply_packet import build_packet

AMOUNT_FIELDS = ("personal_stake", "onsite_stake_total")
FIELDS = AMOUNT_FIELDS + ("participant_count", "age")
PLAIN_AMOUNT = re.compile(r"^(?:人民币)?([0-9]+)(元|块)$")
NEW_SURNAMES = "覃韦蒙樊雷龚骆阮邝牛"
DELTAS = (137, 263, 391, 517)


def apply_edits(rec: dict, edits: list[tuple[int, int, str]], suffix: str) -> dict | None:
    """New record with text edits applied and every derived field recomputed; None if unsafe."""
    edits = sorted(edits)
    if any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
        return None
    views = rec["sentence_view"]
    for a, b, _ in edits:
        # Fully inside one view, or fully outside all of them (hidden zones are edited too).
        if any(a < v["end"] and v["start"] < b and not (v["start"] <= a and b <= v["end"]) for v in views):
            return None
    text, out, pos = rec["text_full"], [], 0
    for a, b, new in edits:
        out.append(text[pos:a] + new)
        pos = b
    new_text = "".join(out) + text[pos:]

    def shift(i: int) -> int:
        # Every edit lies inside one view, so an edit ending at or before i is wholly before it.
        return i + sum(len(new) - (b - a) for a, b, new in edits if b <= i)

    new_views = []
    for v in views:
        s, e = shift(v["start"]), shift(v["end"])
        new_views.append({**v, "start": s, "end": e, "text": new_text[s:e]})
    if any(not v["text"].strip() for v in new_views):
        new_views = [v for v in new_views if v["text"].strip()]
    return {**rec, "id": f"{rec['id']}#{suffix}", "text_full": new_text, "sentence_view": new_views,
            "facts_text": "\n".join(v["text"] for v in new_views if v["type"] == "facts"),
            "meta_text": "\n".join(v["text"] for v in new_views if v["type"] == "meta"),
            "view_hash": digest(new_views),
            "source_sha256": hashlib.sha256(new_text.encode("utf-8")).hexdigest()}


def _amount_value(q: dict) -> int | None:
    p = q.get("engine_projection") or {}
    if p.get("min") is None or p["min"] != p.get("max") or p["min"] != int(p["min"]):
        return None
    return int(p["min"])


def relabel(it: dict) -> list[tuple[dict, dict]]:
    out = []
    amounts = amounts_of(it["packet"])
    present = {_amount_value(q) for q in amounts}
    for f in AMOUNT_FIELDS:
        ref = it["refs"][f]["consensus"]
        if not ref or ref[0] != "selected":
            continue
        v = ref[1].split(":", 1)[1]
        if not v.isdigit():
            continue
        v = int(v)
        hits = [q for q in amounts if _amount_value(q) == v]
        if not hits or any(not PLAIN_AMOUNT.match(q["raw"]) for q in hits):
            continue
        new = next((v + d for d in DELTAS if v + d not in present), None)
        if new is None:
            continue
        edits = [(q["start"], q["end"], ("人民币" if q["raw"].startswith("人民币") else "") + f"{new}" +
                  PLAIN_AMOUNT.match(q["raw"])[2]) for q in hits]
        variant = apply_edits(it["record"], edits, f"relabel-{f}")
        if variant is None:
            continue
        expect = {}
        for g in FIELDS:
            gref = it["refs"][g]["consensus"]
            expect[g] = ({"type": "value", "value": f"amount:{new}"} if g in AMOUNT_FIELDS and gref
                         and gref[0] == "selected" and gref[1] == f"amount:{v}" else {"type": "same_as_base"})
        out.append((variant, {"kind": "relabel", "from": f"amount:{v}", "to": f"amount:{new}", "expect": expect}))
        break  # one relabel per record keeps the suite balanced
    return out


def delete_evidence(it: dict) -> list[tuple[dict, dict]]:
    ref = it["refs"]["personal_stake"]
    if not ref["consensus"] or ref["consensus"][0] != "selected" or not ref["candidate_ids"]:
        return []
    quantities = {q["candidate_id"]: q for q in it["packet"]["quantities"]}
    chosen = [quantities[c] for c in ref["candidate_ids"] if c in quantities]
    if not chosen:
        return []
    scenes = [next((s for s in it["packet"]["scenes"] if s["start"] <= q["start"] < s["end"]), None) for q in chosen]
    if any(s is None for s in scenes):
        return []
    spans = sorted({(s["start"], s["end"]) for s in scenes})
    v = ref["consensus"][1]
    left = [q for q in amounts_of(it["packet"]) if amount_key(q["engine_projection"]) == v
            and not any(a <= q["start"] < b for a, b in spans)]
    if left:
        return []
    variant = apply_edits(it["record"], [(a, b, "") for a, b in spans], "delete-personal")
    if variant is None or it["record"]["target"] not in variant["text_full"]:
        return []
    expect = {"personal_stake": {"type": "not_value", "value": v}}
    oref = it["refs"]["onsite_stake_total"]
    onsite_ids = oref["candidate_ids"]
    if not any(a <= quantities[c]["start"] < b for c in onsite_ids if c in quantities for a, b in spans):
        expect["onsite_stake_total"] = {"type": "same_as_base"}
    return [(variant, {"kind": "delete_evidence", "removed": v, "expect": expect})]


def _surname_forms(text: str, surname: str) -> set[str]:
    return {m.group() for m in MASKED_NAME.finditer(text) if m.group().startswith(surname)}


def rename_target(it: dict) -> list[tuple[dict, dict]]:
    rec = it["record"]
    target, text = rec["target"], rec["text_full"]
    names = {target, *(rec.get("aliases") or ())}
    surname = target[0]
    # Role aliases such as 申请人 are not names; only surname-led forms are renamed.
    forms = _surname_forms(text, surname) | {n for n in names if n in text and n.startswith(surname)}
    # Several different same-surname forms may be different people; keep only clear cases.
    if len({f for f in forms if f not in names}) > 1:
        return []
    new_surname = next((s for s in NEW_SURNAMES if s not in text), None)
    if new_surname is None:
        return []
    pattern = re.compile("|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)))
    edits = [(m.start(), m.start() + 1, new_surname) for m in pattern.finditer(text)]
    variant = apply_edits(rec, edits, "rename-target")
    if variant is None:
        return []
    variant["target"] = new_surname + target[1:]
    variant["aliases"] = [new_surname + a[1:] if a.startswith(surname) else a for a in rec.get("aliases") or ()]
    return [(variant, {"kind": "rename_target", "to": variant["target"],
                       "expect": {f: {"type": "same_as_base"} for f in FIELDS}})]


def rename_others(it: dict) -> list[tuple[dict, dict]]:
    rec = it["record"]
    text, surname = rec["text_full"], rec["target"][0]
    others = sorted({m.group()[0] for m in MASKED_NAME.finditer(text) if m.group()[0] != surname})
    pool = [s for s in NEW_SURNAMES if s not in text]
    if not others or len(pool) < len(others):
        return []
    mapping = dict(zip(others, pool))
    edits = [(m.start(), m.start() + 1, mapping[m.group()[0]]) for m in MASKED_NAME.finditer(text)
             if m.group()[0] in mapping]
    variant = apply_edits(rec, edits, "rename-others")
    if variant is None:
        return []
    return [(variant, {"kind": "rename_others", "mapping": mapping,
                       "expect": {f: {"type": "same_as_base"} for f in FIELDS}})]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    variants, expects, stats = [], [], Counter()
    for b in args.batch:
        for it in load_batch(b, b / "ab" / "labels"):
            stats["records"] += 1
            for make in (relabel, delete_evidence, rename_target, rename_others):
                for variant, meta in make(it):
                    try:  # an edit that leaves the target invisible is not a valid variant
                        build_packet(variant["text_full"], variant, record_id=variant["id"])
                    except ValueError:
                        stats["unbuildable_" + meta["kind"]] += 1
                        continue
                    variants.append(variant)
                    expects.append({"variant_id": variant["id"], "base_id": it["id"], **meta})
                    stats[meta["kind"]] += 1
    args.out.mkdir(parents=True)
    (args.out / "inputs.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in variants), "utf-8")
    (args.out / "expect.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in expects), "utf-8")
    manifest = {"version": "counterfactual-1", "batches": [str(b) for b in args.batch], "counts": dict(stats),
                "inputs_sha256": hashlib.sha256((args.out / "inputs.jsonl").read_bytes()).hexdigest()}
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
