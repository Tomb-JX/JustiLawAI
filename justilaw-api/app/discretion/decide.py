"""引擎第一版：要素 → M2 省级分档定处罚种类 → 档内数额分布。

- 种类：省级分档给出唯一种类就用它；给出多个候选时，由调用方提供的文本模型概率在候选内取最大；
  省级分档无输出（缺赌资、省份未录入等）时退回文本模型概率；都没有就不判，只给合法空间。
- 数额：档内历史分布（data/band_quantities.json），按本案适用法律的法定幅度过滤后重新归一；
  只给分布不给点值——档内数额对未见机关不可预测（docs/05-research/2026-10-28-rule-chain-validation.md）。
- 输出是裁量建议，不是处罚决定；省级分档本身也只是"已知要素的建议"（stake_threshold.scope）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .norm_layer import NO_PENALTY, Assessment, Facts, assess
from .norm_store import NormLibrary

QUANTITIES = Path(__file__).parent / "data" / "band_quantities.json"
PENALTY_TYPES = ("罚款", "拘留", "拘留并处罚款", NO_PENALTY)
TIER_OF = {"罚款": "一般", "拘留": "一般", "拘留并处罚款": "情节严重"}


def band_types(stake: dict) -> list[str]:
    """省级分档（stake_threshold）→ 可能的处罚种类，按 band_penalty 原文判定。"""
    names, penalties = stake.get("bands") or [], list(stake.get("band_penalty") or [])
    if names and names[0] == "未达起罚标准":
        penalties = [None] + penalties
    out = set()
    for name, text in zip(names, penalties):
        if name == "未达起罚标准":
            out.add(NO_PENALTY)
        elif "拘留" in text and "罚款" in text:
            out.add("拘留并处罚款")
        else:
            out.add("拘留" if "拘留" in text else "罚款")
    return sorted(out)


@lru_cache(maxsize=1)
def _quantities() -> dict:
    return json.loads(QUANTITIES.read_text(encoding="utf-8"))


def _legal_distribution(a: Assessment, kind: str, field_name: str) -> list[tuple[float, float]]:
    """档内历史分布中落在本案法定幅度内的取值，重新归一。"""
    tier = a.tiers.get(TIER_OF[kind])
    entry = (_quantities()["bands"].get(kind) or {}).get(field_name)
    if tier is None or entry is None:
        return []
    ranges = [o.detention if field_name == "detention_days" else o.fine
              for o in tier.options if o.kind == kind and o.via == "法定幅度"]
    kept = [(v, s) for v, s in entry["values"] if any(r and r[0] <= v <= r[1] for r in ranges)]
    total = sum(s for _, s in kept)
    return [(v, round(s / total, 3)) for v, s in kept] if total else []


@dataclass
class Decision:
    penalty_type: str | None            # 建议处罚种类；None = 不足以判断
    route: str                          # rule_single / rule_candidates / model_fallback / undetermined
    candidates: list[str]               # 省级分档允许的种类（空 = 无省级分档）
    quantities: dict[str, list[tuple[float, float]]]   # 字段 → [(取值, 占比)]，按占比降序
    assessment: Assessment
    notes: list[str] = field(default_factory=list)


def decide(f: Facts, type_probabilities: dict[str, float] | None = None,
           lib: NormLibrary | None = None) -> Decision:
    a = assess(f, lib)
    candidates = band_types(a.stake_threshold)
    probs = {k: v for k, v in (type_probabilities or {}).items() if k in PENALTY_TYPES}
    notes = []
    if len(candidates) == 1:
        kind, route = candidates[0], "rule_single"
    elif candidates and probs:
        kind, route = max(candidates, key=lambda k: probs.get(k, 0.0)), "rule_candidates"
        notes.append("省级分档留有多个种类，按文本模型概率在候选内选择")
    elif candidates:
        kind, route = None, "undetermined"
        notes.append("省级分档留有多个种类且无文本模型概率，未选定种类")
    elif probs:
        kind, route = max(probs, key=probs.get), "model_fallback"
        notes.append(f"无省级分档（{a.stake_threshold.get('status')}），种类来自文本模型，仅作统计参考")
    else:
        kind, route = None, "undetermined"
        notes.append("无省级分档且无文本模型概率，仅给出法定处罚空间")
    quantities = {}
    if kind in TIER_OF:
        fields = ("fine",) if kind == "罚款" else ("detention_days",) if kind == "拘留" else ("detention_days", "fine")
        quantities = {name: _legal_distribution(a, kind, name) for name in fields}
        notes.append("档内数额为历史分布（旧法时期决定），不是点预测")
    return Decision(kind, route, candidates, quantities, a, notes + a.needs_review)
