"""Agreement and frozen-chain evaluation on model-draft relation labels.

A/B (and optional blind C) drafts vote per field on (status, value); only a
strict majority becomes the consensus reference. Consensus is model-draft, not
human gold. The holdout split is reported only as aggregates: no per-record
rows leave this script for it, so it stays usable for a later frozen test.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import experiment_age_count_closure as age_count
import minimal_amount_closure as amount_closure
from audit_supply_replay import rows
from experiment_age_derivation import birth_interval, completed_age
from experiment_participant_list import candidate_lists
from supply_packet import build_packet

FIELDS = ("personal_stake", "onsite_stake_total", "participant_count", "age")
CHAIN = {"personal_stake": "amounts.personal_stake", "onsite_stake_total": "amounts.onsite_stake_total",
         "participant_count": "persons.participant_count", "age": "person.age"}
SCORED = {"selected", "absent"}


def frozen_predictions(records: list[dict], amount_artifact: Path, age_artifact: Path,
                       engine_root: Path) -> dict[str, dict]:
    """Apply the frozen 203-silver chain unchanged to fresh events (no refit, no threshold change)."""
    amounts = json.loads(amount_artifact.read_text("utf-8"))
    ages = json.loads(age_artifact.read_text("utf-8"))
    bind = amount_closure.bind_import(engine_root)
    out = {}
    for record in records:
        rid = record["id"]
        packet = build_packet(record["text_full"], record, record_id=rid)
        fields = amount_closure.predict_record(rid, record, packet, amounts, bind)["fields"]
        fields.update(age_count.predict_record(rid, record, packet, ages)["fields"])
        out[rid] = fields
    return out


def plain(value) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def amount_key(value) -> str | None:
    # A point amount {min: x, max: x} and a bare x are the same reference value.
    if isinstance(value, dict) and value.get("min") is not None:
        lo, hi = plain(value["min"]), value.get("max")
        # A missing upper bound is an open interval, not an exact point amount.
        return "amount:" + lo + ("+" if hi is None else "" if plain(hi) == lo else "-" + plain(hi))
    if isinstance(value, (int, float, str)) and str(value).strip():
        return "amount:" + plain(value)
    return None


def int_key(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("min") if value.get("exact", True) else None
    return "int:" + str(int(value)) if type(value) in (int, float) else None


def derived_ages(birth: dict, event: dict) -> set[int]:
    interval = birth_interval(birth)
    day = (event.get("engine_projection") or {}).get("date")
    if interval is None or not day:
        return set()
    when = date.fromisoformat(day)
    lo, hi = completed_age(interval[1], when), completed_age(interval[0], when)
    return set(range(lo, hi + 1)) if 0 <= lo <= hi <= 130 else set()


def model_value(field: str, item: dict, quantities: dict, lists: dict) -> tuple[str, str | None]:
    """(status, value_key); a selection whose value cannot be recomputed is 'uncertain'."""
    status = item["status"]
    if status != "selected":
        return status, None
    cid = item.get("candidate_id")
    if field in {"personal_stake", "onsite_stake_total"}:
        key = amount_key(quantities[cid].get("engine_projection"))
    elif field == "participant_count":
        key = (int_key(lists[cid]["value"]) if cid in lists else
               int_key(quantities[cid].get("engine_projection")))
    elif cid in quantities and quantities[cid]["type"] == "age":
        key = int_key(quantities[cid].get("engine_projection"))
    else:
        ages = derived_ages(quantities[item["birth_candidate_id"]], quantities[item["event_date_candidate_id"]])
        key = "int:" + str(next(iter(ages))) if len(ages) == 1 else None
    return ("selected", key) if key else ("uncertain", None)


def chain_value(field: str, output: dict) -> str | None:
    if output["status"] != "selected":
        return None
    return amount_key(output.get("value")) if field in {"personal_stake", "onsite_stake_total"} else int_key(
        output.get("value"))


def vote(votes: list[tuple[str, str | None]]) -> tuple[str, str | None] | None:
    top, n = Counter(votes).most_common(1)[0]
    return top if n * 2 > len(votes) else None


def kappa(pairs: list[tuple]) -> float | None:
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / len(pairs) ** 2
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)


def score(rows_: list[dict]) -> dict:
    c = Counter()
    for r in rows_:
        ref, pred = r["consensus"], r["chain"]
        if ref is None or ref[0] not in SCORED:
            c["no_scorable_consensus"] += 1
            continue
        c["scored"] += 1
        if ref[0] == "selected":
            c["consensus_positive"] += 1
            if r.get("age_definition_conflict"):
                # Stated age vs completed age at the act date: a contract question, not a binding error.
                c["age_definition_conflict"] += 1
                continue
            c["tp" if pred == ref[1] else "abstain_on_positive" if pred is None else "wrong_value"] += 1
        else:
            c["tn" if pred is None else "output_on_absent"] += 1
    fp = c["wrong_value"] + c["output_on_absent"]
    fn = c["wrong_value"] + c["abstain_on_positive"]
    c["precision"] = round(c["tp"] / (c["tp"] + fp), 3) if c["tp"] + fp else None
    c["recall"] = round(c["tp"] / (c["tp"] + fn), 3) if c["tp"] + fn else None
    return dict(c)


def edge_agreement(a: dict, b: dict) -> dict:
    c = Counter()
    left = {e["candidate_id"]: e for e in a["candidate_edges"]}
    for e in b["candidate_edges"]:
        x = left[e["candidate_id"]]
        c["candidates"] += 1
        c["decision_agree"] += x["decision"] == e["decision"]
        if x["decision"] == e["decision"] == "asserted":
            c["both_asserted"] += 1
            c["roles_exact"] += set(x["roles"]) == set(e["roles"])
            c["owner_agree"] += x["owner"] == e["owner"]
            c["roles_and_owner"] += set(x["roles"]) == set(e["roles"]) and x["owner"] == e["owner"]
    lists = {e["list_candidate_id"]: e for e in a["list_edges"]}
    for e in b["list_edges"]:
        x = lists[e["list_candidate_id"]]
        c["lists"] += 1
        c["list_all_agree"] += all(x[k] == e[k] for k in ("complete", "distinct_people", "target_participates"))
    return c


def evaluate(batch: Path, labels: Path, providers: list[str], arbiter: str | None,
             amount_artifact: Path, age_artifact: Path, engine_root: Path) -> tuple[dict, list[dict]]:
    records = list(rows(batch / "inputs.jsonl"))
    chain = frozen_predictions(records, amount_artifact, age_artifact, engine_root)
    report = {"label_provenance": "model_draft_majority", "human_gold": False,
              "voters": providers, "arbiter": arbiter, "fields": {}, "edges": {}, "coverage": Counter()}
    per_record, field_rows = [], {f: [] for f in FIELDS}
    edge_totals = Counter()
    for record in records:
        rid = record["id"]
        packet = build_packet(record["text_full"], record, record_id=rid)
        quantities = {q["candidate_id"]: q for q in packet["quantities"]}
        lists = {l["candidate_id"]: l for l in candidate_lists(packet, record["target"], record["aliases"])}
        drafts = {}
        for name in providers + ([arbiter] if arbiter else []):
            path = labels / f"{rid}-{name}.json"
            if path.exists():
                drafts[name] = json.loads(path.read_text("utf-8"))["annotation"]
        if not all(p in drafts for p in providers):
            report["coverage"]["missing_ab"] += 1
            continue
        report["coverage"]["ab_complete"] += 1
        edge_totals.update(edge_agreement(drafts[providers[0]], drafts[providers[1]]))
        row = {"id": rid, "split": record["split"], "group": record["selection_group"],
               "flags": record["flags"], "fields": {}}
        for field in FIELDS:
            values = {n: model_value(field, d["fields"][field], quantities, lists) for n, d in drafts.items()}
            ab = [values[p] for p in providers]
            agreed = ab[0] == ab[1]
            consensus = ab[0] if agreed else (vote(list(values.values())) if arbiter in values else None)
            output = chain[rid][CHAIN[field]]
            pred = chain_value(field, output)
            stated_age = [d["fields"]["age"].get("candidate_id") for d in drafts.values()] if field == "age" else []
            item_conflict = bool(field == "age" and consensus and consensus[0] == "selected" and pred
                                 and output.get("route") == "date_interval_derivation"
                                 and abs(int(pred[4:]) - int(consensus[1][4:])) == 1
                                 and any(c in quantities and quantities[c]["type"] == "age" for c in stated_age))
            item = {"split": record["split"], "group": record["selection_group"], "ab_agree": agreed,
                    "age_definition_conflict": item_conflict,
                    "needs_arbiter": not agreed, "arbitrated": not agreed and arbiter in values,
                    "consensus": consensus, "chain": pred, "votes": values}
            field_rows[field].append(item)
            row["fields"][field] = {k: item[k] for k in ("ab_agree", "consensus", "chain", "votes",
                                                             "age_definition_conflict")}
        per_record.append(row)
    for field, items in field_rows.items():
        status_pairs = [(i["votes"][providers[0]][0], i["votes"][providers[1]][0]) for i in items]
        report["fields"][field] = {
            "records": len(items), "ab_exact_agree": sum(i["ab_agree"] for i in items),
            "ab_status_kappa": kappa(status_pairs),
            "needs_arbiter": sum(i["needs_arbiter"] for i in items),
            "arbitrated": sum(i["arbitrated"] for i in items),
            "unresolved": sum(i["consensus"] is None for i in items),
            "consensus_status": dict(Counter(i["consensus"][0] for i in items if i["consensus"])),
            "chain_vs_consensus": {
                "all": score(items),
                **{f"split:{s}": score([i for i in items if i["split"] == s])
                   for s in ("train", "calibration", "model_draft_holdout")},
                **{f"group:{g}": score([i for i in items if i["group"] == g]) for g in ("challenge", "random")}}}
    report["edges"] = dict(edge_totals)
    report["coverage"] = dict(report["coverage"])
    # The holdout contributes aggregates only; its per-record rows stay sealed.
    visible = [r for r in per_record if r["split"] != "model_draft_holdout"]
    report["disagreement_ids"] = sorted({r["id"] for r in per_record
                                        if not all(x["ab_agree"] for x in r["fields"].values())})
    return report, visible


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("batch", "labels", "amount_artifact", "age_artifact", "engine_root", "report", "records"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--arbiter", default=None)
    args = ap.parse_args()
    report, visible = evaluate(args.batch, args.labels, args.providers.split(","), args.arbiter,
                               args.amount_artifact, args.age_artifact, args.engine_root)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    args.records.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in visible), "utf-8")
    print(json.dumps({f: {k: v for k, v in x.items() if k != "chain_vs_consensus"} | {
        "chain_all": x["chain_vs_consensus"]["all"]} for f, x in report["fields"].items()},
        ensure_ascii=False))


if __name__ == "__main__":
    main()
