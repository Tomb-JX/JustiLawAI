"""Blind review set for the two amount fields on the H3 holdout.

Selects H3 records where the frozen chain, softmax/semantic and
softmax/semantic_pair disagree with each other or with the model-vote reference,
plus a seeded random sample of all-agree records (to estimate reference error).
Each task shows only the visible text, the target and the amount candidates;
method outputs and model-vote references go to a private key file and never
into the task. Reviews are Claude reviews, not human gold.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import experiment_pair_integration as integ
from evaluate_relation_model_labels import amount_key, frozen_predictions
from experiment_joint_amount_roles import FIELDS, HOLDOUT, Variant, decide, pick_threshold
from experiment_pair_relations import load_pairs, view_of
from experiment_relation_edges import amounts_of, chain_decisions, load_batch
from experiment_selective_binding import event_fold

SEED = 20261027
GUIDE = """你是行政赌博处罚文书的要素复核员。只依据给出的 facts/meta 原文判断，不推测原文没有的内容。对目标人（target）判断两个字段，并从给定金额候选中选出正确的一项。

个人赌资 personal_stake：目标人本人在本次赌博中持有、投入、下注、携带用于赌博或赢得的钱。
- 计入：“目标持有赌资X元”“目标下注/充值/购买彩票X元”“每人各拿X元”（目标也在其中）“单人网络赌博中目标投入的赌资X元”。
- 不计入：他人的钱；现场合计；抽头、台费、获利（除非原文明确这是目标下注的赌资）；单局输赢上限、底注、番数等规则数额；罚款；历史处罚中的金额；目标作为庄家收取的他人投注款。
现场总额 onsite_stake_total：本次赌博现场查获或认定的、属于全体或现场的赌资合计（如“现场查获赌资共X元”“现场赌资X元”“共计X元”）。
- 不计入：单个人的钱（即使是唯一被提到的人）；抽头、获利；单局上限等规则数额；他人或目标的个人赌资之和以外的推算值。
- 单人网络赌博、个人购彩，原文没有“现场/查获/共计”这类合计表述时，现场总额判 absent。

对每个字段输出：
- status：selected（候选中有正确值）／absent（原文确实没有该字段的事实）／missing_candidate（原文有正确值，但候选列表中没有或只有拆碎的片段）／uncertain（原文信息不足以确定）。
- candidate_id：status=selected 时填一个候选 id，否则 null。若多个候选数值相同且都正确，任选其一。
- raw：status=missing_candidate 时逐字写出原文中的正确金额表述，否则 null。
- evidence：用原文中不超过 40 字的连续片段说明理由；absent 时写 null。
最后可在 notes 里用一句话写下拿不准的原因（没有则为空字符串）。"""

SCHEMA = {"personal_stake": {"status": "...", "candidate_id": None, "raw": None, "evidence": "..."},
          "onsite_stake_total": {"status": "...", "candidate_id": None, "raw": None, "evidence": "..."},
          "notes": ""}


def method_decisions(dev: list[dict], test: list[dict], chain: dict) -> dict[str, dict[str, dict]]:
    """name -> field -> rid -> value key (None = abstain). Frozen exactly as in the integration run."""
    out = {"frozen_chain": {f: chain_decisions(test, chain, f) for f in FIELDS}}
    for name in ("softmax/semantic", "softmax/semantic_pair"):
        v = Variant(*name.split("/"))
        oof = {}
        for k in range(5):
            train = [i for i in dev if event_fold(i["event"]) != k]
            held = [i for i in dev if event_fold(i["event"]) == k]
            oof.update(v.predict(held, v.fit(train)))
        model = v.fit(dev)
        thresholds = {f: pick_threshold(dev, f, oof) for f in FIELDS}
        preds = v.predict(test, model)
        out[name] = {f: decide(preds, f, thresholds[f]) for f in FIELDS}
    return out


def task_for(it: dict) -> dict:
    packet, record = it["packet"], it["record"]
    cands = []
    for q in amounts_of(packet):
        view = view_of(packet, q["start"])
        a = q["start"] - view["start"]
        cands.append({"candidate_id": q["candidate_id"], "raw": q["raw"], "normalized": q["engine_projection"],
                      "context": view["quote"][max(0, a - 30):a] + "【" + q["raw"] + "】" +
                      view["quote"][a + len(q["raw"]):a + len(q["raw"]) + 20]})
    return {"record_id": it["id"], "guide": GUIDE, "answer_schema": SCHEMA, "target": record["target"],
            "aliases": record["aliases"], "visible_text": [{"zone": v["zone"], "text": v["quote"]}
                                                           for v in packet["visible_spans"]],
            "amount_candidates": cands}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dev-batch", type=Path, action="append", required=True)
    for name in ("dev_pair_labels", "dev_pair_oof", "test_batch", "test_pair_labels", "test_pair_preds",
                 "amount_artifact", "age_artifact", "engine_root", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--random", type=int, default=15)
    args = ap.parse_args()
    dev = []
    for b in args.dev_batch:
        for it in load_batch(b, b / "ab" / "labels"):
            it["split"] = "train"
            dev.append(it)
    test = [dict(it, split=HOLDOUT) for it in load_batch(args.test_batch, args.test_batch / "ab" / "labels")]
    integ.summarize_pairs(integ.read_preds(args.dev_pair_oof),
                          [it for b in args.dev_batch for it in load_pairs(b, args.dev_pair_labels, "dev")])
    integ.summarize_pairs(integ.read_preds(args.test_pair_preds),
                          load_pairs(args.test_batch, args.test_pair_labels, "holdout", require_labels=False))
    chain = frozen_predictions([i["record"] for i in dev + test], args.amount_artifact, args.age_artifact,
                               args.engine_root)
    methods = method_decisions(dev, test, chain)
    keys, diff, same = {}, [], []
    for it in test:
        if not amounts_of(it["packet"]):
            continue
        row = {"methods": {m: {f: methods[m][f][it["id"]] for f in FIELDS} for m in methods},
               "model_vote": {f: it["refs"][f]["consensus"] for f in FIELDS},
               "candidates_by_key": {}}
        for q in amounts_of(it["packet"]):
            row["candidates_by_key"].setdefault(amount_key(q["engine_projection"]), []).append(q["candidate_id"])
        values = [{m: row["methods"][m][f] for m in methods} | {
            "vote": (row["model_vote"][f] or ("unresolved", None))[1]} for f in FIELDS]
        keys[it["id"]] = row
        (diff if any(len(set(v.values())) > 1 for v in values) else same).append(it)
    rng = random.Random(SEED)
    rng.shuffle(diff)
    rng.shuffle(same)
    chosen = diff[:args.max - args.random] + same[:args.random]
    tasks = args.out / "tasks"
    tasks.mkdir(parents=True, exist_ok=False)
    for it in chosen:
        (tasks / f"{it['id']}.json").write_text(json.dumps(task_for(it), ensure_ascii=False, indent=1), "utf-8")
    ids = [it["id"] for it in chosen]
    rng.shuffle(ids)
    (args.out / "ids.txt").write_text("\n".join(ids), "utf-8")
    (args.out / "PRIVATE-key.json").write_text(json.dumps(
        {"selection": {i["id"]: ("disagree" if i in diff else "random_agree") for i in chosen},
         "rows": {i["id"]: keys[i["id"]] for i in chosen}}, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"with_amounts": len(keys), "disagree_pool": len(diff), "agree_pool": len(same),
                      "chosen": len(chosen)}))


if __name__ == "__main__":
    main()
