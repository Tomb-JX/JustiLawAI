"""Four-field blind review: build tasks, validate answers, merge two passes, score service runs.

Covers personal stake, onsite total, participant count and age, including "absent".
Tasks show only the visible facts/meta text, the target and amount candidates; no
method output or model vote is ever written into a task. Values are compared as keys:
amounts by normalized value, counts as integers, age as completed years at the
behavior date computed here from the reviewer's date operands (never the reviewer's
arithmetic). Reviews are Claude reviews (two independent passes + adjudication by a
separate reviewer), not human gold.

`build`    : batch inputs.jsonl -> tasks/, shards/, MANIFEST.json
`validate` : one pass directory -> problems list (format, ids, evidence verbatim)
`merge`    : pass1 + pass2 -> AGREED.json + ADJUDICATE.json (counts only on stdout)
`score`    : AGREED (+ ADJUDICATED) vs one or more binding-service output files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import date
from pathlib import Path

from audit_supply_replay import rows
from element_contract import normalization_spec
from evaluate_relation_model_labels import amount_key
from experiment_pair_relations import view_of
from experiment_relation_edges import amounts_of
from supply_packet import build_packet

SEED = 20261027
FIELDS = ("personal_stake", "onsite_stake_total", "participant_count", "age")
SERVICE_FIELD = {"amounts.personal_stake": "personal_stake", "amounts.onsite_stake_total": "onsite_stake_total",
                 "persons.participant_count": "participant_count", "person.age": "age"}
AMOUNT_STATUS = {"selected", "absent", "missing_candidate", "uncertain"}
VALUE_STATUS = {"value", "absent", "uncertain"}

GUIDE = """你是行政赌博处罚文书的要素复核员。只依据给出的 facts/meta 原文判断，不推测原文没有的内容，不使用案外常识补全。对目标人（target）判断下面 4 个字段。
目标人的姓名在原文中可能有不同的遮蔽写法（如 周*、周x、周某、周XX），指向被处罚人本人时视为同一人；但同姓的其他遮蔽名（如另一个“周xx”与目标同时出现、分别有不同金额）可能是不同的人，要按上下文区分。原文因排版换行，一句话可能被拆成几行。

一、个人赌资 personal_stake：目标人本人在本次赌博中持有、投入、下注、携带用于赌博或赢得的钱。
- 计入：“目标持有赌资X元”“目标下注/充值/购买彩票X元”“每人各拿X元”（目标也在其中）“单人网络赌博中目标投入的赌资X元”。
- 不计入：他人的钱；现场合计；抽头、台费、场地费、获利（除非原文明确这是目标下注的赌资）；单局输赢上限、底注、番数等规则数额；罚款；历史处罚中的金额；目标作为庄家收取的他人投注款；“人均赌资”（判 uncertain）。
- 原文只说“输了X元”“赢了X元”而没有持有/投入表述时：赢得的钱计入；输掉的钱即为投入的赌资，计入。
- 目标本人没有参赌（只是组织者、提供场所或赌博机、抽头者）时判 absent，除非原文写明目标自己也下注。
二、现场总额 onsite_stake_total：本次赌博现场查获或认定的、属于全体或现场的赌资合计（如“现场查获赌资共X元”“现场赌资X元”“桌面赌资X元”“共计X元”）。
- 必须是原文直接写出的合计数。原文只分别列出各人赌资、或只给“人均赌资”而没有写合计时，判 absent，不要自己加总或推算。
- 不计入：单个人的钱（即使是唯一被提到的人）；抽头、获利；规则数额。
- 现场查获的赌资（包括赌博机内查获的现金、原文称为赌资的钱款）计入，即使查获时无人正在赌博。
- 单人网络赌博、个人购彩，原文没有“现场/查获/共计”这类合计表述时，判 absent。
- 全场或桌面“总输赢”按现场认定赌资计；点数折算出来的金额属于推算，不计。
金额字段输出 status：selected（候选中有正确值，填 candidate_id）／absent（原文确实没有该事实）／missing_candidate（原文有正确值，但候选中没有或只有拆碎的片段，raw 逐字写出原文表述）／uncertain（原文信息不足以确定）。多个候选数值相同且都正确时任选其一。

