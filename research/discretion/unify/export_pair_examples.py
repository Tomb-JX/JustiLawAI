"""Export labelled person–amount pairs as marked text windows for an encoder.

Window = the sentence holding the amount, extended to the sentence of the
person's nearest mention, capped at 256 characters around the amount. Typed
markers wrap that mention and the amount (Zhou & Chen-style entity markers).
Fold ids reuse `event_fold`, so encoder OOF predictions line up with the linear
model's folds. Only text, markers and labels leave; no model is run here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiment_pair_relations import load_pairs, view_of
from experiment_relation_edges import amounts_of
from experiment_selective_binding import event_fold
from ownership import CLAUSE, SENTENCE, bounds

MAX_CHARS = 256


def marker_type(person: dict) -> str:
    if person["kind"] == "target":
        return "目标"
    return "称谓" if person["kind"].startswith("role:") else "他人"


def subjectless(it: dict, q: dict) -> bool:
    """No proposed person is mentioned inside the amount's clause (a zero-anaphora candidate)."""
    view = view_of(it["packet"], q["start"])
    cl, cr = bounds(view["quote"], q["start"] - view["start"], CLAUSE)
    lo, hi = view["start"] + cl, view["start"] + cr
    return not any(lo <= s and e <= hi for p in it["persons"] for s, e in p["mentions"])


def window(it: dict, q: dict, person: dict, *, topic: bool = False, flag_subjectless: bool = False) -> dict | None:
    """Marked window; `topic` prefixes an absent target, `flag_subjectless` marks a clause without persons."""
    body = _window(it, q, person)
    prefix = ""
    if flag_subjectless and subjectless(it, q):
        prefix += "[无主]"
    if topic and person["kind"] == "target" and not body["person_in_window"]:
        # The discourse topic of a penalty notice is its target; give the encoder that referent explicitly.
        prefix += f"[人:目标]{person['surface']}[/人]："
        body["topic_prefixed"] = True
    body["text"] = prefix + body["text"]
    return body


def _window(it: dict, q: dict, person: dict) -> dict | None:
    view = view_of(it["packet"], q["start"])
    text, base = view["quote"], view["start"]
    mentions = [(s - base, e - base) for s, e in person["mentions"] if base <= s and e <= base + len(text)]
    a, b = q["start"] - base, q["end"] - base
    if mentions:
        ms, me = min(mentions, key=lambda m: min(abs(m[0] - b), abs(a - m[1])))
        if not (me <= a or ms >= b):
            ms = me = None  # overlapping spans cannot both be marked
    else:
        ms = me = None
    lo, hi = bounds(text, a, SENTENCE)
    if ms is not None:
        plo, phi = bounds(text, ms, SENTENCE)
        lo, hi = min(lo, plo), max(hi, phi)
    if hi - lo > MAX_CHARS:
        lo = max(lo, min(a, ms if ms is not None else a) - MAX_CHARS // 2)
        hi = min(hi, lo + MAX_CHARS)
        if ms is not None and not (lo <= ms and me <= hi):
            ms = me = None
    cuts = [(a, "[额]"), (b, "[/额]")]
    if ms is not None:
        cuts += [(ms, f"[人:{marker_type(person)}]"), (me, "[/人]")]
    out, prev = [], lo
    for pos, mark in sorted(cuts, key=lambda c: (c[0], c[1].startswith("[/") is False)):
        out.append(text[prev:pos])
        out.append(mark)
        prev = pos
    out.append(text[prev:hi])
    return {"text": "".join(out), "person_in_window": ms is not None,
            "person_surface": person["surface"], "person_type": marker_type(person)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev", type=Path, nargs=2, action="append", default=[], metavar=("BATCH", "LABELS"))
    ap.add_argument("--test", type=Path, nargs=2, metavar=("BATCH", "LABELS"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--topic", action="store_true", help="prefix the target when it is absent from the window")
    ap.add_argument("--subjectless", action="store_true", help="mark amounts whose clause names no person")
    ap.add_argument("--test-arbiter", default="kimi", help="C voter for holdout pair labels (kimi or claude)")
    args = ap.parse_args()
    groups = [("dev", it) for b, l in args.dev for it in load_pairs(b, l, "dev")]
    if args.test:
        groups += [("holdout", it) for it in load_pairs(args.test[0], args.test[1], "holdout", require_labels=False,
                                arbiter=args.test_arbiter)]
    n = 0
    with args.out.open("w", encoding="utf-8") as f:
        for split, it in groups:
            persons = {p["person_id"]: p for p in it["persons"]}
            quantities = {q["candidate_id"]: q for q in amounts_of(it["packet"])}
            # Unresolved pairs are exported with label null: never trained on, still predicted.
            all_pairs = {(q, p["person_id"]): it["pairs"].get((q, p["person_id"])) for q in quantities for p in it["persons"]}
            for (qid, pid), label in sorted(all_pairs.items()):
                w = window(it, quantities[qid], persons[pid], topic=args.topic, flag_subjectless=args.subjectless)
                f.write(json.dumps({"id": it["id"], "q": qid, "p": pid, "label": label, "split": split,
                                    "fold": event_fold(it["event"]) if split == "dev" else -1, **w},
                                   ensure_ascii=False) + "\n")
                n += 1
    print(json.dumps({"examples": n}))


if __name__ == "__main__":
    main()
