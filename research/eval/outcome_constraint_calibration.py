# -*- coding: utf-8 -*-
"""方案 C 最小验证 v2：处罚结果 → 赌资区间的反推校准（development-only，不放行任何训练）。

问题：第 70 条体系下"处罚档位由赌资金额决定"（省基准分档）。反过来，
观测到的处罚结果应当给出未观测赌资的区间约束（删失信息）。本脚本量化
该反推的可靠性：在**文书写明了赌资金额**的记录上，假装金额不可见、
只按处罚结果反推区间，然后对答案（区间覆盖率）。

v2 修订（对 v1 首轮 61.6% 覆盖的 miss 归因后）：
- 中文数字金额（"四万多元"）接入 E-05 cn_to_number；
- "X赌资共计N元"改判个人语境（仅"现场/当场/查获/收缴/全场"强标记算现场）；
- 多人案件且 ≥2 个不同人名各挂金额 → ambiguous_multi_person 单列不进严格分母；
- 边界双口径：档位下限"以上"含本数（inclusive）vs 不含（exclusive）分别计覆盖；
- miss 分层：below_band（金额低于反推档 → 实践下偏/减轻信号）与 above_band
  （金额高于反推档上界 → 应更高档而判低档，或金额属他人/整场）。

口径与限制（如实）：
- 档位来源：norms/provinces/130000.yaml（河北 [200,500,1000] / onsite [500,1000,2000]，
  "或"关系取高档）、320000.yaml（江苏 personal_or_per_capita：特殊方式 [100,500,1000]、
  其他 [500,2000,5000]）。两省 YAML `verification=待核验`，本实验 development-only。
- 只用 m4-facts-silver-1740-v3-clean 的 mechanism=base 记录。
- 升档（elevate）触发词命中单列不进严格分母；2026-01 起新法期间单列。
- 真值 = facts_text 赌资语境金额；江苏核 personal+percap，河北核 personal/onsite 双档。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from normalization_spec import cn_to_number  # noqa: E402  E-05 复用

BANDS = {
    "河北": {"personal": [200, 500, 1000], "onsite": [500, 1000, 2000], "or_relation": True},
    "江苏": {"special": [100, 500, 1000], "other": [500, 2000, 5000], "or_relation": False},
}
TIER_BY_TYPE = {"罚款": 1, "拘留": 2, "拘留并处罚款": 3}

SPECIAL_METHOD = re.compile(r"网络赌博|赌博机|六合彩|私彩|赌场|聚众|网上|互联网|手机|软件|[Aa][Pp][Pp]|平台投注")
ELEVATE_HEBEI = re.compile(r"互联网|移动终端|网络赌博|网上投注|工作场所|公共场所|公共交通工具|国家工作人员|公务员")
ELEVATE_JIANGSU = re.compile(r"国家工作人员|公务员")
PRIOR_HINT = re.compile(r"曾因|曾被(行政处罚|治安)|再次|又实施|一年内")

STRONG_ONSITE = re.compile(r"现场|当场|查获|收缴|缴获|全场|屋内|桌上|台面")
PERCAP_CTX = re.compile(r"人均|每人|各(带|持|投|下)")
STAKE_CTX = re.compile(r"赌资|赌本|投注|下注|输赢|赢取|赌债|筹码")
PERSON_TOKEN = re.compile(r"[\u4e00-\u9fa5]{1,2}(?:xx|XX|\*{1,3}|某{1,2})")
PERSON_NEAR = re.compile(r"[\u4e00-\u9fa5]{1,3}(?:xx|XX|\*{1,3}|某{1,2})?[^。；\n]{0,4}(?:被|的)?(?:当场)?(?:缴获|收缴|查获|扣押|携带|带|自有)?[^。；\n]{0,4}赌资$")
AMOUNT_AR = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:余)?元|人民币\s*([\d,]+(?:\.\d+)?)")
AMOUNT_CN = re.compile(r"([零一二两三四五六七八九十百千万亿]{2,6})\s*(?:余|多)?元")


def _num(arabic: str) -> float | None:
    try:
        return float(arabic.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_stake_amounts(facts: str) -> dict:
    out = {"personal": [], "onsite": [], "percap": [], "unknown": []}
    spans = []
    for m in AMOUNT_AR.finditer(facts):
        v = _num(m.group(1) or m.group(2))
        if v and v > 0:
            spans.append((m.start(), m.end(), v))
    for m in AMOUNT_CN.finditer(facts):
        v = cn_to_number(m.group(1))
        if v and v > 0 and not any(abs(m.start() - s) < 6 for s, _, _ in spans):
            spans.append((m.start(), m.end(), float(v)))
    for st, en, val in spans:
        pre = facts[max(0, st - 25):st]
        ctx = pre + facts[st:min(len(facts), en + 10)]
        if not STAKE_CTX.search(ctx):
            continue
        # 人名紧邻"赌资"（12字内）的份额是个人语境，即使带"当场/收缴"字样
        person_adjacent = bool(re.search(r"赌资|赌本|共计$", pre[-4:])) and bool(PERSON_TOKEN.search(pre[-12:]))
        if PERCAP_CTX.search(ctx):
            out["percap"].append(val)
        elif person_adjacent:
            out["personal"].append(val)
        elif STRONG_ONSITE.search(ctx):
            out["onsite"].append(val)
        else:
            out["personal"].append(val)  # 含"X赌资共计N元"型个人累计
    return out


def _band_hit(vals, lo, hi_incl, exclusive: bool) -> bool:
    for v in vals:
        if (v > lo if exclusive else v >= lo) and (hi_incl is None or v < hi_incl):
            return True
    return False


def classify(cands, lo, hi, exclusive: bool) -> str:
    if not cands:
        return "skip_no_amount"
    if _band_hit(cands, lo, hi, exclusive):
        return "covered"
    if all(v < (lo if not exclusive else lo) for v in cands):
        return "miss_below_band"   # 实践下偏/减轻信号
    return "miss_above_band"       # 应更高档判低档，或金额属他人/整场


def person_ambiguity(facts: str, amts: dict) -> bool:
    persons = set(PERSON_TOKEN.findall(facts))
    if len(persons) < 2:
        return False
    # ≥2 个不同人名各挂金额：粗略判据=个人语境金额 ≥2 个不同值
    return len(set(amts["personal"])) >= 2


def resolve_regions(train: list, lake_db: Path) -> dict:
    db = sqlite3.connect(str(lake_db))
    cur = db.cursor()
    auth2rc = {}
    for a, rc in cur.execute("select authority, region_code from documents where authority is not null and region_code != ''"):
        auth2rc.setdefault(a, Counter())[rc[:2]] += 1
    d2rc = {d: rc for d, rc in cur.execute("select doc_id, region_code from documents") if rc}
    ev2rc = {}
    for eid, docid in cur.execute("select event_id, doc_id from records where event_id is not null"):
        if d2rc.get(docid):
            ev2rc.setdefault(eid, Counter())[d2rc[docid][:2]] += 1
    db.close()
    JS_CITIES = ("无锡", "盱眙", "高邮", "如皋", "靖江", "江北新区", "溧阳", "宜兴", "江阴", "张家港",
                 "太仓", "常熟", "昆山", "吴江", "南京", "苏州", "常州", "南通", "徐州", "扬州",
                 "盐城", "淮安", "连云港", "宿迁", "泰州", "镇江", "东海", "赣榆")
    CODE2PROV = {"13": "河北", "32": "江苏"}
    regions = {}
    for r in train:
        org = r["event_id"].split("|")[0]
        code = None
        if org in auth2rc:
            code = auth2rc[org].most_common(1)[0][0]
        else:
            for a, c in auth2rc.items():
                if a and (a in org or org in a):
                    code = c.most_common(1)[0][0]
                    break
        if code is None:
            cnt = ev2rc.get(r["event_id"])
            if cnt and len(cnt) == 1:
                code = next(iter(cnt))
        if code is None and any(c in org for c in JS_CITIES):
            code = "32"
        regions[r["id"]] = CODE2PROV.get(code)
    return regions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default=r"D:/02_Dev/Data/justilaw-research/engine/training/m4-facts-silver-1740-v3-clean-20261026")
    ap.add_argument("--lake-db", default=r"D:/02_Dev/Data/justilaw-research/lake/catalog/lake.db")
    ap.add_argument("--out", default=r"D:/02_Dev/Data/justilaw-research/engine/development/outcome-constraint-calib-20261026")
    a = ap.parse_args()
    pkg, out = Path(a.package), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    train = [json.loads(l) for l in (pkg / "train.jsonl").open(encoding="utf-8")]
    regions = resolve_regions(train, Path(a.lake_db))

    stats = Counter()
    cov = {"inclusive": Counter(), "exclusive": Counter()}
    strat = {"inclusive": defaultdict(Counter), "exclusive": defaultdict(Counter)}
    misses, weak = [], []
    for r in train:
        prov = regions.get(r["id"])
        if prov not in BANDS:
            stats["out_of_scope_province"] += 1
            continue
        stats[f"in_scope_{prov}"] += 1
        if r["metadata"].get("mechanism") != "base":
            stats["skip_mechanism"] += 1
            continue
        t = r["target"]["type"]
        if t not in TIER_BY_TYPE:
            stats["skip_type"] += 1
            continue
        tier = TIER_BY_TYPE[t]
        facts = r["input"]["facts_text"]
        mdate = re.search(r"(\d{4})年(\d{1,2})月", r["event_id"].split("|")[1] if "|" in r["event_id"] else "")
        if mdate and (int(mdate.group(1)), int(mdate.group(2))) >= (2026, 1):
            stats["skip_new_law_2026"] += 1
            continue
        if (ELEVATE_HEBEI if prov == "河北" else ELEVATE_JIANGSU).search(facts):
            stats["elevated_excluded"] += 1
            continue
        prior = bool(PRIOR_HINT.search(facts))
        amts = extract_stake_amounts(facts)
        if person_ambiguity(facts, amts):
            stats["skip_ambiguous_multi_person"] += 1
            continue
        special = bool(SPECIAL_METHOD.search(facts))
        if prov == "江苏":
            bounds = BANDS["江苏"]["special"] if special else BANDS["江苏"]["other"]
            lo, hi = bounds[tier - 1], (bounds[tier] if tier < 3 else None)
            cands = amts["personal"] + amts["percap"]
            field = "personal_or_per_capita_stake"
        else:
            p, o = BANDS["河北"]["personal"], BANDS["河北"]["onsite"]
            lo, hi = p[tier - 1], (p[tier] if tier < 3 else None)
            olo, ohi = o[tier - 1], (o[tier] if tier < 3 else None)
            cands = amts["personal"]
            field = "personal_stake_OR_onsite"
        if not cands and not amts["onsite"] and not amts["unknown"]:
            stats["no_visible_amount"] += 1
            w = {"id": r["id"], "province": prov, "tier": tier, "field": field,
                 "min": lo, "max": hi, "prior_hint": prior,
                 "label_provenance": "outcome-constraint", "release_approved": False}
            if prov == "河北":
                w.update({"onsite_min": olo, "onsite_max": ohi})
            weak.append(w)
            continue
        for mode in ("inclusive", "exclusive"):
            ex = mode == "exclusive"
            if prov == "江苏":
                res = classify(cands or amts["unknown"], lo, hi, ex)
            else:
                res_p = classify(cands, lo, hi, ex) if cands else "skip_no_amount"
                res_o = classify(amts["onsite"], olo, ohi, ex) if amts["onsite"] else "skip_no_amount"
                # 多人场景：各人份额之和 ≈ 一场赌资总额（河北"或"关系的整场口径）
                all_amts = cands + amts["onsite"]
                res_t = classify([sum(all_amts)], olo, ohi, ex) if len(all_amts) >= 2 else "skip_no_amount"
                if "covered" in (res_p, res_o, res_t):
                    res = "covered"
                else:
                    non_skip = [x for x in (res_p, res_o, res_t) if x != "skip_no_amount"]
                    res = non_skip[0] if non_skip else "skip_no_amount"
                    # below 优先于 above（下偏信号更保守）
                    if "miss_below_band" in non_skip and "miss_above_band" in non_skip:
                        res = "miss_mixed_unit"
                if res == "skip_no_amount" and amts["unknown"]:
                    res = classify(amts["unknown"], lo, hi, ex)
            cov[mode][res] += 1
            key = f"{prov}|tier{tier}" + (("|special" if special else "|other") if prov == "江苏" else "")
            strat[mode][key][res] += 1
            if res.startswith("miss") and mode == "inclusive" and len(misses) < 80:
                mitigate = bool(re.search(r"投案|自首|如实|供认|认错认罚|主动交代", facts))
                misses.append({"id": r["id"], "province": prov, "tier": tier, "type": t,
                               "res": res, "amounts": {k: v for k, v in amts.items() if v},
                               "prior_hint": prior, "mitigate_hint": mitigate,
                               "facts_head": facts[:200]})

    def rate(c):
        n = c["covered"] + c["miss_below_band"] + c["miss_above_band"] + c["miss_mixed_unit"]
        return round(c["covered"] / n, 4) if n else None

    report = {
        "experiment": "outcome-constraint-calibration-v2",
        "status": "development_only",
        "package": str(pkg),
        "package_train_sha256": hashlib.sha256((pkg / "train.jsonl").read_bytes()).hexdigest(),
        "records_train": len(train),
        "in_scope": {p: stats[f"in_scope_{p}"] for p in BANDS},
        "exclusions": {k: stats[k] for k in ("skip_mechanism", "skip_type", "skip_new_law_2026",
                                             "elevated_excluded", "skip_ambiguous_multi_person",
                                             "out_of_scope_province")},
        "no_visible_amount_weak_labels": len(weak),
        "coverage": {m: {**dict(cov[m]), "rate": rate(cov[m])} for m in ("inclusive", "exclusive")},
        "by_stratum": {m: {"|".join(map(str, (k,))): dict(v) for k, v in strat[m].items()} for m in ("inclusive", "exclusive")},
        "verdict_rule": "rate>=0.90 informative; 0.75-0.90 usable-with-flags; <0.75 unreliable",
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "weak_stake_intervals.jsonl").open("w", encoding="utf-8") as f:
        for w in weak:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")
    with (out / "misses.jsonl").open("w", encoding="utf-8") as f:
        for m in misses:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("in_scope", "exclusions", "no_visible_amount_weak_labels", "coverage")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