三、参赌人数 participant_count：与目标同一场次实际参与赌博的人数，**含目标本人**。
- 不计入围观、望风、执法人员、只提供场地而未参赌的人。
- “本人等四人”计 4；“本人与另外四人”计 5；“张三、李四、王五（含目标）三人赌博”计 3。
- 目标本人没有参赌（组织者、提供场所或赌博机）时，按该场次实际参赌的人数计，不把目标算进去。
- 原文只有姓名列举时，若能确定这是该场次参赌者的完整名单，按人数计；同一个人在叙述中反复被提到只算一次，但名单中不同列举位置上相同的遮蔽写法（如两个“徐某某”）视为不同的人，除非原文写明是同一人；名单写“等人”或明显不完整时判 uncertain。
- 只有“多人”“数人”“若干人”判 uncertain；单人网络赌博、个人购彩、原文完全没有同场参赌者信息时判 absent。
- 目标参加了多个场次且人数不同、无法确定时判 uncertain。
输出 status：value（填整数 value）／absent／uncertain。

四、年龄 age：只抄写操作数，不要自己计算周岁（程序计算）。
- birth_date：原文中目标人的出生日期，按原文精度写成 YYYY-MM-DD、YYYY-MM 或 YYYY；被遮蔽（如 xxxx 年 xx 月）写 null。
- behavior_date：目标本次违法行为（参赌，或组织、提供条件等）发生的日期，按原文精度写；“左右”“许”按原文日期写；行为持续一段时间（如从某日起提供赌博机直至被查获）写成“起/止”区间，如 2022-07-05/2022-07-08；没有写 null。不要用处罚决定日期代替；当场查获的日期就是行为日期。
- stated_age：原文直接写出的目标年龄（如“现年33岁”“33岁”），没有写 null。
- birth_date 和 stated_age 都没有（含出生日期被遮蔽）时 status=absent（behavior_date 仍照填）；否则 status=value；原文信息互相矛盾、无法判断是否属于目标时 status=uncertain。

