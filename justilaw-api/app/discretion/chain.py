"""能力层 ①–③：清洗句表 → 分段与结果解析（S1）→ 要素抽取。复用 research/discretion/unify 的已有链路。

只换"模型调用入口"：S1 与要素链路的提示、输入视图、结构校验、引用编译与归一化全部原样调用，
模型请求改走平台网关（model_gateway.call_json），按槽位配置选模型（slots.py）。
每次尝试都留回执（槽位、提示版本、供应商、模型、参数、请求与响应摘要、耗时、usage、校验结果）。

平台输入的文本不经网页清洗：cleaned = 原文，坐标映射为恒等（OffsetIndex 无删除）。
部署镜像目前不含 research/ 目录，链路不可用时接口返回 503（见 API 契约 §3.12）。
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
import sys
from dataclasses import fields
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from ..model_gateway import gateway
from .norm_layer import Facts
from .schema import GamblingElements

API_DIR = Path(__file__).resolve().parents[2]
UNIFY = API_DIR.parent / "research" / "discretion" / "unify"
SOURCE_TYPE = "平台输入"


class ChainUnavailable(RuntimeError):
    pass


class ChainFailed(RuntimeError):
    def __init__(self, message: str, calls: list[dict]):
        super().__init__(message)
        self.calls = calls


@lru_cache(maxsize=1)
def load() -> SimpleNamespace:
    if not (UNIFY / "s1.py").is_file():
        raise ChainUnavailable("信息处理链路模块不可用（部署包未包含 research/discretion/unify）")
    os.environ.setdefault("JUSTILAW_ENGINE_API", str(API_DIR))
    if str(UNIFY) not in sys.path:
        sys.path.insert(0, str(UNIFY))
    import cleanse
    import run_elements
    import s1
    from locate import OffsetIndex
    from supply_packet import build_packet
    engine = run_elements.ENGINE
    impl = {name: hashlib.sha256((UNIFY / name).read_bytes()).hexdigest()
            for name in ("s1.py", "cleanse.py", "run_elements.py", "element_contract.py", "supply_packet.py")}
    return SimpleNamespace(
        sentence_table=cleanse.sentence_table, s1=s1, re=run_elements, OffsetIndex=OffsetIndex,
        build_packet=build_packet, engine=engine,
        segment_prompt={"version": s1.PROMPT_VERSION, "system_sha256": _sha(s1.SYSTEM_PROMPT)},
        extract_prompt={"version": engine.PROMPT_VERSION, "wire": run_elements.WIRE_VERSION,
                        "schema": engine.SCHEMA_VERSION,
                        "fingerprint_sha256": run_elements.digest(run_elements.prompt_fingerprint(engine))},
        implementation=impl)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def versions() -> dict:
    ns = load()
    return {"segment_prompt": ns.segment_prompt, "extract_prompt": ns.extract_prompt,
            "chain_files_sha256": ns.implementation}


async def _run(slot: str, cfg: dict, messages: list[dict], check, prompt: dict) -> tuple[object, list[dict]]:
    """主模型（1 + retries 次，校验不过时把违例回灌重试）→ 备用模型 1 次。check(content) → (结果, 违例列表)。"""
    p = cfg["params"]
    seq = [cfg["effective_model_id"]] * (1 + int(p.get("retries", 1)))
    if cfg.get("fallback_model_id"):
        seq.append(cfg["fallback_model_id"])
    params = {**{k: v for k, v in p.items() if k != "retries"}, "json": True}
    calls, msgs, last = [], list(messages), "未调用"
    for attempt, model_id in enumerate(seq, 1):
        base = {"slot": slot, "attempt": attempt, "prompt": prompt}
        try:
            content, receipt = await gateway.call_json(model_id, msgs, params)
        except Exception as e:  # noqa: BLE001
            calls.append({**base, **(getattr(e, "receipt", None) or {"platform_model_id": model_id,
                                                                     "status": "fail", "error": str(e)[:300]})})
            last = str(e)[:300]
            continue
        result, errors = check(content)
        calls.append({**base, **receipt, "validation": {"ok": not errors, "violations": errors[:10]}})
        if not errors:
            return result, calls
        last = "；".join(errors[:3])
        msgs = messages[:-1] + [{"role": "user", "content": messages[-1]["content"]
                                 + "\n\n[上次输出存在错误，请修正后重发全部字段：" + last + "]"}]
    raise ChainFailed(f"{slot} 失败：{last}", calls)


# ---------- ② 分段与结果解析 ----------

async def parse(text: str, doc_kind: str, target: str | None, cfg: dict) -> dict:
    ns = load()
    sentences = ns.sentence_table(text)
    if not sentences:
        raise ValueError("文本为空或无法切分句子")
    texts = [text[a:b] for a, b in sentences]
    user = ns.s1.build_user_prompt(doc_kind, SOURCE_TYPE, texts, subject_mention=target or "")
    messages = [{"role": "system", "content": ns.s1.SYSTEM_PROMPT}, {"role": "user", "content": user}]

    def check(content):
        try:
            out = ns.s1.extract_json(content)
        except Exception as e:  # noqa: BLE001
            return None, [f"无法提取 JSON：{str(e)[:80]}"]
        return out, ns.s1.validate(out, n_sentences=len(sentences))

    out, calls = await _run("segment", cfg, messages, check, ns.segment_prompt)
    return {"sentences": texts, "spans": sentences, "output": out, "model_calls": calls,
            "text_sha256": _sha(text)}


# ---------- ③ 要素抽取 ----------

def _path_by_fact() -> dict[str, str]:
    names = {f.name for f in fields(Facts)}
    out = {}
    for path in load().engine.FIELD_INFO:
        name = path.split(".")[1]
        if name in names:
            out[name] = path
    return out


async def extract(text: str, parsed: dict, target: str, cfg: dict, meta: dict) -> dict:
    ns = load()
    rec = {"id": parsed["text_sha256"][:16], "cleaned_text": text, "sentences": parsed["spans"],
           "_text_full": text, "text_orig_sha256": parsed["text_sha256"], "subject_mention": target}
    seg = {k: parsed["output"].get(k) for k in ("zones", "subject", "meta_fields", "prior_sentence_ids")
           if parsed["output"].get(k) is not None}
    inp = ns.re.build_inputs(rec, seg, ns.OffsetIndex({"orig_len": len(text), "deletes": []}))
    if inp is None:
        raise ValueError("目标当事人不在事实或当事人信息句中，无法组织抽取输入")
    inp["supply_packet"] = ns.build_packet(text, inp, record_id=rec["id"], case_event_id=None,
                                           schema_version=ns.engine.SCHEMA_VERSION)
    messages = ns.re.messages(ns.engine, inp)

    def check(content):
        try:
            payload = ns.s1.extract_json(content)
            return ns.re.compile_references(payload, inp, text, ns.engine), []
        except ValueError as e:
            return None, [str(e)[:300]]

    compiled, calls = await _run("extract", cfg, messages, check, ns.extract_prompt)
    starts = [a for a, _ in parsed["spans"]]
    elements, provenance = {}, {}
    by_fact = {p: f for f, p in _path_by_fact().items()}
    for group, items in compiled.items():
        for name, item in items.items():
            path = f"{group}.{name}"
            ev = [{"quote": e["quote"], "sentence": bisect.bisect_right(starts, e["start"]),
                   "span": [e["start"], e["end"]]} for e in item.get("evidence") or []]
            elements[path] = {"value": item.get("value"), "status": item.get("status"), "evidence": ev,
                              "origin": "extracted", "fact_field": by_fact.get(path)}
            if by_fact.get(path) and item.get("status") != "未提及":
                provenance[by_fact[path]] = {"status": item["status"], "origin": "extracted", "evidence": ev}
    el = GamblingElements.model_validate({"meta": {k: v for k, v in meta.items() if v}, **compiled})
    facts = Facts.from_elements(el)
    flat = {k: (v.value if hasattr(v, "value") and not hasattr(v, "model_dump") else v)
            for k, v in vars(facts).items() if v is not None}
    flat = json.loads(json.dumps(flat, ensure_ascii=False, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)))
    return {"elements": elements, "assess_input": {**flat, "provenance": provenance},
            "input_view": {"sentences": [s["sentence_id"] for s in inp["sentence_view"]], "view_sha256": inp["view_hash"]},
            "model_calls": calls}
