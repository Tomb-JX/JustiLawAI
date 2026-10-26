"""X1: how much ownership signal does parser structure carry, with no training?

On development amounts with A/B-agreed owners, a person is a structural holder
when the shortest semantic-dependency path from the amount reaches that person
through a holder role (agent / possessor / experiencer), or when SRL puts the
amount in ARG1 and the person in ARG0 of one predicate. Target holder → target;
else another holder → other; else shared. This is a probe of the signal, not a
proposed decision rule.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from experiment_joint_amount_roles import mentions_for
from experiment_ownership import owner_examples, owner_metrics
from experiment_pair_relations import ParseCache, graph_path, head_token, view_of
from experiment_relation_edges import load_batch
from ownership import owner_class

HOLDER = {"agt", "poss", "exp", "aft"}
COUNTER = {"datv", "orig", "comp"}
ARG0 = {"ARG0", "A0"}
ARG1 = {"ARG1", "A1", "ARG2", "A2"}


def person_end_role(path: list[str]) -> str | None:
    """Label on the final step into the person, if it enters as a dependent (↓)."""
    return path[-1][1:].lower().lstrip("rd") if path and path[-1].startswith("↓") else None


def structural(it: dict, q: dict, cache: ParseCache, max_len: int) -> dict:
    view = view_of(it["packet"], q["start"])
    doc = cache.get(view)
    if not doc:
        return {"status": "no_parse"}
    base = view["start"]
    qa = head_token(doc, q["start"] - base, q["end"] - base)
    found = {"sdp": Counter(), "srl": Counter()}
    reached = False
    for m in mentions_for(it["packet"], it["record"]):
        if not (base <= m["start"] and m["end"] <= base + len(view["quote"])):
            continue
        pa = head_token(doc, m["start"] - base, m["end"] - base)
        if qa is None or pa is None or doc["sent_of"][pa] != doc["sent_of"][qa]:
            continue
        who = "target" if owner_class(m["kind"]) == "target_like" else "other"
        path = graph_path(doc["sdp"], qa, pa, limit=max_len)
        if path is not None:
            reached = True
            role = person_end_role(path)
            if role in HOLDER:
                found["sdp"][who] += 1
            elif role in COUNTER:
                found["sdp"][who + "_counterparty"] += 1
        for frame in doc["srl"]:
            amount_role = next((r for r, s, e in frame["args"] if s <= qa <= e), None)
            person_role = next((r for r, s, e in frame["args"] if s <= pa <= e), None)
            if amount_role in ARG1 and person_role in ARG0:
                found["srl"][who] += 1
    return {"status": "parsed", "reached_person": reached, **found}


def decide(found: Counter) -> str:
    if found.get("target"):
        return "target"
    if found.get("other"):
        return "other"
    return "shared"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=Path, action="append", required=True)
    ap.add_argument("--cache", type=Path, action="append", required=True)
    ap.add_argument("--max-len", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    dev = [it for b in args.batch for it in load_batch(b, b / "ab" / "labels")]
    ex = owner_examples(dev)
    report = {"scope": "development owner edges (A/B agreed), no training", "examples": len(ex),
              "label_counts": dict(Counter(y for _, _, y in ex)), "toolkits": {}}
    for path in args.cache:
        cache = ParseCache(path)
        rows = [(y, structural(it, q, cache, args.max_len)) for it, q, y in ex]
        parsed = [(y, s) for y, s in rows if s["status"] == "parsed"]
        out = {"parsed": len(parsed), "reached_any_person": sum(s["reached_person"] for _, s in parsed)}
        for layer in ("sdp", "srl"):
            out[layer] = owner_metrics([(y, decide(s[layer])) for y, s in parsed])
            # Signal coverage: amounts where the layer names any holder at all, and its precision there.
            named = [(y, decide(s[layer])) for y, s in parsed if s[layer].get("target") or s[layer].get("other")]
            out[layer]["holder_named"] = len(named)
            out[layer]["accuracy_when_named"] = round(sum(y == p for y, p in named) / max(1, len(named)), 3)
        report["toolkits"][path.stem] = out
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for name, t in report["toolkits"].items():
        print(name, {k: t[k] for k in ("parsed", "reached_any_person")},
              {layer: {k: t[layer][k] for k in ("accuracy", "macro_f1", "holder_named", "accuracy_when_named")}
                       | {"other": t[layer]["other"]} for layer in ("sdp", "srl")})


if __name__ == "__main__":
    main()
