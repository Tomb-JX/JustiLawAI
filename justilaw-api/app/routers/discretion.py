"""赌博类治安处罚裁量建议（引擎第一版）。

输入是办案人员填写的要素（不经大模型抽取），输出合法处罚空间、省级分档给出的处罚种类与档内历史分布。
设计见 docs/02-design/gambling-discretion-engine.md；输出是裁量建议，不是处罚决定。
"""
from __future__ import annotations

from dataclasses import asdict, fields
from datetime import date
from enum import Enum

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..auth import current_user, require_admin
from ..discretion import chain, slots
from ..discretion import trace as tr
from ..discretion.decide import decide
from ..discretion.norm_layer import Facts
from ..discretion.norm_store import load
from ..discretion.schema import (SCHEMA_VERSION, AmountRange, Role, BehaviorType, GamblingForm, GamblingMethod, MinorLevel,
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
    role: Role | None = None


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
        "minor_levels": _values(MinorLevel), "roles": _values(Role),
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


def _assess_data(body: AssessRequest) -> dict:
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
    return jsonable_encoder({
        "run_id": tr.new_run_id(),
        "written": {"type": d.penalty_type, "route": d.route, "candidates": d.candidates,
                    "legal_space": steps["legal_space"]["result"], "band": steps["band"]["result"]},
        "practice": {"status": steps["practice"]["status"], **(steps["practice"]["result"] or {}),
                     "reading": steps["practice"].get("reading"), "note": steps["practice"].get("note")},
        "amounts": steps["amount"]["result"],
        "deviation": steps["deviation"]["result"] if "deviation" in steps else None,
        "missing": steps["missing"]["result"],
        "needs_review": trace["needs_review"],
        "trace": trace,
    })


@router.post("/discretion/assess")
async def assess_route(body: AssessRequest, user: dict = Depends(current_user)):
    data = _assess_data(body)
    _record(data["run_id"], "assess", user, body.model_dump(mode="json"), status="succeeded",
            result=data, finished_at=tr.now())
    discretion_runs_db.save()
    return ok(data)


# ---------- §3.12 模型槽位、分段解析、要素抽取、决定书审查 ----------

def _chain_versions() -> dict:
    try:
        return {"chain": {"available": True, **chain.versions()}}
    except chain.ChainUnavailable as e:
        return {"chain": {"available": False, "reason": str(e)}}


@router.get("/discretion/settings")
async def get_settings(user: dict = Depends(current_user)):
    return ok({"models": slots.get(), **_chain_versions()})


@router.put("/discretion/settings", dependencies=[Depends(require_admin)])
async def put_settings(body: dict):
    out = slots.put((body or {}).get("models") or {})
    if out["errors"]:
        raise HTTPException(422, detail=err(42200, "；".join(out["errors"])))
    return ok({"models": out["settings"], **_chain_versions()})


DocKind = Literal["笔录", "叙述", "决定书"]


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=30000)
    doc_kind: DocKind = "叙述"
    target: str | None = None                       # 本案当事人写法（多人文书必填）
    model_id: str | None = None                     # 临时指定 segment 槽位模型（需槽位允许）


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=30000)
    parse_run_id: str | None = None                 # 复用已有 parse 结果，不重复调用分段模型
    doc_kind: DocKind = "叙述"
    target: str | None = None
    region: str | None = None
    behavior_date: date | None = None
    decision_date: date | None = None
    model_id: str | None = None                     # extract 槽位
    segment_model_id: str | None = None             # 需要先分段时用的 segment 槽位模型


class ReviewRequest(BaseModel):
    """决定书审查：给 text（走 ①–③ 再评估），或给已确认的 elements + actual（不调用模型）。"""
    model_config = ConfigDict(extra="forbid")
    text: str | None = Field(default=None, max_length=30000)
    target: str | None = None
    region: str | None = None
    behavior_date: date | None = None
    decision_date: date | None = None
    model_id: str | None = None
    segment_model_id: str | None = None
    elements: AssessRequest | None = None
    actual: Proposed | None = None


def _slot(slot: str, override: str | None, user: dict) -> dict:
    try:
        return slots.resolve(slot, override, user)
    except PermissionError as e:
        raise HTTPException(403, detail=err(40300, str(e)))
    except LookupError as e:
        raise HTTPException(503, detail=err(50300, f"裁量模型未配置/不可用：{e}"))


