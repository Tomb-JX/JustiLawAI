"""赌博类治安处罚裁量建议（引擎第一版）。

输入是办案人员填写的要素（不经大模型抽取），输出合法处罚空间、省级分档给出的处罚种类与档内历史分布。
设计见 docs/02-design/gambling-discretion-engine.md；输出是裁量建议，不是处罚决定。
"""
from __future__ import annotations

from dataclasses import asdict, fields
from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict

from ..auth import current_user
from ..discretion import trace as tr
from ..discretion.decide import decide
from ..discretion.norm_layer import Facts
from ..discretion.norm_store import load
from ..discretion.schema import (AmountRange, BehaviorType, GamblingForm, GamblingMethod, MinorLevel,
                                 VenueType)
from ..resp import err, ok
from ..store import discretion_runs_db

router = APIRouter()


class DecideRequest(BaseModel):
    """字段与 norm_layer.Facts 一致；未填 = 未知（不是"否"）。"""
    model_config = ConfigDict(extra="forbid")

    behavior_date: date
    decision_date: date | None = None
    region: str | None = None                      # 六位行政区划代码，省级分档按前两位匹配
    behavior_type: BehaviorType
    age: int | None = None
    pregnant_or_nursing: bool | None = None
    first_offense: bool | None = None
    violations_last_year: int | None = None
    last_prior_penalty_date: date | None = None
    surrendered: bool | None = None
    truthful_statement: bool | None = None
    admits_and_accepts: bool | None = None
    remedied_consequence: bool | None = None
    victim_forgiveness: bool | None = None
    coerced_or_lured: bool | None = None
    meritorious: bool | None = None
    instigated_others: bool | None = None
    retaliation: bool | None = None
    minor_circumstance: MinorLevel | None = None
    personal_stake: AmountRange | None = None
    onsite_stake_total: AmountRange | None = None
    commission: AmountRange | None = None
    cumulative_stake: AmountRange | None = None
    participant_count: int | None = None
    cumulative_participants: int | None = None
    abroad_organized_count: int | None = None
    method: GamblingMethod | None = None
    gambling_form: GamblingForm | None = None
    venue_type: VenueType | None = None
    civil_servant: bool | None = None
    minors_involved: bool | None = None
    profit_purpose: bool | None = None
    times: int | None = None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str
    sentence: int | None = None
    span: tuple[int, int] | None = None


class Provenance(BaseModel):
    """要素来源：每个要素的状态、来源与原文证据（追踪用）。"""
    model_config = ConfigDict(extra="forbid")
    status: str = "明确"                            # 明确 / 推断
    origin: str = "human"                           # human / extracted / extracted_then_confirmed / edited
    evidence: list[Evidence] = []


class Proposed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str                                       # 罚款 / 拘留 / 拘留并处罚款 / 不予处罚
    detention_days: int | None = None
    fine: float | None = None


class AssessRequest(DecideRequest):
    """§3.12 assess：要素（与 decide 同名字段）+ 要素来源 + 拟处罚意见；结果附完整 trace 并存档。"""
    provenance: dict[str, Provenance] = {}
    proposed: Proposed | None = None


_FACT_FIELDS = {f.name for f in fields(Facts)}
assert set(DecideRequest.model_fields) == _FACT_FIELDS, "DecideRequest 与 Facts 字段不一致"


def _facts(body: DecideRequest) -> Facts:
    values = {k: getattr(body, k) for k in _FACT_FIELDS}
    return Facts(**{k: v.value if isinstance(v, Enum) else v for k, v in values.items()})


def _values(enum) -> list[str]:
    return [m.value for m in enum]


@router.get("/discretion/meta")
async def meta(user: dict = Depends(current_user)):
    lib = load()
    return ok({
        "behavior_types": _values(BehaviorType), "methods": _values(GamblingMethod),
        "gambling_forms": _values(GamblingForm), "venue_types": _values(VenueType),
        "minor_levels": _values(MinorLevel),
        "provinces": [{"code": code, "name": p.get("name")} for code, p in sorted(lib.provinces.items())],
        "laws": [{"id": law.law_id, "title": law.title} for law in lib.laws],
    })


@router.post("/discretion/decide")
async def decide_route(body: DecideRequest, user: dict = Depends(current_user)):
    values = {k: getattr(body, k) for k in _FACT_FIELDS}
    facts = Facts(**{k: v.value if isinstance(v, Enum) else v for k, v in values.items()})
    try:
        d = decide(facts)
    except ValueError as e:
        raise HTTPException(422, detail=err(42200, str(e)))
    out = asdict(d)
    out["assessment"]["tiers"] = {
        name: {**asdict(t), "options": [{**asdict(o), "kind": o.kind} for o in t.options]}
        for name, t in d.assessment.tiers.items()}
    return ok(jsonable_encoder(out))


@router.post("/discretion/assess")
async def assess_route(body: AssessRequest, user: dict = Depends(current_user)):
    unknown = set(body.provenance) - _FACT_FIELDS
    if unknown:
        raise HTTPException(422, detail=err(42200, f"provenance 含未知要素：{'、'.join(sorted(unknown))}"))
    facts = _facts(body)
    try:
        d = decide(facts)
    except ValueError as e:
        raise HTTPException(422, detail=err(42200, str(e)))
    lib = load()
    proposed = body.proposed.model_dump() if body.proposed else None
    trace = tr.build(lib, facts, d, {k: v.model_dump() for k, v in body.provenance.items()}, proposed)
    steps = {s["id"]: s for s in trace["steps"]}
    data = {
        "run_id": tr.new_run_id(),
        "written": {"type": d.penalty_type, "route": d.route, "candidates": d.candidates,
                    "legal_space": steps["legal_space"]["result"], "band": steps["band"]["result"]},
        "practice": None,
        "amounts": steps["amount"]["result"],
        "deviation": steps["deviation"]["result"] if "deviation" in steps else None,
        "missing": steps["missing"]["result"],
        "needs_review": trace["needs_review"],
        "trace": trace,
    }
    data = jsonable_encoder(data)
    discretion_runs_db.data[data["run_id"]] = {
        "run_id": data["run_id"], "kind": "assess", "owner": user.get("id"), "created_at": tr.now(),
        "request_sha256": tr.request_digest(body.model_dump(mode="json")), "request": body.model_dump(mode="json"),
        "result": data}
    discretion_runs_db.save()
    return ok(data)


@router.get("/discretion/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(current_user)):
    run = discretion_runs_db.data.get(run_id)
    if not run or (run.get("owner") != user.get("id") and user.get("role") != "admin"):
        raise HTTPException(404, detail=err(40400, "运行记录不存在"))
    return ok(run)
