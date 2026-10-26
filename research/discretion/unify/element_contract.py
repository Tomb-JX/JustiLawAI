"""Engine-owned element semantics with a versioned sentence-reference wire format.

No ontology or acceptance threshold is defined here. element-ref-v2 is a transport
version, NOT a declaration that the engine has approved an element-v2 ontology.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

WIRE_VERSION = "element-ref-v3"  # v3：白名单字段推断态放行 value=null（对齐指南 v0.2）

# 模型质量类失败的稳定前缀表：runner 据此隔离单条、其余 ValueError 一律整批 fail-fast。
# 任何改文案都必须同步这张表，且有 test_model_quality_isolation_taxonomy 守卫。
MODEL_QUALITY_PREFIXES = (
    "wire_schema:", "engine_validation:", "e05_evidence_contract:", "e05_amount_mismatch:",
    "numeric_evidence_unsupported:", "invalid_candidate:", "invalid_legacy:",
    "legacy_evidence_not_allowed_or_ambiguous", "evidence_outside_input",
    "reference_not_allowed:", "reference_out_of_bounds", "reference_source_mismatch", "facts_empty",
    "unknown fact clause ID", "S1_invalid_outcome_numbers", "无法提取 JSON",
)

# full 扩产模式下只有这些必须整批停；超时/断流/单条传输故障/未知账单条隔离后继续
# （unknown_remote_outcome 只跳过该条，不杀批；批次末尾统一核账）。
FULL_MODE_HARD_STOP_PREFIXES = (
    "budget_stop", "shared_budget_stop", "provider_disabled",
    "engine_contract_changed", "contract_changed_during_call", "implementation_changed",
    "execution_settings_changed", "running_elsewhere", "invalid_call_limits",
    "missing_price", "invalid_registered_price",
)


def is_full_mode_hard_stop(exc):
    text = str(exc)
    if text.startswith(FULL_MODE_HARD_STOP_PREFIXES):
        return True
    # Account-level provider failures (arrears/revoked key) burn a 400 on every
    # remaining record; stop the batch instead of quarantining each one.
    return "Arrearage" in text or "Access denied" in text


def is_model_quality_failure(exc):
    """单条模型输出不合格（可隔离续跑）还是管线级故障（必须停批）？"""
    import json as _json
    if isinstance(exc, _json.decoder.JSONDecodeError):
        return True
    return str(exc).startswith(MODEL_QUALITY_PREFIXES)


def _engine_eval_dir() -> Path:
    """Resolve research/eval/ from the engine worktree (E-05 approval package location)."""
    sibling_api = Path(__file__).resolve().parents[3].parent / "discretion-engine/justilaw-api"
    api_path = Path(os.environ.get("JUSTILAW_ENGINE_API") or sibling_api)
    eval_dir = api_path.parent / "research" / "eval"
    if not (eval_dir / "normalization_spec.py").is_file():
        raise RuntimeError("E-05 批准包不可达；research/eval/normalization_spec.py 缺失")
    return eval_dir


def _load_e05_module(name: str):
    """Lazy-load an E-05 approval module from research/eval/."""
    eval_dir = _engine_eval_dir()
    mod_name = f"e05_{name}"
    if mod_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(mod_name, str(eval_dir / f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[mod_name]


def normalization_spec():
    """Return the E-05 normalization_spec module (lazy-loaded)."""
    return _load_e05_module("normalization_spec")


def evidence_contract():
    """Return the E-05 evidence_contract module (lazy-loaded)."""
    return _load_e05_module("evidence_contract")


def binding_rules():
    """Return the E-05 binding_rules module (lazy-loaded)."""
    return _load_e05_module("binding_rules")


def classify_bindings(payload: dict, target: str, aliases=()) -> dict:
    """Classify all evidence bindings using engine FIELD_BINDING semantic definition table.

    Returns binding_summary dict with shared_fact/target_specific/needs_review counts.
    """
    br = binding_rules()
    field_binding = br.FIELD_BINDING
    from collections import Counter
    counts = Counter()
    for group_name, group in (payload or {}).items():
        if not isinstance(group, dict):
            continue
        for field_name, item in group.items():
            if not isinstance(item, dict):
                continue
            if item.get("status") == "未提及" or item.get("value") is None:
                continue
            path = f"{group_name}.{field_name}"
            binding_type = field_binding.get(path)
            if binding_type is None:
                counts["needs_review"] += 1
            else:
                counts[binding_type.value] += 1
    return {
        "total": sum(counts.values()),
        "shared_fact": counts.get("shared_fact", 0),
        "target_specific": counts.get("target_specific", 0),
        "needs_review": counts.get("needs_review", 0),
    }


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def engine_contract():
    # An explicit path is mandatory outside the known sibling-worktree layout.
    sibling = Path(__file__).resolve().parents[3].parent / "discretion-engine/justilaw-api"
    path = Path(os.environ.get("JUSTILAW_ENGINE_API") or sibling)
    if not (path / "app/discretion/element_labels.py").is_file():
        raise RuntimeError("引擎契约不可达；设 JUSTILAW_ENGINE_API，不得在网页侧重定义字段")
    sys.path.insert(0, str(path))
    module = importlib.import_module("app.discretion.element_labels")
    actual = Path(module.__file__).resolve()
    if actual != (path / "app/discretion/element_labels.py").resolve():
        raise RuntimeError("已加载其他引擎契约；在新进程中固定 JUSTILAW_ENGINE_API")
    return module


def contract_snapshot(engine) -> dict:
    paths = [Path(engine.__file__), Path(engine.__file__).with_name("schema.py"),
             Path(engine.__file__).with_name("extract.py")]
    here = Path(__file__).resolve().parent
    dependencies = [here.parent / "harvest/parse.py", here.parent / "harvest/parse_qc.py",
                    Path(engine.__file__).resolve().parents[3] / "research/eval/key_field_presence.py"]
    # E-05 批准包是运行时 lazy-load 的校验权威：金额/证据/绑定语义的任何修改都必须
    # 在契约冻结里可见，否则"改了机器对账却没人察觉"（审计 P1-10）。
    eval_dir = _engine_eval_dir()
    dependencies += [eval_dir / name for name in
                     ("normalization_spec.py", "evidence_contract.py", "binding_rules.py")]
    from s1 import data_root
    caps = data_root() / "config/legal_caps.json"
    dependencies.append(caps)
    return {"wire_version": WIRE_VERSION, "engine_prompt_version": engine.PROMPT_VERSION,
            "engine_schema_version": engine.SCHEMA_VERSION,
            "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
            "implementation": implementation_snapshot(),
            "dependencies": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in dependencies if p.is_file()}}


def implementation_snapshot() -> dict:
    # Freeze local prompts, projection, normalization and billing code as well as
    # the engine schema. A transport version alone cannot identify these changes.
    here = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(here.glob("*.py"))}


def reference_schema(engine) -> dict:
    schema = copy.deepcopy(engine.teacher_output_schema())
    for path in engine.FIELD_INFO:
        group, name = path.split(".")
        item = schema["properties"][group]["properties"][name]
        item["properties"]["evidence"] = {
            "type": "array", "items": {"type": "object", "properties": {
                "sentence_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
                                 "items": {"type": "string", "minLength": 1}}},
                "required": ["sentence_ids"], "additionalProperties": False}}
        unmentioned_rule = {
            "if": {"properties": {"status": {"const": "未提及"}}},
            "then": {"properties": {"value": {"type": "null"}, "evidence": {"maxItems": 0}}},
        }
        explicit_rule = {
            "if": {"properties": {"status": {"const": "明确"}}},
            "then": {"properties": {"value": {"not": {"type": "null"}}}},
        }
        if path in getattr(engine, "NULLABLE_WHEN_INFERRED", ()):
            # 指南 v0.2：该三字段"多次/多人/三十余岁"裁定值记 null、状态推断；仅"明确"必须有值。
            unmentioned_rule["else"] = {"properties": {"evidence": {"minItems": 1}}}
            item["allOf"] = [unmentioned_rule, explicit_rule]
        else:
            unmentioned_rule["else"] = {"properties": {"value": {"not": {"type": "null"}},
                                                       "evidence": {"minItems": 1}}}
            item["allOf"] = [unmentioned_rule]
    return schema


def system_prompt(engine) -> str:
    """传输用 system 全文；它是 prompt 指纹的唯一权威（改这里=改缓存身份）。"""
    from contract_bundle import make_bundle
    bundle = make_bundle(engine)
    return bundle['prompt'] + (
        "\n【传输契约覆盖】证据不抄引文、不算坐标，只选本次允许句的 sentence_ids。"
        "不得引用其他记录或范围外句。未提及须由已读输入支持，缺字段不等于未提及。"
        "按下面完整 JSON Schema 输出七组对象，禁止平铺、包裹或额外键。\n"
        + json.dumps(bundle['output_schema'], ensure_ascii=False))


def prompt_fingerprint(engine) -> dict:
    """只覆盖"真正进请求的内容"：system 全文、user 信封、wire 与引擎版本。
    校验器/计费/runner 等不影响提示词的代码编辑不改变本指纹——审计 P0-1：
    实现哈希曾把付费缓存全灭；工单与 manifest 仍记录全量快照（审计纪律不放宽），
    但缓存 key、续跑识别、工单准入改认此稳定指纹。"""
    return {"wire_version": WIRE_VERSION,
            "engine_prompt_version": engine.PROMPT_VERSION,
            "engine_schema_version": engine.SCHEMA_VERSION,
            "system_sha256": hashlib.sha256(system_prompt(engine).encode("utf-8")).hexdigest(),
            "user_envelope": ["target", "aliases", "prompt_fingerprint", "allowed_sentences"]}


def messages(engine, inp: dict, *, decisions: list | None = None) -> list[dict]:
    # Always transmit the complete engine value schema, including enums.
    system = system_prompt(engine)
    user = {"target": inp["target"], "aliases": inp["aliases"],
            "prompt_fingerprint": digest(prompt_fingerprint(engine)),
            "allowed_sentences": inp["sentence_view"]}
    if decisions is not None:
        # C emits complete fields under the same schema, with exactly the same view.
        user["disagreements"] = decisions
        user["instruction"] = "独立依据本人的允许句重标全部字段；可纠正两候选，但新值必须给自己的有效引用。"
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def compile_references(payload: object, inp: dict, text_full: str, engine) -> dict:
    """Validate wire types, compile allowed IDs, then run the engine's final validator."""
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(reference_schema(engine)).iter_errors(payload),
                    key=lambda e: str(list(e.path)))
    if errors:
        raise ValueError("wire_schema:" + ";".join(f"{list(e.path)}:{e.validator}" for e in errors[:10]))
    allowed = {s["id"]: s for s in inp["sentence_view"]}
    result = copy.deepcopy(payload)
    for group in result.values():
        for field in group.values():
            evidence = []
            seen = set()
            for ev in field["evidence"]:
                for sid in ev["sentence_ids"]:
                    if sid not in allowed:
                        raise ValueError(f"reference_not_allowed:{sid}")
                    s = allowed[sid]
                    a, b = s["start"], s["end"]
                    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text_full):
                        raise ValueError("reference_out_of_bounds")
                    if text_full[a:b] != s["text"]:
                        raise ValueError("reference_source_mismatch")
                    if (a, b) not in seen:
                        evidence.append({"quote": text_full[a:b], "start": a, "end": b})
                        seen.add((a, b))
            field["evidence"] = evidence
    issues = engine.validate_teacher_output(result, evidence_text=text_full, located=True)
    if issues:
        raise ValueError("engine_validation:" + ";".join(f"{i.field}:{i.code}" for i in issues))
    # E-05 证据语义校验（§3.10）：来源限制 facts/meta、逐字连续、坐标
    e05_issues = validate_evidence_contract(
        result, text_full,
        facts_text=inp.get("facts_text") or "",
        meta_text=inp.get("meta_text") or "", located=True)
    e05_errors = [i for i in e05_issues if i.severity == "error"]
    if e05_errors:
        raise ValueError("e05_evidence_contract:" + ";".join(
            f"{i.field}:{i.code}" for i in e05_errors))
    check_money_support(result)
    return result