def _need_chain() -> None:
    try:
        chain.load()
    except chain.ChainUnavailable as e:
        raise HTTPException(503, detail=err(50300, str(e)))


def _public(calls: list[dict]) -> list[dict]:
    """响应里去掉原始模型输出（只留在存档里）。"""
    return [{k: v for k, v in c.items() if k != "_raw"} for c in calls]


# ---------- 任务号 + 轮询（调用模型的 parse / extract / review） ----------
# 提交即返回 202 与 run_id；工作在后台执行，状态写入运行存档，前端轮询 GET /discretion/runs/{run_id}。
# 不需要模型就能发现的错误（参数、槽位配置、链路不可用）在提交时同步返回，不建任务。

_ACTIVE: set[str] = set()          # 本进程内正在执行的任务；服务重启后残留的 running 记录按中断处理
POLL_INTERVAL_MS = 2000


class JobError(Exception):
    """任务失败：HTTP 语义的状态与错误码 + 已完成部分（解析、抽取、模型回执），一并存档。"""

    def __init__(self, status: int, code: int, message: str, calls: list[dict] | None = None,
                 partial: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.calls, self.partial = status, code, calls or [], partial or {}


def _job_error(e: Exception, prior: list[dict] | None = None) -> JobError:
    prior = prior or []
    if isinstance(e, JobError):
        return e
    if isinstance(e, HTTPException):
        return JobError(e.status_code, e.detail["code"], e.detail["message"], prior)
    if isinstance(e, chain.ChainUnavailable):
        return JobError(503, 50300, str(e), prior)
    if isinstance(e, chain.ChainFailed):
        return JobError(502, 50200, str(e), prior + e.calls)
    if isinstance(e, ValueError):
        return JobError(422, 42200, str(e)[:300], prior)
    return JobError(500, 50000, f"{type(e).__name__}: {str(e)[:300]}", prior)


def _record(run_id: str, kind: str, user: dict, request: dict, **fields) -> dict:
    rec = {"run_id": run_id, "kind": kind, "owner": user.get("id"), "created_at": tr.now(),
           "request_sha256": tr.request_digest(request), "request": request, **fields}
    discretion_runs_db.data[run_id] = rec
    return rec


async def _execute(run_id: str, work) -> None:
    rec = discretion_runs_db.data[run_id]
    try:
        public, archived = await work()
        if "run_id" in public:      # review 内部复用 assess，结果里的 run_id 统一为任务号
            public["run_id"] = run_id
        rec.update(status="succeeded", result=public, archive=archived)
    except Exception as e:  # noqa: BLE001  任务失败一律落档，不向外抛
        je = _job_error(e)
        rec.update(status="failed",
                   error={"http_status": je.status, "code": je.code, "message": str(je)},
                   partial={**je.partial, "model_calls": _public(je.calls)} if (je.partial or je.calls) else None,
                   archive={"model_calls": je.calls})
    finally:
        rec["finished_at"] = tr.now()
        _ACTIVE.discard(run_id)
        discretion_runs_db.save()


def _submit(kind: str, user: dict, request: dict, work, background: BackgroundTasks) -> JSONResponse:
    run_id = tr.new_run_id()
    _record(run_id, kind, user, request, status="running")
    discretion_runs_db.save()
    _ACTIVE.add(run_id)
    background.add_task(_execute, run_id, work)
    return JSONResponse(status_code=202, content=ok({
        "run_id": run_id, "kind": kind, "status": "running",
        "poll": f"/api/v1/discretion/runs/{run_id}", "poll_interval_ms": POLL_INTERVAL_MS}))


def _parse_view(p: dict, doc_kind: str) -> dict:
    out = p["output"]
    view = {"sentences": p["sentences"], "zones": out.get("zones"), "subject": out.get("subject"),
            "dates": out.get("dates"), "gambling": out.get("gambling"), "review": out.get("review"),
            "validation": (p["model_calls"][-1].get("validation") if p["model_calls"] else None)}
    if doc_kind == "决定书":
        view["outcome"] = out.get("outcome")
    return view


@router.post("/discretion/parse", status_code=202)
async def parse_route(body: ParseRequest, background: BackgroundTasks, user: dict = Depends(current_user)):
    _need_chain()
    cfg = _slot("segment", body.model_id, user)
    req = body.model_dump(mode="json")

    async def work():
        try:
            p = await chain.parse(body.text, body.doc_kind, body.target, cfg)
        except Exception as e:  # noqa: BLE001
            raise _job_error(e)
        view = _parse_view(p, body.doc_kind)
        trace = {"versions": {"engine": tr.ENGINE_VERSION, **chain.versions()},
                 "inputs": {"text_sha256": p["text_sha256"], "doc_kind": body.doc_kind, "target": body.target},
                 "model_calls": _public(p["model_calls"])}
        internal = {"spans": p["spans"], "output": p["output"], "text": body.text, "text_sha256": p["text_sha256"]}
        return {**view, "trace": trace}, {"model_calls": p["model_calls"], "_internal": internal}

    return _submit("parse", user, req, work, background)


async def _extract(text, parsed, target, region, bd, dd, cfg) -> dict:
    target = target or ((parsed["output"].get("subject") or {}).get("mention"))
    if not target:
        raise ValueError("未能确定本案当事人，请在 target 中给出")
    dates = parsed["output"].get("dates") or {}
    meta = {"region": region, "behavior_date": bd or dates.get("behavior"),
            "decision_date": dd or dates.get("decision")}
    x = await chain.extract(text, parsed, target, cfg, meta)
    missing_meta = [k for k in ("behavior_date", "region") if not x["assess_input"].get(k)]
    return {**x, "target": target, "meta_missing": missing_meta}


def _owned_run(run_id: str, user: dict, kind: str | None = None) -> dict:
    run = discretion_runs_db.data.get(run_id)
    if (not run or (kind and run.get("kind") != kind)
            or (run.get("owner") != user.get("id") and user.get("role") != "admin")):
        raise HTTPException(404, detail=err(40400, "运行记录不存在"))
    return run


@router.post("/discretion/extract", status_code=202)
async def extract_route(body: ExtractRequest, background: BackgroundTasks, user: dict = Depends(current_user)):
    _need_chain()
    if body.parse_run_id:
        run = _owned_run(body.parse_run_id, user, "parse")
        if run.get("status", "succeeded") != "succeeded":
            raise HTTPException(409, detail=err(40900, f"分段任务状态为 {run.get('status')}，不能用于抽取"))
        internal = run["archive"]["_internal"]
        text = internal["text"]
        parsed0 = {"spans": internal["spans"], "output": internal["output"],
                   "text_sha256": internal["text_sha256"], "model_calls": []}
        seg_cfg = None
    elif body.text:
        text, parsed0 = body.text, None
        seg_cfg = _slot("segment", body.segment_model_id, user)
    else:
        raise HTTPException(422, detail=err(42200, "text 与 parse_run_id 至少给一个"))
    cfg = _slot("extract", body.model_id, user)
    req = body.model_dump(mode="json")

    async def work():
        calls = []
        try:
            parsed = parsed0 or await chain.parse(text, body.doc_kind, body.target, seg_cfg)
            calls += parsed["model_calls"]
            x = await _extract(text, parsed, body.target, body.region, body.behavior_date, body.decision_date, cfg)
        except Exception as e:  # noqa: BLE001
            raise _job_error(e, calls)
        calls += x["model_calls"]
        trace = {"versions": {"engine": tr.ENGINE_VERSION, "schema": SCHEMA_VERSION, **chain.versions()},
                 "inputs": {"text_sha256": parsed["text_sha256"], "parse_run_id": body.parse_run_id,
                            "target": x["target"], "input_view": x["input_view"]},
                 "model_calls": _public(calls)}
        data = {"schema_version": SCHEMA_VERSION, "elements": x["elements"], "dropped": x["dropped"],
                "assess_input": x["assess_input"], "meta_missing": x["meta_missing"], "target": x["target"],
                "trace": trace,
                "note": "抽取结果须经人工确认后再用于评估；确认或修改后把 provenance.origin 改为 extracted_then_confirmed / edited"}
        return data, {"model_calls": calls}

    return _submit("extract", user, req, work, background)


REVIEWABLE = {"不予处罚", "罚款", "拘留", "拘留并处罚款"}


def _review_result(assess_body: AssessRequest, actual: dict, parse_view, extraction, calls) -> dict:
    data = _assess_data(assess_body.model_copy(update={"proposed": Proposed(**actual)}))
    flagged = [lv["title"] for lv in data["deviation"]["levels"] if lv["ok"] is False]
    data["deviation"]["summary"] = (("未发现偏离" if not flagged else "存在偏离：" + "、".join(flagged))
                                    + "（实务参照只报比例，不判对错）")
    data.update(actual=actual, parse=parse_view, extraction=extraction)
    data["trace"]["model_calls"] = _public(calls)
    if calls:
        data["trace"]["versions"].update(chain.versions())
    return data


@router.post("/discretion/review", status_code=202)
async def review_route(body: ReviewRequest, background: BackgroundTasks, user: dict = Depends(current_user)):
    req = body.model_dump(mode="json")
    if body.elements is not None:
        if body.actual is None:
            raise HTTPException(422, detail=err(42200, "给 elements 时必须同时给 actual（实际处罚）"))

        async def work():           # 已确认要素：不调用模型，任务立即完成
            data = _review_result(body.elements, body.actual.model_dump(), None, None, [])
            return data, {}

        return _submit("review", user, req, work, background)
    if not body.text:
        raise HTTPException(422, detail=err(42200, "text 或 elements + actual 至少给一组"))
    _need_chain()
    seg_cfg = _slot("segment", body.segment_model_id, user)
    cfg = _slot("extract", body.model_id, user)

    async def work():
        calls = []
        try:
            parsed = await chain.parse(body.text, "决定书", body.target, seg_cfg)
            calls += parsed["model_calls"]
            x = await _extract(body.text, parsed, body.target, body.region, body.behavior_date,
                               body.decision_date, cfg)
        except Exception as e:  # noqa: BLE001
            raise _job_error(e, calls)
        calls += x["model_calls"]
        parse_view = _parse_view(parsed, "决定书")
        extraction = {k: x[k] for k in ("elements", "dropped", "assess_input", "meta_missing", "target")}
        oc = parsed["output"].get("outcome") or {}
        problem = (f"解析后仍缺 {'、'.join(x['meta_missing'])}，请在请求中补充" if x["meta_missing"] else
                   f"决定书处罚种类为「{oc.get('type')}」，不在可审查范围（{'、'.join(sorted(REVIEWABLE))}）"
                   if oc.get("type") not in REVIEWABLE else None)
        if problem:     # 已花费的模型调用不丢：解析与抽取结果随失败记录返回
            raise JobError(422, 42200, problem, calls, {"parse": parse_view, "extraction": extraction})
        actual = {"type": oc["type"], "detention_days": oc.get("detention_days") or None,
                  "fine": oc.get("fine") or None}
        try:
            assess_body = AssessRequest.model_validate(x["assess_input"])
        except Exception as e:  # noqa: BLE001
            raise JobError(422, 42200, f"抽取要素无法用于评估：{str(e)[:300]}", calls,
                           {"parse": parse_view, "extraction": extraction})
        try:
            data = _review_result(assess_body, actual, parse_view, extraction, calls)
        except HTTPException as e:
            raise JobError(e.status_code, e.detail["code"], e.detail["message"], calls,
                           {"parse": parse_view, "extraction": extraction})
        return data, {"model_calls": calls}

    return _submit("review", user, req, work, background)


RUN_VIEW = ("run_id", "kind", "status", "created_at", "finished_at", "request_sha256", "result", "error", "partial")


@router.get("/discretion/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(current_user)):
    """轮询与审计共用。status：running / succeeded / failed；原始模型输出只在服务端存档，不返回。"""
    run = _owned_run(run_id, user)
    if run.get("status") == "running" and run_id not in _ACTIVE:
        run.update(status="failed", finished_at=tr.now(),
                   error={"http_status": 500, "code": 50001, "message": "服务重启，任务中断，请重新提交"})
        discretion_runs_db.save()
    view = {k: run.get(k) for k in RUN_VIEW}
    view["status"] = view["status"] or "succeeded"
    return ok(view)
