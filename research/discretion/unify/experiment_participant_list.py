"""Conservative coordination-list participant-count proposals, train/valid only.

This creates source-bound mention slots and provisional participation edges. It
does not equate identical redacted surface strings with the same real person.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from experiment_age_count_closure import count_candidates, evidence_contains
from minimal_amount_closure import event_ids, load_records

MASKED = re.compile(r"[\u4e00-\u9fff]{1,2}(?:[xX]{1,2}|\*{1,2})")
PLAIN = re.compile(r"[\u4e00-\u9fff]{2,3}")
SEP = re.compile(r"[、]")
CLAUSE_END = re.compile(r"[，,。；;：:\n]")
PARTICIPATION = re.compile(r"参赌|赌博|打麻将|打牌|被查获|抓获")
UNCERTAIN_SUFFIX = re.compile(r"^(?:等|及其他|等人|等[\u4e00-\u9fff0-9])")
LEADING_CONJUNCTION = re.compile(r"(?:伙同|与|同|和|及)$")
NON_NAME_PREFIX = "与同和及村镇县市"


def token_at_start(text: str, start: int) -> tuple[int, int, str] | None:
    # A masked name must win over the shorter all-CJK prefix.
    for pattern in (MASKED, PLAIN):
        match = pattern.match(text, start)
        if match:
            return match.start(), match.end(), match.group()
    return None


def token_at_end(text: str, end: int) -> tuple[int, int, str] | None:
    low = max(0, end - 12)
    found = [m for pattern in (MASKED, PLAIN) for m in pattern.finditer(text, low, end)
             if m.end() == end]
    if not found:
        return None
    match = max(found, key=lambda m: (m.end() - m.start(), bool(MASKED.fullmatch(m.group()))))
    start, raw = match.start(), match.group()
    if MASKED.fullmatch(raw) and len(raw) >= 3 and raw[0] in NON_NAME_PREFIX:
        start += 1
        raw = raw[1:]
    return start, match.end(), raw


def first_slots(text: str, first_separator: int) -> list[tuple[int, int, str]]:
    last = token_at_end(text, first_separator)
    if last is None:
        return []
    prior = text[:last[0]]
    conjunction = LEADING_CONJUNCTION.search(prior)
    if conjunction is None:
        return [last]
    lead = token_at_end(text, conjunction.start())
    if lead is None:
        return [last]
    return [lead, last]


def candidate_lists(packet: dict, target: str, aliases: list[str] | tuple[str, ...] = ()) -> list[dict]:
    results = []
    source = packet["source"]["text_sha256"]
    for view in packet["visible_spans"]:
        if view["zone"] != "facts":
            continue
        text = view["quote"]
        seps = [m.start() for m in SEP.finditer(text)]
        i = 0
        while i < len(seps):
            run = [seps[i]]
            j = i + 1
            while j < len(seps) and seps[j] - run[-1] <= 12 and not CLAUSE_END.search(
                    text[run[-1] + 1:seps[j]]):
                run.append(seps[j])
                j += 1
            i = j
            if not run:
                continue
            initial = first_slots(text, run[0])
            if not initial:
                continue
            slots = initial
            valid = True
            for left, right in zip(run, run[1:]):
                tok = token_at_start(text, left + 1)
                if tok is None or tok[1] != right:
                    valid = False
                    break
                slots.append(tok)
            last = token_at_start(text, run[-1] + 1)
            if last is None:
                valid = False
            else:
                slots.append(last)
            if not valid or len(slots) < 2:
                continue
            surfaces = [x[2] for x in slots]
            if not any(name in surfaces for name in {target, *aliases}):
                continue
            tail = text[slots[-1][1]:]
            clause_end = CLAUSE_END.search(tail)
            tail = tail[:clause_end.start()] if clause_end else tail
            if UNCERTAIN_SUFFIX.match(tail) or len(tail) > 90:
                continue
            trigger = PARTICIPATION.search(tail)
            if trigger is None:
                continue
            abs_slots = [{"mention_id": "PL-" + hashlib.sha256(
                              f"{source}|{view['start'] + a}|{view['start'] + b}|{k}".encode()).hexdigest()[:16],
                          "raw": raw, "start": view["start"] + a, "end": view["start"] + b,
                          "source_span_id": view["span_id"], "slot_index": k}
                         for k, (a, b, raw) in enumerate(slots)]
            event_start = view["start"] + slots[0][0]
            event_end = view["start"] + slots[-1][1] + trigger.end()
            event_id = "LE-" + hashlib.sha256(
                f"{source}|{event_start}|{event_end}".encode()).hexdigest()[:16]
            results.append({"candidate_id": "LC-" + hashlib.sha256(
                                f"{source}|{event_start}|{slots[-1][1] + view['start']}".encode()).hexdigest()[:16],
                            "value": len(abs_slots), "source_span_id": view["span_id"],
                            "start": event_start, "end": event_end,
                            "list_start": abs_slots[0]["start"], "list_end": abs_slots[-1]["end"],
                            "event_id": event_id, "trigger": trigger.group(),
                            "trigger_start": view["start"] + slots[-1][1] + trigger.start(),
                            "trigger_end": view["start"] + slots[-1][1] + trigger.end(),
                            "mentions": abs_slots,
                            "participation_edges": [{"person_mention_id": m["mention_id"],
                                                     "event_id": event_id,
                                                     "relation": "participates",
                                                     "state": "provisional"} for m in abs_slots],
                            "identity_basis": "coordination_slots",
                            "masked_surface_collision": len(set(surfaces)) < len(surfaces),
                            "completeness_basis": "closed_list_with_behavior_predicate"})
    return results


def proposed_count(packet: dict, target: str, aliases: list[str] | tuple[str, ...] = ()) -> dict:
    lists = candidate_lists(packet, target, aliases)
    if not lists:
        return {"status": "abstain", "reason": "no_closed_participant_list", "list_count": 0}
    values = {x["value"] for x in lists}
    if len(values) > 1:
        return {"status": "abstain", "reason": "conflicting_lists", "list_count": len(lists),
                "possible_values": sorted(values)}
    explicit = {q["engine_projection"]["min"] for q in count_candidates(packet)
                if q.get("role_hint") == "participant_count"}
    if explicit and any(v != next(iter(values)) for v in explicit):
        return {"status": "abstain", "reason": "explicit_count_conflict", "list_count": len(lists),
                "possible_values": sorted(values), "explicit_values": sorted(explicit)}
    selected = lists[0]
    return {"status": "selected", "value": selected["value"], "route": "closed_list_count",
            "list_count": len(lists), "candidate": selected}


def run(teacher: Path, originals: Path, silver: Path) -> tuple[dict, list[dict]]:
    records = load_records(teacher, originals, silver, {"train", "valid"})
    train = [r for r in records if r[3]["metadata"]["split"] == "train"]
    valid = [r for r in records if r[3]["metadata"]["split"] == "valid"]
    if event_ids(train) & event_ids(valid):
        raise ValueError("train_valid_event_overlap")
    report = {"scope": "train_valid_only", "test_labels_used": False,
              "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs_sha256": {k: hashlib.sha256(v.read_bytes()).hexdigest()
                                for k, v in {"teacher": teacher, "originals": originals,
                                             "silver": silver}.items()}, "splits": {},
              "limitations": ["Silver field missing is not a verified negative edge",
                              "Masked repeated names are distinct list slots, not resolved person identities",
                              "Participation and list completeness edges are provisional"]}
    predictions = []
    for split in ("train", "valid"):
        stats = Counter()
        incremental_events = set()
        missing_label_events = set()
        disagreement_ids = []
        for rid, inp, packet, ref in records:
            if ref["metadata"]["split"] != split:
                continue
            item = ref["reference_elements"]["persons"]["participant_count"]
            p = proposed_count(packet, inp["target"], inp.get("aliases") or ())
            all_lists = candidate_lists(packet, inp["target"], inp.get("aliases") or ())
            views = {v["span_id"]: v for v in packet["visible_spans"]}
            for proposal in all_lists:
                view = views[proposal["source_span_id"]]
                stats["list_candidates"] += 1
                for mention in proposal["mentions"]:
                    if view["quote"][mention["start"] - view["start"]:
                                     mention["end"] - view["start"]] != mention["raw"]:
                        raise ValueError("list_mention_source_mismatch:" + rid)
                    stats["provisional_participation_edges"] += 1
                if view["quote"][proposal["trigger_start"] - view["start"]:
                                 proposal["trigger_end"] - view["start"]] != proposal["trigger"]:
                    raise ValueError("list_trigger_source_mismatch:" + rid)
            stats["records"] += 1
            positive = type(item.get("value")) is int
            explicit = positive and any(
                q["engine_projection"]["min"] == item["value"] and evidence_contains(q, item)
                for q in count_candidates(packet))
            stats["explicit_evidence_same"] += explicit
            stats["silver_positive" if positive else "silver_missing"] += 1
            if p["status"] == "selected":
                stats["selected"] += 1
                stats["matched_silver" if positive and p["value"] == item["value"] else
                      "wrong_on_positive" if positive else "output_on_silver_missing"] += 1
                list_local = evidence_contains(
                    {"start": p["candidate"]["list_start"],
                     "end": p["candidate"]["list_end"]}, item)
                if positive and not explicit and p["value"] == item["value"]:
                    stats["incremental_list_match"] += 1
                    stats["incremental_list_evidence_local_match"] += list_local
                    incremental_events.add(ref["metadata"].get("event_id") or rid)
                if not positive:
                    missing_label_events.add(ref["metadata"].get("event_id") or rid)
                    disagreement_ids.append(rid)
                if positive and p["value"] == item["value"] and not list_local:
                    stats["match_outside_silver_evidence"] += 1
            else:
                stats["abstained"] += 1
                stats["abstain_on_positive"] += positive
            stats["masked_collision_selected"] += (p["status"] == "selected" and
                                                     p["candidate"]["masked_surface_collision"])
            stats["union_candidate_coverage"] += positive and (
                explicit or p["status"] == "selected" and p["value"] == item["value"])
            stats["union_evidence_local_coverage"] += positive and (
                explicit or p["status"] == "selected" and p["value"] == item["value"]
                and evidence_contains({"start": p["candidate"]["list_start"],
                                       "end": p["candidate"]["list_end"]}, item))
            predictions.append({"id": rid, "split": split, "silver_value": item.get("value"),
                                "prediction": p})
        report["splits"][split] = {**stats, "incremental_events": len(incremental_events),
                                   "silver_missing_disagreement_events": len(missing_label_events),
                                   "silver_missing_disagreement_ids": disagreement_ids}
    return report, predictions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("teacher", "originals", "silver", "report", "predictions"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    if args.report.exists() or args.predictions.exists():
        ap.error("output_already_exists")
    report, predictions = run(args.teacher, args.originals, args.silver)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    args.predictions.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in predictions), "utf-8")
    print(json.dumps(report["splits"], ensure_ascii=False))


if __name__ == "__main__":
    main()