def check_money_support(payload):
    """Local monetary grounding only, NOT a claim of semantic entailment.

    指南 v0.2 的开口与多值语义必须被承认：'10元起押、上不封顶' → (10,null)，
    '2元和4元的底注' → (2,4)，逐项列出需加总 → (sum,sum)，列举带'等' → (sum,null)。
    对账集合只取自本字段自己的 evidence quotes（不借全文），端点必须逐字有据；
    错得离谱的区间合成由 C 仲裁与人工复核兜底——过严闸的代价是丢弃合规标注。
    """
    from app.discretion.extract import parse_amount
    from s3 import _text_numbers
    tokens = re.compile(r"(?:约|近|超过|至少|逾|不足|不低于)?[0-9０-９〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟两.,，]+[余多]?元(?:以上|以下)?")
    open_top = re.compile(r"上不封顶|以上|超过|至少|逾|不低于|余|多")
    # 2026-10-26 金额硬闸修复（后处理线公告任务1）：
    # 1) 区间短语级扫描——"赌注10至100元"左端省略单位，单 token 扫描只见"100元"；
    #    权威归一化已支持整短语区间，按短语入账（两端进 supported/mins，不进 points：
    #    区间端点不是可加总的确切数额）。
    # 2) "最低下注/押注"近邻开口——仅当"最低"+金额同短语时该数值才解释为下界开口；
    #    无金额 token 的"最低"（如"最低生活保障"）不会触发。
    range_phrase = re.compile(r"[0-9０-９〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟两.,，]+(?:至|到|—|–|~|-)[0-9０-９〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟两.,，]+元")
    floor_phrase = re.compile(r"最低(?:下注|押注|赌注|底注|注码)?\s*[0-9０-９〇零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟两.,，]+[余多]?元")
    additive_etc = re.compile(r"等")
    for name, item in payload.get("amounts", {}).items():
        if item["status"] == "未提及":
            continue
        supported = set()
        points = []       # 本字段证据内所有确切数额（可重复，供加总）
        mins = set()      # 单 token 下界集合
        quote_open = False
        quote_etc = False
        floor_open = False
        for ev in item["evidence"]:
            quote = ev.get("quote", "")
            if open_top.search(quote):
                quote_open = True
            if additive_etc.search(quote):
                quote_etc = True
            if floor_phrase.search(quote):
                floor_open = True
            for match in range_phrase.finditer(quote):
                value = parse_amount(match.group())
                if value is not None and value.min is not None:
                    supported.add((value.min, value.max))
                    mins.add(value.min)
            for match in tokens.finditer(quote):
                value = parse_amount(match.group())
                if value is not None:
                    supported.add((value.min, value.max))
                    if value.min is not None:
                        mins.add(value.min)
                        if value.max == value.min:
                            points.append(value.min)
                else:
                    # Exact upper/lowercase numerals supported by the existing S3 parser.
                    if not re.search(r"约|近|超过|至少|逾|不足|以上|以下|余|多", match.group()):
                        nums = list(_text_numbers(match.group(), "元"))
                        supported.update((n, n) for n in nums)
                        points.extend(nums)
                        mins.update(nums)
        value = item["value"]
        mn, mx = value["min"], value["max"]
        direct = (mn, mx) in supported
        ok = direct
        if not ok and mn is not None:
            if mx is None and mn in mins and (quote_open or floor_open):
                ok = True  # 开口上界：'上不封顶/以上'整引文或'最低下注'近邻短语，下界逐字有据
            elif mx is not None and mx >= mn and mn in points and mx in points:
                ok = True  # 多值列举合成区间：两端点都是证据内确切数额
            elif points and mn == sum(points) and (mx == sum(points) or (mx is None and quote_etc)):
                ok = True  # 指南加总：逐项列出合计；'等' → 上界开口
        if not ok:
            raise ValueError(f"numeric_evidence_unsupported:amounts.{name}")
        # E-05 归一化对账只对"单一数额直取"形态有效（2026-10-26 多句职责判定，公告任务2）：
        # 数值支持由**至少一条**引文承担；其余引文可承担主体/场景归属，不逐条强制等值——
        # 逐条 all 曾误杀"前两句他人付款、第三句渔利300元"的合法标注。
        # 本人绑定审查独立于本闸（binding pending 门负责），金额闸通过不等于归属成立。
        if direct:
            if not any(validate_amount_e05(value, ev.get("quote", "")) for ev in item["evidence"]):
                raise ValueError(f"e05_amount_mismatch:amounts.{name}")