每个字段写 evidence：用原文中不超过 40 字的**连续原样片段**说明依据（逐字复制，不要改写、不要加省略号）；absent 时写 null。年龄的 evidence 写出生日期所在的片段（没有则写行为日期或年龄所在片段）。
最后可在 notes 里用一句话写下拿不准的原因（没有则为空字符串）。只输出一个 JSON 对象，结构与 answer_schema 完全一致。"""

SCHEMA = {
    "personal_stake": {"status": "selected|absent|missing_candidate|uncertain", "candidate_id": None,
                       "raw": None, "evidence": "..."},
    "onsite_stake_total": {"status": "selected|absent|missing_candidate|uncertain", "candidate_id": None,
                           "raw": None, "evidence": "..."},
    "participant_count": {"status": "value|absent|uncertain", "value": None, "evidence": "..."},
    "age": {"status": "value|absent|uncertain", "birth_date": None, "behavior_date": None,
            "stated_age": None, "evidence": "..."},
    "notes": ""}

_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def _bounds(text: str) -> tuple[date, date] | None:
    """Earliest and latest day a YYYY[-MM[-DD]] value can denote."""
    m = _DATE.match(text.strip())
    if not m:
        return None
    y, mo, d = int(m[1]), m[2] and int(m[2]), m[3] and int(m[3])
    if d:
        return date(y, mo, d), date(y, mo, d)
    if mo:
        nxt = date(y + (mo == 12), mo % 12 + 1, 1)
        return date(y, mo, 1), date.fromordinal(nxt.toordinal() - 1)
    return date(y, 1, 1), date(y, 12, 31)


def _completed_years(birth: date, day: date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def age_range(birth: str | None, behavior: str | None) -> tuple[int, int] | None:
    if not birth or not behavior:
        return None
    b = _bounds(birth)
    parts = [_bounds(p) for p in behavior.split("/")]
    if b is None or not parts or any(p is None for p in parts):
        return None
    first, last = parts[0][0], parts[-1][1]
    return _completed_years(b[1], first), _completed_years(b[0], last)


def key_of(field: str, ans: dict, task: dict) -> str:
    """Comparable reference key: amount:<v> | missing:<raw> | count:<n> | age:<n> | absent | uncertain."""
    status = ans["status"]
    if field in ("personal_stake", "onsite_stake_total"):
        if status == "selected":
            cand = next(c for c in task["amount_candidates"] if c["candidate_id"] == ans["candidate_id"])
            return amount_key(cand["normalized"])
        if status == "missing_candidate":
            # A correct amount the candidate list lacked (often a wrap fragment) still has a value.
            raw = re.sub(r"[\s|]+", "", ans.get("raw") or "")
            value = normalization_spec().normalize_amount(raw if re.search(r"元|块", raw) else raw + "元")
            return amount_key(value) if value else "missing:" + raw
        return status
    if status != "value":
        return status
    if field == "participant_count":
        return f"count:{int(ans['value'])}"
    span = age_range(ans.get("birth_date"), ans.get("behavior_date"))
    if span and span[0] == span[1]:
        return f"age:{span[0]}"
    if ans.get("stated_age") is not None and span is None:
        return f"age:{int(ans['stated_age'])}"
    if not ans.get("birth_date") and ans.get("stated_age") is None:
        return "absent"  # a behavior date alone carries no age
    return "uncertain"


def age_alternative(ans: dict) -> str | None:
    """The stated age when it disagrees with the computed one (a convention case, reported apart)."""
    span = age_range(ans.get("birth_date"), ans.get("behavior_date"))
    stated = ans.get("stated_age")
    if stated is not None and span and span[0] == span[1] and int(stated) != span[0]:
        return f"age:{int(stated)}"
    return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def problems_of(ans: dict, task: dict) -> list[str]:
    out = []
    ids = {c["candidate_id"] for c in task["amount_candidates"]}
    visible = _squash("".join(v["text"] for v in task["visible_text"]))
    for f in FIELDS:
        a = ans.get(f)
        if not isinstance(a, dict):
            out.append(f"{f}:missing")
            continue
        allowed = AMOUNT_STATUS if f in ("personal_stake", "onsite_stake_total") else VALUE_STATUS
        if a.get("status") not in allowed:
            out.append(f"{f}:status")
            continue
        if f in ("personal_stake", "onsite_stake_total") and a["status"] == "selected" and a.get("candidate_id") not in ids:
            out.append(f"{f}:candidate_id")
        if f == "participant_count" and a["status"] == "value" and not isinstance(a.get("value"), int):
            out.append(f"{f}:value")
        if f == "age" and a["status"] == "value":
            for k in ("birth_date", "behavior_date"):
                v = a.get(k)
                if v is not None and any(_bounds(p) is None for p in str(v).split("/")):
                    out.append(f"age:{k}_format")
            if not any(a.get(k) is not None for k in ("birth_date", "behavior_date", "stated_age")):
                out.append("age:value_without_operands")
        ev = a.get("evidence")
        if a["status"] not in ("absent",) and ev and _squash(ev) not in visible:
            out.append(f"{f}:evidence_not_verbatim")
    return out


def task_for(rec: dict, packet: dict) -> dict:
    cands = []
    for q in amounts_of(packet):
        view = view_of(packet, q["start"])
        a = q["start"] - view["start"]
        cands.append({"candidate_id": q["candidate_id"], "raw": q["raw"], "normalized": q["engine_projection"],
                      "context": view["quote"][max(0, a - 30):a] + "【" + q["raw"] + "】" +
                      view["quote"][a + len(q["raw"]):a + len(q["raw"]) + 20]})
    return {"record_id": rec["id"], "guide": GUIDE, "answer_schema": SCHEMA, "target": rec["target"],
            "aliases": rec.get("aliases") or [], "visible_text": [{"zone": v["zone"], "text": v["quote"]}
                                                                  for v in packet["visible_spans"]],
            "amount_candidates": cands}


def build(batch: Path, out: Path, shards: int) -> None:
    records = list(rows(batch / "inputs.jsonl"))
    (out / "tasks").mkdir(parents=True, exist_ok=False)
    ids = []
    for rec in records:
        packet = build_packet(rec["text_full"], rec, record_id=rec["id"], layout_wraps=True)
        (out / "tasks" / f"{rec['id']}.json").write_text(
            json.dumps(task_for(rec, packet), ensure_ascii=False, indent=1), "utf-8")
        ids.append(rec["id"])
    random.Random(SEED).shuffle(ids)
    (out / "shards").mkdir()
    for k in range(shards):
        (out / "shards" / f"shard-{k:02d}.txt").write_text("\n".join(ids[k::shards]) + "\n", "utf-8")
    manifest = {"version": "review4-1", "batch": str(batch),
                "inputs_sha256": hashlib.sha256((batch / "inputs.jsonl").read_bytes()).hexdigest(),
                "tasks": len(ids), "shards": shards, "seed": SEED,
                "guide_sha256": hashlib.sha256(GUIDE.encode("utf-8")).hexdigest(),
                "nature": "claude_review_not_human_gold"}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


def _task(root: Path, rid: str) -> dict:
    return json.loads((root / "tasks" / f"{rid}.json").read_text("utf-8"))


def validate(root: Path, name: str) -> None:
    bad, missing = {}, []
    for tpath in sorted((root / "tasks").glob("*.json")):
        apath = root / name / tpath.name
        if not apath.exists():
            missing.append(tpath.stem)
            continue
        try:
            probs = problems_of(json.loads(apath.read_text("utf-8")), json.loads(tpath.read_text("utf-8")))
        except Exception as exc:  # noqa: BLE001 - every problem is listed
            probs = [f"{type(exc).__name__}: {exc}"]
        if probs:
            bad[tpath.stem] = probs
    print(json.dumps({"pass": name, "missing": len(missing), "with_problems": len(bad),
                      "problems": dict(Counter(p.split(":")[0] + ":" + p.split(":")[-1] for v in bad.values()
                                               for p in v)), "examples": dict(list(bad.items())[:5]),
                      "missing_ids": missing[:10]}, ensure_ascii=False))


def merge(root: Path) -> None:
    final, sheet, problems = {}, {}, []
    for tpath in sorted((root / "tasks").glob("*.json")):
        rid, task = tpath.stem, json.loads(tpath.read_text("utf-8"))
        try:
            p1, p2 = (json.loads((root / p / tpath.name).read_text("utf-8")) for p in ("pass1", "pass2"))
            for p in (p1, p2):
                if [x for x in problems_of(p, task) if not x.endswith("evidence_not_verbatim")]:
                    raise ValueError("invalid_answer")
        except Exception as exc:  # noqa: BLE001 - every problem is listed
            problems.append((rid, f"{type(exc).__name__}: {exc}"))
            continue
        final[rid] = {}
        for f in FIELDS:
            k1, k2 = key_of(f, p1[f], task), key_of(f, p2[f], task)
            if k1 == k2:
                final[rid][f] = {"key": k1, "source": "agreed", "answer": p1[f]}
            else:
                sheet.setdefault(rid, {"target": task["target"]})[f] = {
                    "pass1": p1[f] | {"key": k1}, "pass2": p2[f] | {"key": k2},
                    "notes": [p1.get("notes"), p2.get("notes")]}
    (root / "AGREED.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), "utf-8")
    (root / "ADJUDICATE.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=1), "utf-8")
    fields = sum(len(v) for v in final.values())
    disputed = sum(len(v) - 1 for v in sheet.values())
    print(json.dumps({"records": len(final), "fields_agreed": fields, "fields_to_adjudicate": disputed,
                      "agreement": round(fields / (fields + disputed), 4) if fields + disputed else None,
                      "by_field_disputed": dict(Counter(f for v in sheet.values() for f in v if f != "target")),
                      "n_problems": len(problems), "problems": problems[:5]}, ensure_ascii=False))


def final_keys(root: Path) -> dict[str, dict[str, dict]]:
    final = json.loads((root / "AGREED.json").read_text("utf-8"))
    path = root / "ADJUDICATED.json"
    for rid, fields in (json.loads(path.read_text("utf-8")) if path.exists() else {}).items():
        task = _task(root, rid)
        for f, ans in fields.items():
            final.setdefault(rid, {})[f] = {"key": key_of(f, ans, task), "source": "adjudicated", "answer": ans}
    return final


def wilson_low(k: int, n: int, z: float = 1.96) -> float:
    """Lower end of the Wilson score interval for k successes out of n."""
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return (centre - margin) / (1 + z * z / n)


def _pred_key(field: str, binding: dict) -> str | None:
    """Service output -> key; None = unresolved (to a person). An absent binding predicts 'absent'."""
    status, value = binding["binding_status"], binding.get("value")
    if status == "absent" or (status == "bound" and value is None):
        return "absent"
    if status != "bound":
        return None
    if field in ("personal_stake", "onsite_stake_total"):
        # v1 writes "amount:<v>"; v1.1 writes the structured {min, max} projection.
        return amount_key(value) if isinstance(value, dict) else str(value)
    return f"{'count' if field == 'participant_count' else 'age'}:{int(value)}"


def score(root: Path, runs: list[tuple[str, Path]], out: Path, batch: Path | None) -> None:
    final = final_keys(root)
    flags = {r["id"]: r.get("flags") or {} for r in rows(batch / "inputs.jsonl")} if batch else {}
    report = {"records": len(final), "nature": "claude_review_not_human_gold",
              "reference": {f: dict(Counter(final[r][f]["key"].split(":")[0] for r in final if f in final[r]))
                            for f in FIELDS},
              "sources": dict(Counter(v["source"] for r in final.values() for v in r.values())),
              "systems": {}}
    for name, path in runs:
        preds = {r["id"]: {SERVICE_FIELD[b["field"]]: b for b in r["bindings"]} for r in rows(path)}
        sys_block = {}
        for stratum in ("all", "multi_amount", "single_or_none"):
            rids = [r for r in final if r in preds and (stratum == "all" or
                                                        bool(flags.get(r, {}).get("multi_amount")) == (stratum == "multi_amount"))]
            block = {"records": len(rids)}
            to_person = 0
            for rid in rids:
                to_person += any(_pred_key(f, preds[rid][f]) is None for f in FIELDS)
            block["records_to_person"] = to_person
            for f in FIELDS:
                c = Counter()
                for rid in rids:
                    if f not in final[rid]:
                        continue
                    gold, pred = final[rid][f]["key"], _pred_key(f, preds[rid][f])
                    if gold == "uncertain":
                        c["ref_uncertain"] += 1
                    elif pred is None:
                        c["to_person_ref_absent" if gold == "absent" else "to_person_ref_value"] += 1
                        reason = (preds[rid][f].get("reason") or "none").split(":")[0]
                        c[f"reason:{reason}:{'ref_absent' if gold == 'absent' else 'ref_value'}"] += 1
                    elif pred == "absent":
                        c["absent_correct" if gold == "absent" else "silent_miss"] += 1
                    elif gold == "absent":
                        c["output_on_absent"] += 1
                    elif pred == gold:
                        c["correct"] += 1
                    elif f == "age" and pred == age_alternative(final[rid][f]["answer"]):
                        c["age_convention"] += 1
                    else:
                        c["wrong_value"] += 1
                auto = c["correct"] + c["wrong_value"] + c["output_on_absent"] + c["age_convention"]
                c["value_precision"] = round(c["correct"] / auto, 3) if auto else None
                c["precision_wilson_low95"] = round(wilson_low(c["correct"], auto), 3) if auto else None
                block[f] = dict(c)
            sys_block[stratum] = block
        report["systems"][name] = sys_block
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"reference": report["reference"], "sources": report["sources"]}, ensure_ascii=False))
    for name in report["systems"]:
        a = report["systems"][name]["all"]
        print(name, "records_to_person", a["records_to_person"], "/", a["records"])
        for f in FIELDS:
            print("  ", f, a[f])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("build", "validate", "merge", "score"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--batch", type=Path)
    ap.add_argument("--shards", type=int, default=8)
    ap.add_argument("--pass-name", default="pass1")
    ap.add_argument("--run", action="append", default=[], help="name=path of a binding-service output jsonl")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.stage == "build":
        build(args.batch, args.root, args.shards)
    elif args.stage == "validate":
        validate(args.root, args.pass_name)
    elif args.stage == "merge":
        merge(args.root)
    else:
        score(args.root, [(x.split("=", 1)[0], Path(x.split("=", 1)[1])) for x in args.run], args.out, args.batch)


if __name__ == "__main__":
    main()
