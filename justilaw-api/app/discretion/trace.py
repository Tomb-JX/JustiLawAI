"""裁量结果的完整追踪（trace）：把引擎每一步的结论、依据原文、计算过程、数据来源与版本汇总成可展示、可存档的记录。

原则（docs/02-design/discretion-capability-layer.md §4）：
- 规则结论附条文原文；学习 / 统计结论附来源与样本规模；两者分开展示；
- 计算过程写成可读的比较句，不只给档位名；
- 要素逐项记录状态、来源与证据；
- 记录引擎、规范库、schema、数据文件的版本与哈希，可按 run_id 取回。
本模块只做汇总与格式化，不改变任何裁量结论。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path

from . import practice as rap
from .decide import QUANTITIES, Decision, band_types
from .norm_layer import Facts
from .norm_store import NORMS_DIR, NormLibrary
from .schema import SCHEMA_VERSION

ENGINE_VERSION = "de-0.2.0"

# 未知条件 / 计量字段 → 人话标签
LABELS = {
    "personal_stake": "本人赌资", "onsite_stake_total": "现场（一场）赌资合计", "personal_or_per_capita": "本人赌资或人均赌资",
    "commission": "为赌博提供条件的获利", "times": "为赌博提供条件次数", "cumulative_participants": "累计参赌人次",
    "participant_count": "参赌人数", "civil_servant": "是否国家工作人员", "venue_public": "是否在公共场所",
    "method_online": "是否网络赌博", "minors_involved": "是否涉及未成年人", "prior_within_year": "一年内是否受过治安处罚",
    "venue_public_for_profit": "是否以营利为目的在公共场所提供条件",
    "role_lender": "是否明知他人赌博而放贷", "role_lookout": "是否为赌场望风看场", "abroad_organized": "是否组织、协助他人出境赌博", "赌博方式的省级法定类别": "赌博组织形式（聚众、赌场 / 其他）",
}


def _plain(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if hasattr(v, "model_dump"):
        return v.model_dump()
    return v


def _cite(lib: NormLibrary, ref: str) -> dict:
    doc_id, _, article = ref.partition("#")
    return {"ref": ref, "text": lib.cite(doc_id, article) if article else None,
            "verified": lib.is_verified(doc_id)}


@lru_cache(maxsize=1)
def _norms_digest() -> str:
    h = hashlib.sha256()
    for p in sorted(Path(NORMS_DIR).rglob("*.yaml")):
        h.update(p.relative_to(NORMS_DIR).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


@lru_cache(maxsize=1)
def _quantities_meta() -> dict:
    q = json.loads(Path(QUANTITIES).read_text(encoding="utf-8"))
    return {"version": q.get("version"), "law_epoch": q.get("law_epoch"), "weighting": q.get("weighting"),
            "source_sha256": q.get("source_sha256"),
            "events": {f"{k}:{f}": e.get("events") for k, v in q.get("bands", {}).items() for f, e in v.items()}}


def versions(lib: NormLibrary, region: str | None) -> dict:
    prov = lib.provinces.get((region or "")[:2] + "0000") or {}
    pdoc = (prov.get("documents") or [{}])[0]
    return {
        "engine": ENGINE_VERSION, "schema": SCHEMA_VERSION,
        "norm_library_sha256": _norms_digest(),
        "laws": [{"id": law.law_id, "title": law.title} for law in lib.laws],
        "province_benchmark": ({"number": pdoc.get("number"), "title": pdoc.get("title"),
                                "verification": (pdoc.get("verification") or {}).get("status"),
                                "checked_at": (pdoc.get("verification") or {}).get("checked_at")} if prov else None),
        "band_quantities": _quantities_meta(),
        "practice_model": _practice_meta(),
    }


def _practice_meta() -> dict | None:
    m = rap.load_model()
    return {"version": m["version"], "trained": m["trained"], "training_n": m["training"]["n"],
            "training_ids_sha256": m["training"]["ids_sha256"]} if m else None


PRACTICE_PROVINCES = {"130000", "320000"}


def practice_step(facts: Facts, decision: Decision) -> dict:
    """RAP 无文本版：分布 + 逐特征贡献。范围外（省份、行为类型、新法时期）不外推。"""
    base = {"id": "practice", "title": "实务参照（学习，非法律结论）"}
    province = (facts.region or "")[:2] + "0000"
    st = decision.assessment.stake_threshold
    why = ("训练数据只覆盖河北、江苏" if province not in PRACTICE_PROVINCES else
           "训练数据只覆盖参与赌博、为赌博提供条件" if facts.behavior_type not in ("参与赌博", "为赌博提供条件") else
           "训练数据全部是旧法（2012 修正）时期，新法时期的实务分布未知" if decision.assessment.law_id != "psal-2012" else
           "省级基准在行为时尚未施行，训练数据不含此时期" if st.get("status") in ("基准未生效", "基准待核验") else None)
    if why:
        return {**base, "status": "out_of_scope", "result": None, "note": why}
    out = rap.predict(facts, band_types(st), province)
    if out is None:
        return {**base, "status": "unavailable", "result": None, "note": "实务模型参数文件缺失"}
    reading = [f"历史上与本案规则结论、要素相近的案件，最常见的处罚是「{out['predicted']}」"
               f"（{out['distribution'][out['predicted']]:.0%}）"]
    for g, v in list(out["margin_for_predicted"].items())[:3]:
        reading.append(f"{g}：使「{out['predicted']}」相对其他种类的对数几率{'提高' if v > 0 else '降低'} {abs(v):.2f}")
    return {**base, "status": "reference",
            "result": {"distribution": out["distribution"], "predicted": out["predicted"]},
            "reading": reading,
            "explanation": {k: out[k] for k in ("baseline_logits", "logits", "groups", "margin_for_predicted", "contributions")},
            "method": "多项逻辑回归（标准化特征）；对数几率 = 基线（训练集平均案件）+ Σ 系数 × 标准化特征值，逐项即贡献",
            "model": out["model"]}


def _band_step(lib: NormLibrary, facts: Facts, st: dict) -> dict:
    prov = lib.provinces.get((facts.region or "")[:2] + "0000") or {}
    clauses = (prov.get("clauses") or {}).get(facts.behavior_type) or {}
    names = (prov.get("bands") or {}).get("names") or []
    lines = []
    for c in st.get("computation") or []:
        if c["step"] == "measure" and c.get("value") is None:
            lines.append(f"{c.get('label') or LABELS.get(c['field'], c['field'])}：未知，不能按此计量定档")
        elif c["step"] == "measure":
            lo, hi = c["value"]
            val = f"{lo:g} 元" if hi == lo else (f"{lo:g} 元以上" if hi is None else f"{lo:g}–{hi:g} 元")
            for t in c["thresholds"]:
                cat = f"按「{t['label']}」门槛 " if t.get("label") else "门槛 "
                got = "、".join("未达起罚标准" if k == 0 else names[k - 1] for k in t["bands"])
                lines.append(f"{c['label']} {val}，{cat}{' / '.join(f'{b:g}' for b in t['lower_bounds'])} 元 → {got}")
        elif c["step"] == "entry_floor":
            lines.append(f"{c['text']}（{LABELS.get(c['field'], c['field'])} ≥ {c['min']:g} 元）")
        elif c["step"] == "elevate":
            lines.append(f"升档条件成立：{c['text']}"
                         + ("" if c["stake_known"] else "；但赌资不明，未达起罚标准则不予处罚，各档均保留为候选"))
    possible = st.get("observed_band_indices") or []
    return {
        "id": "band", "title": "省级基准定档",
        "status": ("unknown" if not st.get("bands") else "determined" if len(possible) == 1 else "candidates"),
        "result": st.get("bands") or [], "penalty_text": st.get("band_penalty") or [],
        "computation": lines, "computation_detail": st.get("computation") or [],
        "unknown_conditions": [{"condition": u, "label": LABELS.get(u, u)} for u in st.get("unknown_conditions") or []],
        "basis": {"document": st.get("basis"), "verified": st.get("verified"), "ref": clauses.get("ref"),
                  "clauses": [{"band": names[k - 1] if 0 < k <= len(names) else "未达起罚标准",
                               "text": clauses.get(k) or clauses.get(str(k))} for k in possible if k > 0]},
        "status_text": st.get("status"), "applicability": st.get("applicability"),
        "law_alignment": st.get("law_alignment"), "notes": st.get("notes") or [],
        "scope": st.get("scope"),
    }


def deviation(decision: Decision, proposed: dict | None, practice: dict | None = None) -> dict | None:
    if not proposed:
        return None
    a, kind = decision.assessment, proposed.get("type")
    days, fine = proposed.get("detention_days") or 0, proposed.get("fine") or 0
    in_space = kind == "不予处罚" or any(a.contains(tier, days, fine) for tier in a.tiers)
    levels = [{"level": "legal_space", "title": "法定处罚空间", "ok": in_space,
               "detail": "在法定档次与修正情节展开的选项内" if in_space else "超出法定处罚空间（须复核是否另有减轻、合并执行等依据）"}]
    if decision.candidates:
        ok = kind in decision.candidates
        levels.append({"level": "written_band", "title": "省级基准档位", "ok": ok,
                       "detail": f"基准允许：{'、'.join(decision.candidates)}" + ("" if ok else f"；拟处罚为{kind}")})
    else:
        levels.append({"level": "written_band", "title": "省级基准档位", "ok": None, "detail": "无省级分档结论，无法对照"})
    if kind in ("罚款", "拘留", "拘留并处罚款") and kind != decision.penalty_type:
        levels.append({"level": "amount_reference", "title": "档内数额参照（历史统计，非法律结论）", "ok": None,
                       "detail": "拟处罚种类与成文种类不同，不比较数额"})
    elif kind in ("罚款", "拘留", "拘留并处罚款"):
        field = "fine" if kind == "罚款" else "detention_days"
        dist = dict(decision.quantities.get(field) or [])
        x = fine if field == "fine" else days
        share = dist.get(float(x)) or dist.get(x)
        levels.append({"level": "amount_reference", "title": "档内数额参照（历史统计，非法律结论）",
                       "ok": None, "detail": f"拟处罚取值在历史分布中的占比：{share:.0%}" if share else "该取值不在历史分布常见取值中"})
    if practice and practice.get("status") == "reference":
        dist = practice["result"]["distribution"]
        rank = sorted(dist, key=dist.get, reverse=True).index(kind) + 1 if kind in dist else None
        levels.append({"level": "practice", "title": "实务参照（学习，非法律结论）", "ok": None,
                       "detail": f"相近历史案件中处「{kind}」的比例约 {dist.get(kind, 0):.0%}" + (f"，排第 {rank}" if rank else ""),
                       "probability": dist.get(kind)})
    else:
        levels.append({"level": "practice", "title": "实务参照（学习，非法律结论）", "ok": None,
                       "detail": (practice or {}).get("note") or "无实务参照"})
    return {"proposed": proposed, "levels": levels}


def missing(st: dict) -> list[dict]:
    items = []
    for c in st.get("computation") or []:
        if c["step"] == "measure" and c.get("value") is None:
            items.append({"field": c["field"], "label": LABELS.get(c["field"], c.get("label") or c["field"]),
                          "why": "省级基准按此数额定档"})
    for u in st.get("unknown_conditions") or []:
        if not any(i["field"] == u for i in items):
            items.append({"field": u, "label": LABELS.get(u, u), "why": "省级基准的升档、归类或从重条件"})
    return items


def build(lib: NormLibrary, facts: Facts, decision: Decision, provenance: dict | None = None,
          proposed: dict | None = None) -> dict:
    a = decision.assessment
    law = lib.law(a.law_id)
    elements = {}
    for name, v in vars(facts).items():
        if v is None:
            continue
        p = (provenance or {}).get(name) or {}
        elements[name] = {"value": _plain(v), "status": p.get("status", "明确"), "origin": p.get("origin", "human"),
                          "evidence": p.get("evidence") or []}
    tiers = {name: {"options": [{"kind": o.kind, "detention": _plain(o.detention), "fine": _plain(o.fine),
                                 "via": o.via, "basis": [_cite(lib, b) for b in o.basis]} for o in t.options],
                    "detention_executable": t.detention_executable, "not_executed_reason": t.not_executed_reason}
             for name, t in a.tiers.items()}
    st = a.stake_threshold
    steps = [
        {"id": "law", "title": "适用法律", "status": "determined", "result": {"id": law.law_id, "title": law.title},
         "reasoning": a.temporal_note},
        {"id": "legal_space", "title": "法定处罚空间", "status": "determined", "result": tiers,
         "scope": a.option_scope, "exhaustive_for_case": a.exhaustive_for_case},
        {"id": "modifiers", "title": "修正情节", "status": "determined" if a.directions else "none_found",
         "result": [{"effect": d.effect, "trigger": d.trigger, "basis": _cite(lib, d.basis)} for d in a.directions],
         "note": None if a.directions else "按已填要素未发现从轻、减轻、从重等法定情节；未填的情节按未知处理"},
        {"id": "referral", "title": "涉嫌犯罪提示", "status": "found" if a.referral else "none_found",
         "result": _plain(a.referral)},
        _band_step(lib, facts, st),
        {"id": "written_type", "title": "成文处罚种类", "status": "determined" if decision.route == "rule_single" else "undetermined",
         "result": decision.penalty_type, "route": decision.route, "candidates": decision.candidates,
         "reasoning": {"rule_single": "省级基准只给出一个档位，对应唯一处罚种类",
                       "rule_candidates": "省级基准留有多个档位，处罚种类在候选内选择",
                       "model_fallback": "无省级分档，种类来自统计参考",
                       "undetermined": "要素不足以确定处罚种类，只给出法定空间与候选"}[decision.route]},
        {"id": "amount", "title": "档内数额参照（历史统计，非法律结论）", "status": "reference" if decision.quantities else "none",
         "result": _plain(decision.quantities),
         "source": {"scope": "全国、旧法时期、按处罚种类、事件加权，已按本案法定幅度过滤",
                    **{k: v for k, v in _quantities_meta().items() if k != "events"},
                    "events": {k: v for k, v in _quantities_meta()["events"].items()
                               if k.split(":")[0] == decision.penalty_type}}},
        practice_step(facts, decision),
    ]
    dev = deviation(decision, proposed, steps[-1])
    if dev:
        steps.append({"id": "deviation", "title": "偏离检查", "status": "checked", "result": dev})
    miss = missing(st)
    steps.append({"id": "missing", "title": "补查提示", "status": "found" if miss else "none", "result": miss})
    return {"versions": versions(lib, facts.region), "inputs": {"elements": elements, "proposed": proposed},
            "steps": steps, "needs_review": list(dict.fromkeys(decision.notes)),
            "disclaimer": "仅供辅助参考，不构成法律意见；结论须由办案人员审核确认"}


def new_run_id() -> str:
    return "dr_" + uuid.uuid4().hex[:16]


def request_digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