def validate_located(payload, text_full: str, engine, regions=()) -> None:
    issues = engine.validate_teacher_output(payload, evidence_text=text_full, located=True)
    if issues:
        raise ValueError("invalid_candidate:" + ";".join(f"{i.field}:{i.code}" for i in issues))
    for group in payload.values():
        for item in group.values():
            for ev in item["evidence"]:
                if regions and not any(a <= ev["start"] < ev["end"] <= b for a, b in regions):
                    raise ValueError("evidence_outside_input")
    check_money_support(payload)


def merge_valid(a: dict, b: dict, engine, text_full: str, regions=(), c=None):
    """Keep the existing strict comparison; never default missing/invalid fields to absent."""
    validate_located(a, text_full, engine, regions)
    validate_located(b, text_full, engine, regions)
    if c is not None:
        validate_located(c, text_full, engine, regions)
    merged, differences, unresolved = {}, [], []
    for path in engine.FIELD_INFO:
        group, name = path.split(".")
        va, vb = a[group][name], b[group][name]
        def key(v):
            return (v["status"], digest(v["value"]),
                    frozenset((e["start"], e["end"]) for e in v["evidence"]))
        if key(va) == key(vb):
            chosen = va
        else:
            kind = ("status_difference" if va["status"] != vb["status"] else
                    "value_difference" if digest(va["value"]) != digest(vb["value"]) else "evidence_only")
            d = {"path": path, "kind": kind, "a": va, "b": vb}
            differences.append(d)
            if c is None:
                unresolved.append(d)
                continue
            chosen = c[group][name]
        merged.setdefault(group, {})[name] = copy.deepcopy(chosen)
    if not unresolved:
        validate_located(merged, text_full, engine, regions)
    return merged, unresolved, differences


# --- E-05 approval package integration ---

def validate_evidence_contract(payload: dict, text_full: str,
                               facts_text: str = "", meta_text: str = "",
                               *, located: bool = True) -> list:
    """E-05 证据语义校验（§3.10 全 6 条规则）。

    Call after S2 positioning, before storage. Returns list of EvidenceIssue.
    Empty list = pass. When facts_text and meta_text are both empty, source
    restriction checks are skipped (caller did not provide source context).
    """
    ec = evidence_contract()
    # When source texts are unavailable, disable source restriction checks
    # to avoid false positives on legitimate evidence.
    effective_facts = facts_text if facts_text else text_full
    effective_meta = meta_text if meta_text else ""
    record = {"id": "?", "input": {"text_full": text_full,
              "facts_text": effective_facts, "meta_text": effective_meta},
              "elements": payload}
    return ec.EvidenceValidator().validate_record(record, located=located)


def normalize_amount_e05(text: str) -> dict | None:
    """E-05 权威金额归一化。返回 {"min": float, "max": float|None} 或 None。"""
    return normalization_spec().normalize_amount(text)


def normalize_date_e05(text: str):
    """E-05 权威日期归一化。返回 (date, status) 或 None。"""
    return normalization_spec().normalize_date(text)


def normalize_duration_e05(text: str) -> float | None:
    """E-05 权威持续时间归一化（天）。"""
    return normalization_spec().normalize_duration(text)


def validate_amount_e05(normalized: dict, evidence_text: str) -> bool:
    """E-05 金额归一化对账。True=一致或无法机械对账。"""
    return normalization_spec().validate_amount_against_source(normalized, evidence_text)


def validate_date_e05(normalized_iso: str, evidence_text: str) -> bool:
    """E-05 日期归一化对账。True=一致或无法解析。"""
    return normalization_spec().validate_date_against_source(normalized_iso, evidence_text)
