"""Regression tests for the reviewed failures; all source examples are synthetic."""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from element_contract import compile_references, reference_schema, merge_valid, messages, contract_snapshot, digest
from run_elements import build_inputs, ENGINE, _candidates, locate_evidence
from locate import OffsetIndex
from durable_calls import DurableCalls, read_rows, check_models
from freeze_slice import build_slice
from run_seg import request_for, validated_output
from s1 import ProviderResponseError
from to_unified import convert
from replay_pipeline import assemble
from durable_calls import append


def absent():
    result = {}
    for path in ENGINE.FIELD_INFO:
        g, n = path.split(".")
        result.setdefault(g, {})[n] = {"status": "未提及", "value": None, "evidence": []}
    return result


def view():
    text = "甲带赌资100元。决定罚款500元。"
    return text, {"target": "甲", "aliases": [], "sentence_view": [
        {"id": "S1.1", "text": text[:9], "start": 0, "end": 9, "type": "facts"}]}


def valued():
    p = absent()
    p["amounts"]["personal_stake"] = {"status": "明确", "value": {"min": 100, "max": 100},
                                     "evidence": [{"sentence_ids": ["S1.1"]}]}
    return p


def test_reference_compile_cannot_read_decision_or_other_record():
    text, inp = view()
    p = valued()
    compiled = compile_references(p, inp, text, ENGINE)
    assert compiled["amounts"]["personal_stake"]["evidence"] == [{"quote": text[:9], "start": 0, "end": 9}]
    p["amounts"]["personal_stake"]["evidence"][0]["sentence_ids"] = ["S2.1"]
    with pytest.raises(ValueError, match="not_allowed"):
        compile_references(p, inp, text, ENGINE)


@pytest.mark.parametrize("change", ["missing", "flat", "extra", "enum", "absent_value"])
def test_invalid_payload_never_becomes_absent(change):
    text, inp = view()
    p = absent()
    if change == "missing":
        del p["conduct"]
    elif change == "flat":
        p = {"conduct.role": p["conduct"]["role"]}
    elif change == "extra":
        p["answer"] = {}
    elif change == "enum":
        p["conduct"]["role"] = {"status": "明确", "value": "随意角色", "evidence": [{"sentence_ids": ["S1.1"]}]}
    else:
        p["conduct"]["times"]["value"] = 3
    with pytest.raises(ValueError):
        compile_references(p, inp, text, ENGINE)


def test_valid_absent_and_c_new_value_use_same_final_contract():
    text, inp = view()
    a = compile_references(absent(), inp, text, ENGINE)
    b = compile_references(valued(), inp, text, ENGINE)
    _, unresolved, _ = merge_valid(a, b, ENGINE, text, [(0, 9)])
    assert len(unresolved) == 1
    c = copy.deepcopy(b)
    c["amounts"]["personal_stake"]["evidence"] = []
    with pytest.raises(ValueError):
        merge_valid(a, b, ENGINE, text, [(0, 9)], c)


def test_complete_schema_and_target_are_in_c_request():
    _, inp = view()
    request = messages(ENGINE, inp, decisions=[{"path": "conduct.role"}])
    assert '"enum"' in request[0]["content"]
    assert json.loads(request[1]["content"])["target"] == "甲"
    assert len(reference_schema(ENGINE)["required"]) == 7


def test_present_but_wrong_money_cannot_pass_by_citing_any_source_sentence():
    text, inp = view()
    p = valued()
    p["amounts"]["personal_stake"]["value"] = {"min": 500, "max": 500}
    with pytest.raises(ValueError, match="numeric_evidence_unsupported"):
        compile_references(p, inp, text, ENGINE)


def test_projection_keeps_last_character_and_skips_deleted_gap():
    text = "导航甲赌删除资100元。决定罚款。"
    deleted = [[0, 2, "nav"], [4, 2, "noise"]]
    index = OffsetIndex({"orig_len": len(text), "deletes": deleted})
    cleaned = "甲赌资100元。决定罚款。"
    split = cleaned.index("。") + 1
    rec = {"subject_mention": "甲", "text_orig_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "_text_full": text, "sentences": [[0, split], [split, len(cleaned)]]}
    inp = build_inputs(rec, {"zones": [{"type": "facts", "from": 1, "to": 1},
                                     {"type": "decision", "from": 2, "to": 2}]}, index)
    assert inp["facts_text"] == "甲赌\n资100元。"
    assert "决定" not in inp["facts_text"] and "删除" not in inp["facts_text"]
    assert all(text[a:b] == s["text"] for s, (a, b) in zip(inp["sentence_view"], inp["regions"]))


@pytest.mark.parametrize("a,b", [(-1, 1), (0, 0), (1, 0), (0, 4), (True, 2)])
def test_invalid_half_open_coordinates_rejected(a, b):
    with pytest.raises(IndexError):
        OffsetIndex({"orig_len": 3, "deletes": []}).span(a, b)


def test_unique_quote_outside_input_is_rejected():
    assert locate_evidence("罚款500元", "甲赌博。罚款500元", [(0, 4)]) is None


class FakeProvider:
    base_url = "https://api.example.test/v1"
    model, max_tokens, temperature = "fake", 30, 0
    def __init__(self, content='{"ok":true}', error=None):
        self.content, self.error, self.calls = content, error, 0
    def chat(self, *args):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return self.content, {"usage": {"prompt_tokens": 10, "completion_tokens": 10}}


def call_runner(tmp_path, provider, **overrides):
    kw = dict(prices={"fake": {"input": 1, "output": 1}}, cap=1,
              max_calls=3, max_input_bytes=10000, execute=True)
    kw.update(overrides)
    return DurableCalls(tmp_path, {"A": provider}, **kw)


MSG = [{"role": "system", "content": "JSON"}, {"role": "user", "content": "x"}]


def test_raw_survives_parse_failure_and_replay_never_calls_again(tmp_path):
    provider = FakeProvider("broken")
    run = call_runner(tmp_path, provider)
    with pytest.raises(ValueError):
        run.call("A", MSG, context={"id": "1"}, validator=lambda p: None, repairs=0)
    assert read_rows(tmp_path / "raws.jsonl")[0]["content"] == "broken"
    resumed = call_runner(tmp_path, provider, execute=False)
    with pytest.raises(ValueError, match="cached_invalid"):
        resumed.call("A", MSG, context={"id": "1"}, validator=lambda p: None)
    assert provider.calls == 1


def test_success_reuses_durable_raw_after_restart(tmp_path):
    provider = FakeProvider()
    for _ in range(2):
        assert call_runner(tmp_path, provider).call("A", MSG, context={}, validator=lambda p: None)["ok"]
    assert provider.calls == 1


def test_empty_http_success_retains_usage_and_is_not_resubmitted(tmp_path):
    class EmptyProvider(FakeProvider):
        def chat(self, *args):
            self.calls += 1
            raise ProviderResponseError("empty", "", {"usage": {
                "prompt_tokens": 10, "completion_tokens": 20}})
    provider = EmptyProvider()
    with pytest.raises(ValueError):
        call_runner(tmp_path, provider).call("A", MSG, context={}, validator=lambda p: None, repairs=0)
    assert read_rows(tmp_path / "raws.jsonl")[0]["content"] == ""
    events = read_rows(tmp_path / "attempts.jsonl")
    assert events[-1]["event"] == "finished" and events[-1]["usage"]["completion_tokens"] == 20
    with pytest.raises(ValueError, match="cached_invalid"):
        call_runner(tmp_path, provider, execute=False).call("A", MSG, context={}, validator=lambda p: None)
    assert provider.calls == 1


def test_invalid_output_repairs_once_and_resume_does_not_buy_more_repairs(tmp_path):
    provider = FakeProvider("broken")
    for _ in range(2):
        with pytest.raises(ValueError):
            call_runner(tmp_path, provider).call("A", MSG, context={}, validator=lambda p: None)
    assert provider.calls == 2


def test_unknown_timeout_not_automatically_resubmitted(tmp_path):
    provider = FakeProvider(error="TimeoutError")
    with pytest.raises(RuntimeError):
        call_runner(tmp_path, provider).call("A", MSG, context={}, validator=lambda p: None)
    provider.error = None
    with pytest.raises(RuntimeError, match="unknown_remote_outcome"):
        call_runner(tmp_path, provider).call("A", MSG, context={}, validator=lambda p: None)
    assert provider.calls == 1


def test_budget_reserves_before_network(tmp_path):
    provider = FakeProvider()
    with pytest.raises(RuntimeError, match="budget_stop"):
        call_runner(tmp_path, provider, cap=.000001).call("A", MSG, context={}, validator=lambda p: None)
    assert provider.calls == 0


def test_fatal_provider_stays_disabled_after_restart(tmp_path):
    provider = FakeProvider(error="HTTP 402")
    with pytest.raises(RuntimeError):
        call_runner(tmp_path, provider).call("A", MSG, context={"id": "1"}, validator=lambda p: None)
    provider.error = None
    with pytest.raises(RuntimeError, match="provider_disabled"):
        call_runner(tmp_path, provider).call("A", MSG, context={"id": "2"}, validator=lambda p: None)
    assert provider.calls == 1


def test_public_s1_request_does_not_ask_for_model_zones():
    rec = {"id": "T1", "cleaned_text": "甲赌博。", "sentences": [[0, 4]],
           "source_type": "执法公示", "form": "字段表公示", "subject_mention": "甲",
           "zones_det": [{"type": "facts", "from": 1, "to": 1}]}
    msg = request_for(rec)
    assert '"zones"' not in msg[0]["content"]
    payload = {"outcome": {"type": "罚款", "fine": 500, "detention_days": 0},
               "gambling": {"verdict": "是"}, "dates": {}, "subject": {"mention": "甲"},
               "confidence": "high", "review": {"result": "无"}}
    assert validated_output(payload, rec)["zones"] == rec["zones_det"]
    payload["outcome"]["type"] = "非法类型"
    with pytest.raises(ValueError, match="S1_invalid"):
        validated_output(payload, rec)


def test_slice_rejects_answer_and_keeps_event_siblings_together(tmp_path):
    rows = []
    for i, facts in enumerate(["甲以麻将赌博。", "乙以扑克赌博。", "丙决定罚款500元。"]):
        rows.append({"id": f"T{i}", "text_full": facts + "决定给予罚款500元。", "text_facts": facts,
                     "text_decision": "决定给予罚款500元。",
                     "subject_mention": "甲乙丙"[i], "event_key": "same-event", "doc_no_hash": f"doc{i}",
                     "outcome": {"type": "罚款", "fine": 500, "detention_days": 0},
                     "quality": {"tier": "L1-金标候选", "in_scope": True}})
    source = tmp_path / "source.jsonl"
    source.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    out = tmp_path / "slice"
    report = build_slice([source], out)
    assert report["records"] == 2 and report["events"] == 1
    records = read_rows(out / "records.jsonl")
    assert len({r["development_split"] for r in records}) == 1
    assert all(r["reference_elements"] is None and not r["release_approved"] for r in records)
    assert any("penalty_amount" in r["reasons"] for r in report["excluded"])
    with pytest.raises(FileExistsError):
        build_slice([source], out)


def test_offline_assembly_attaches_only_valid_same_context_candidate(tmp_path):
    text = "甲参与赌博。决定给予甲罚款500元。"
    src = {"id": "T1", "source": "公开网页", "source_type": "处罚决定书",
           "subject_mention": "甲", "text_full": text, "text_facts": "甲参与赌博。",
           "text_decision": "决定给予甲罚款500元。", "text_review": "",
           "doc_no_hash": "synthetic-doc", "authority": "某公安局",
           "behavior_date": None, "decision_date": None, "harvest_date": "2026-10-18",
           "quality": {"tier": "L1", "gambling": "是", "in_scope": True},
           "outcome": {"type": "罚款", "fine": 500, "detention_days": 0}}
    source = tmp_path / "source.jsonl"
    append(source, src)
    unified = tmp_path / "unified"
    convert(str(source), None, str(unified))
    rec = read_rows(unified / "records.jsonl")[0]
    sentences = rec["sentences"]
    boundary = next(i for i, (a, b) in enumerate(sentences, 1) if "决定" in rec["cleaned_text"][a:b])
    output = {"zones": [{"type": "facts", "from": 1, "to": boundary - 1},
                        {"type": "decision", "from": boundary, "to": len(sentences)}],
              "subject": {"mention": "甲", "aliases": []}, "outcome": src["outcome"],
              "dates": {}, "gambling": {"verdict": "是"}, "confidence": "high", "review": {"result": "无"}}
    run = tmp_path / "run"
    run.mkdir()
    append(run / "outputs.jsonl", {"id": "T1", "ok": True, "output": output})
    rec["_text_full"] = text
    inp = build_inputs(rec, output, OffsetIndex(read_rows(unified / "edits.rle.jsonl")[0]))
    elements = tmp_path / "elements"
    elements.mkdir()
    label = {"id": "T1", "status": "valid", "view_hash": inp["view_hash"],
             "contract_hash": digest(contract_snapshot(ENGINE)),
             "input": {k: inp[k] for k in ("target", "facts_text", "meta_text")},
             "elements": compile_references(absent(), inp, text, ENGINE),
             "element_schema_version": ENGINE.SCHEMA_VERSION, "element_prompt_version": ENGINE.PROMPT_VERSION}
    label["input"]["text_orig_sha256"] = rec["text_orig_sha256"]
    label_path = elements / "record-T1.json"
    label_path.write_text(json.dumps(label, ensure_ascii=False), "utf-8")
    out = tmp_path / "parsed2"
    report = assemble(unified / "records.jsonl", source, run, out, elements=elements)
    assert report["parsed2_candidate_records"] == 1
    row = read_rows(out / "records.jsonl")[0]
    assert row["elements_status"] == "candidate_validated" and not row["release_approved"]
    assert row["source_observed_outcome"] == src["outcome"]
    label["input"]["target"] = "乙"
    label_path.write_text(json.dumps(label, ensure_ascii=False), "utf-8")
    rejected = assemble(unified / "records.jsonl", source, run, tmp_path / "rejected", elements=elements)
    assert rejected["parsed2_candidate_records"] == 0
    assert read_rows(tmp_path / "rejected/excluded.jsonl")[0]["reason"] == "element_commit_input_mismatch"


# ---------- 2026-10-20 CLI 审计修复的守卫 ----------

from element_contract import (MODEL_QUALITY_PREFIXES, is_model_quality_failure,
                              prompt_fingerprint, system_prompt)
from run_elements import manifest_matches, preflight_request_sizes, acquire_run_lock
from process_guard import process_alive
from durable_calls import is_not_sent
from budget_scope import BudgetScope


@pytest.mark.parametrize("prefix", MODEL_QUALITY_PREFIXES)
def test_model_quality_prefixes_are_isolated(prefix):
    assert is_model_quality_failure(ValueError(prefix + "amounts.fine"))


@pytest.mark.parametrize("msg", ["budget_stop: 预留超限", "unknown_remote_outcome: 先核账",
                                 "request_too_large: 超限", "provider_disabled",
                                 "concurrent_task_exists", "shared_budget_stop",
                                 "reservation_exceeded", "unsafe_record_id"])
def test_pipeline_level_failures_never_isolated(msg):
    assert not is_model_quality_failure(RuntimeError(msg))
    assert not is_model_quality_failure(ValueError(msg))


def test_jsondecode_counts_as_model_quality():
    assert is_model_quality_failure(json.JSONDecodeError("x", "x", 0))


def test_wire_envelope_transmits_stable_fingerprint_not_bundle_hash():
    _, inp = view()
    msgs = messages(ENGINE, inp)
    assert msgs[0]["content"] == system_prompt(ENGINE)
    user = json.loads(msgs[1]["content"])
    assert user["prompt_fingerprint"] == digest(prompt_fingerprint(ENGINE))
    assert "contract_bundle_hash" not in user


def test_prompt_fingerprint_isolates_validators_from_cache_identity():
    fp = prompt_fingerprint(ENGINE)
    snapshot = contract_snapshot(ENGINE)
    assert "implementation" not in fp
    assert digest(fp) != digest(snapshot)


def test_e05_authority_files_are_in_contract_snapshot():
    deps = " ".join(contract_snapshot(ENGINE)["dependencies"])
    for name in ("normalization_spec.py", "evidence_contract.py", "binding_rules.py"):
        assert name in deps, name


def test_manifest_resume_identity_ignores_implementation_drift():
    frozen = {"version": "v", "prompt_fingerprint": "fp", "ids": ["A"], "views": {"A": "h"},
              "source_hashes": {"s": "x"}, "contract": {"implementation": {"run_elements.py": "1"}},
              "input_mode": "m"}
    drifted = {**frozen, "contract": {"implementation": {"run_elements.py": "2"}}}
    assert manifest_matches(drifted, frozen)
    assert not manifest_matches({**frozen, "ids": ["B"]}, frozen)
    assert not manifest_matches({**frozen, "prompt_fingerprint": "other"}, frozen)
    assert not manifest_matches({k: v for k, v in frozen.items() if k != "prompt_fingerprint"}, frozen)


def test_preflight_names_oversized_records_before_any_spend():
    _, inp = view()
    sizes = preflight_request_sizes([("T1", {}, inp)])
    assert sizes["T1"] >= len(system_prompt(ENGINE).encode("utf-8"))
    # 口径一致：闸判定与 DurableCalls 内的 request_too_large 完全同源（+1024 framing）
    assert sum(len(m["content"].encode("utf-8")) for m in messages(ENGINE, inp)) + 1024 == sizes["T1"]
    assert [rid for rid, s in sizes.items() if s > 1000] == ["T1"]
    assert [rid for rid, s in sizes.items() if s > 10 ** 9] == []


@pytest.mark.parametrize("err,expected", [
    ("URLError: <urlopen error [Errno 11004] getaddrinfo failed>", True),
    ("URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>", True),
    ("ConnectionRefusedError: refused", True),
    ("TimeoutError: timed out", False),
    ("HTTP 402: Insufficient Balance", False),
    ("RemoteDisconnected: Connection reset", False)])
def test_not_sent_classification_is_conservative(err, expected):
    assert is_not_sent(err) is expected


def test_not_sent_failure_releases_reservation_without_manual_reconcile(tmp_path):
    provider = FakeProvider(error="[Errno 11004] getaddrinfo failed")
    scope = BudgetScope(tmp_path / "b", cap=10, max_calls=5)
    run = DurableCalls(tmp_path, {"A": provider}, prices={"fake": {"input": 1, "output": 1}},
                       cap=1, max_calls=3, max_input_bytes=10000, execute=True, budget_scope=scope)
    with pytest.raises(RuntimeError):
        run.call("A", MSG, context={"id": "1"}, validator=lambda p: None)
    assert run.unknown == set() and run.reserved == 0 and run.used_calls == 0
    assert scope.snapshot()["used_or_reserved"] == 0 and scope.snapshot()["unknown_keys"] == []
    provider.error = None
    assert run.call("A", MSG, context={"id": "1"}, validator=lambda p: None)["ok"]
    assert provider.calls == 2
    resumed = call_runner(tmp_path, provider)
    assert resumed.unknown == set() and resumed.used_calls == 1


def test_timeout_failure_still_holds_unknown_and_reserve(tmp_path):
    provider = FakeProvider(error="TimeoutError: timed out")
    run = call_runner(tmp_path, provider)
    with pytest.raises(RuntimeError):
        run.call("A", MSG, context={"id": "t"}, validator=lambda p: None)
    assert run.unknown and run.reserved > 0


def test_finished_recovered_from_raw_without_new_call(tmp_path):
    append(tmp_path / "attempts.jsonl", {"event": "submitted", "key": "k1", "attempt_id": "k1:1",
                                         "reservation": 0.5, "provider": "test", "model": "fake",
                                         "context": {"id": "r"}, "request_hash": "h",
                                         "price": {"input": 1, "output": 1}})
    append(tmp_path / "raws.jsonl", {"key": "k1", "attempt_id": "k1:1", "content": "{\"ok\": true}",
                                     "meta": {"usage": {"prompt_tokens": 10, "completion_tokens": 20}},
                                     "context": {"id": "r"}, "provider": "test", "model": "fake"})
    seen = []
    provider = FakeProvider(error="must-not-be-called")
    run = DurableCalls(tmp_path, {"A": provider}, prices={"fake": {"input": 1, "output": 1}},
                       cap=1, max_calls=3, max_input_bytes=10000, execute=True,
                       on_finish=lambda m, u: seen.append((m, u)))
    assert run.unknown == set() and provider.calls == 0 and seen == [("fake", {"prompt_tokens": 10, "completion_tokens": 20})]
    assert abs(run.reserved - (30 / 1e6)) < 1e-9
    finished = [e for e in read_rows(tmp_path / "attempts.jsonl") if e["event"] == "finished"]
    assert finished[0]["recovered_from_raw"] is True


def test_acquire_run_lock_distinguishes_live_and_dead_holder(tmp_path):
    lock = tmp_path / "RUNNING.lock"
    lock.write_text("999999999")
    with pytest.raises(RuntimeError, match="stale_running_lock"):
        acquire_run_lock(tmp_path)
    acquired = acquire_run_lock(tmp_path, take_over=True)
    assert int(acquired.read_text()) == os.getpid() and process_alive(os.getpid())
    acquired.unlink()
    acquired.write_text(str(os.getpid()))
    with pytest.raises(RuntimeError, match="running_elsewhere"):
        acquire_run_lock(tmp_path, take_over=True)
    acquired.unlink()


def test_writer_lock_takeover_when_holder_dead(tmp_path):
    scope = BudgetScope(tmp_path / "b", cap=10, max_calls=5)
    (tmp_path / "b" / "WRITER.lock").write_text("999999999")
    scope.reserve("k1", 1.0, owner="x")            # 死亡持有者：自动清锁重入，不再 5 秒超时
    assert scope.snapshot()["calls"] == 1


def test_status_element_summary_synthesizes_ledger_state(tmp_path):
    from status import element_summary
    (tmp_path / "manifest.json").write_text('{"contract": {}}', encoding="utf-8")
    (tmp_path / "plan.json").write_text('{"eligible": 2}', encoding="utf-8")
    for row in [{"event": "submitted", "key": "k1", "attempt_id": "a1", "reservation": .1},
                {"event": "submitted", "key": "k2", "attempt_id": "a2", "reservation": .2},
                {"event": "finished", "key": "k1", "attempt_id": "a1", "charged": .05},
                {"event": "submitted", "key": "k3", "attempt_id": "a3", "reservation": .3},
                {"event": "released", "key": "k3", "attempt_id": "a3"}]:
        append(tmp_path / "attempts.jsonl", row)
    for row in [{"id": "r1", "status": "valid"}, {"id": "r2", "status": "invalid"}]:
        append(tmp_path / "diagnostics.jsonl", row)
    (tmp_path / "record-r1.json").write_text("{}", encoding="utf-8")
    el = element_summary(tmp_path)
    assert el["done"] == 1 and el["valid"] == 1 and el["invalid"] == 1
    assert el["calls"] == 2 and el["unknown"] == 1 and el["charged"] == 0.05
    assert el["reserved"] == 0.2 and el["phase"] == "idle"


def test_manual_settle_closes_unknown_only_with_evidence(tmp_path):
    from audit_run import settle
    scope_root = tmp_path / "b"
    scope = BudgetScope(scope_root, cap=10, max_calls=5)
    append(tmp_path / "attempts.jsonl", {"event": "submitted", "key": "k1", "attempt_id": "a1",
                                         "reservation": 0.3, "provider": "test", "model": "fake",
                                         "context": {}, "request_hash": "h",
                                         "price": {"input": 1, "output": 1}})
    scope.reserve("k1", 0.3, owner=str(tmp_path))
    with pytest.raises(ValueError, match="settlement_requires_evidence"):
        settle(tmp_path, "a1", 0.0, evidence="", scope_dir=scope_root)
    with pytest.raises(ValueError, match="implausible_charged"):
        settle(tmp_path, "a1", 5.0, evidence="console", scope_dir=scope_root)
    with pytest.raises(ValueError, match="unknown_attempt_id"):
        settle(tmp_path, "nope", 0.0, evidence="console", scope_dir=scope_root)
    row = settle(tmp_path, "a1", 0.12, evidence="provider-console-2026-10-20", scope_dir=scope_root)
    assert row["manual_reconcile"] is True
    resumed = call_runner(tmp_path, FakeProvider(error="must-not-be-called"))
    assert resumed.unknown == set() and abs(resumed.reserved - 0.12) < 1e-9
    with pytest.raises(ValueError, match="already_finished"):
        settle(tmp_path, "a1", 0.0, evidence="again", scope_dir=scope_root)
    assert scope.snapshot()["used_or_reserved"] == 0.12


# ---------- runner 端到端离线演练（fake 调用层，零网络） ----------

class FakeCalls:
    def __init__(self, fail=None):
        self.used_calls, self.fail = 0, fail
    def call(self, name, msgs, *, context, validator, repairs=1):
        self.used_calls += 1
        if self.fail:
            raise self.fail
        return copy.deepcopy(absent())


def runner_env(tmp_path, monkeypatch, fail=None):
    import run_elements as RE
    data = tmp_path / "data"
    (data / "s1_runs").mkdir(parents=True)
    monkeypatch.setattr(RE, "data_root", lambda: data)
    monkeypatch.setattr(RE, "from_order", lambda order, root: None)
    monkeypatch.setattr(RE, "freeze_execution", lambda *a, **k: {})
    monkeypatch.setattr(RE, "check_models", lambda *a, **k: None)
    monkeypatch.setattr(RE, "load_config", lambda: ({"p": SimpleNamespace(
        base_url="https://api.example.test/v1", model="fake", max_tokens=1000, temperature=0)}, {}, "cfg"))
    monkeypatch.setattr(RE, "load_prices", lambda path: {"fake": {"input": 1, "output": 1}})
    text, inp = view()
    full = {**inp, "facts_text": text[:9], "meta_text": "", "regions": [(0, 9)],
            "view_hash": digest(inp["sentence_view"])}
    rec = {"text_orig_sha256": hashlib.sha256(text.encode()).hexdigest(), "_text_full": text}
    monkeypatch.setattr(RE, "load_work", lambda run, unified, parsed: ([("T1", rec, full)], []))
    run_dir = data / "s1_runs" / "src"
    run_dir.mkdir()
    (run_dir / "outputs.jsonl").write_text("{}\n", encoding="utf-8")
    unified = data / "s1_runs" / "u.jsonl"
    unified.write_text("{}\n", encoding="utf-8")
    (data / "s1_runs" / "edits.rle.jsonl").write_text("{}\n", encoding="utf-8")
    parsed = data / "s1_runs" / "p.jsonl"
    parsed.write_text("{}\n", encoding="utf-8")
    out = data / "s1_runs" / "e2e"
    order = {"stage": "smoke12", "cap": 1.0, "max_calls": 96, "max_input_bytes": 400000,
             "providers": {"A": "p", "B": "p", "C": "p"}, "ids": ["T1"],
             "contract_hash": digest(RE.prompt_fingerprint(RE.ENGINE)),
             "review_record": "r", "executor_review": "e", "engine_ack": "a",
             "free_replay_pass": True,
             "budget_scope": {"path": str(data / "s1_runs" / "scope"), "cap": 10, "max_calls": 50}}
    order_file = tmp_path / "order.json"
    order_file.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
    fake = FakeCalls(fail=fail)
    monkeypatch.setattr(RE, "DurableCalls", lambda *a, **k: fake)
    monkeypatch.setattr(sys, "argv", ["run_elements.py", "--run", str(run_dir), "--unified", str(unified),
                                      "--parsed", str(parsed), "--out", str(out), "--execute",
                                      "--order", str(order_file)])
    return RE, out, fake


def test_e2e_runner_happy_path_writes_commit_and_done_heartbeat(tmp_path, monkeypatch):
    RE, out, fake = runner_env(tmp_path, monkeypatch)
    RE.main()
    assert (out / "record-T1.json").exists()
    prog = json.loads((out / "progress.json").read_text("utf-8"))
    assert prog["phase"] == "done" and prog["ok"] == 1 and prog["kind"] == "l5-elements"
    assert not (out / "RUNNING.lock").exists()
    assert fake.used_calls == 2                      # A+B，absent==absent 无分歧不请 C


def test_e2e_runner_fatal_abort_is_diagnosed_not_masked(tmp_path, monkeypatch):
    RE, out, fake = runner_env(tmp_path, monkeypatch, fail=RuntimeError("budget_stop: 模拟预算拦截"))
    with pytest.raises(RuntimeError, match="budget_stop"):
        RE.main()
    diag = read_rows(out / "diagnostics.jsonl")
    assert diag[-1]["id"] == "T1" and "budget_stop" in diag[-1]["reason"]
    assert diag[-1]["status"] == "unresolved"
    prog = json.loads((out / "progress.json").read_text("utf-8"))
    assert prog["phase"] == "aborted" and not prog.get("done_masked_as_finished", False)
    assert prog["errors_recent"] and "budget_stop" in prog["errors_recent"][-1]["error"]
    assert not (out / "RUNNING.lock").exists()
    from status import element_summary
    assert element_summary(out)["phase"] == "aborted"


# ---------- 2026-10-26 金额硬闸修复（后处理线公告）守卫 ----------

from element_contract import check_money_support
from field_table import parse_fields


def _amount_item(value, quotes):
    return {"status": "明确", "value": value, "evidence": [{"quote": q} for q in quotes]}


def test_money_floor_phrase_rescues_minimum_bet():
    # 公告 S1-37324a：'最低下注10元' → {10,null} 是合法下界开口
    check_money_support({"amounts": {"per_bet": _amount_item(
        {"min": 10, "max": None}, ["现场赌局最低下注10元，多者不限"])}})


def test_money_range_phrase_with_open_top_rescues():
    # 公告 S1-38da：'赌注10至100元，上不封顶' 左端省略单位须按短语入账
    check_money_support({"amounts": {"per_bet": _amount_item(
        {"min": 10, "max": None}, ["赌注10至100元，上不封顶"])}})


def test_money_multiquote_value_quote_carries_number():
    # 公告 S1-0171：数值由一条引文承担，其余引文承担主体/场景归属，不逐条强制等值
    check_money_support({"amounts": {"commission": _amount_item(
        {"min": 300, "max": 300},
        ["龚x甲等人抽头，第一次抽头得200元", "第二次抽头得30元", "龚x甲共计渔利300元"])}})


@pytest.mark.parametrize("value,quotes", [
    ({"min": 2, "max": None}, ["扣张2元、自摸翻倍"]),                     # 公告 S1-0034：无开口词
    ({"min": 2000, "max": 2000}, ["每点代表十元，初始点数两百点"]),         # 公告 S1-e69f：乘积≠本人赌资
    ({"min": 800, "max": 800}, ["共抽头900余元", "事后给刘xx300元现金", "给王xx200元现金"]),  # 公告 S1-41e3
    ({"min": 10, "max": None}, ["最低生活保障发放10元"]),                  # '最低'无金额语境不得开口
])
def test_money_counterexamples_stay_rejected(value, quotes):
    with pytest.raises(ValueError):
        check_money_support({"amounts": {"amounts_x": _amount_item(value, quotes)}})


# ---------- 2026-10-26 L5-VIEW-01 person_block 起点收窄守卫 ----------

def _field_rec(line, target, facts="经查明，甲以麻将形式赌博。"):
    cleaned = line + "。" + facts
    return ({"subject_mention": target, "cleaned_text": cleaned,
             "sentences": [[0, len(line)], [len(line), len(cleaned)]]},
            {"zones": [{"type": "meta", "from": 1, "to": 1},
                       {"type": "facts", "from": 2, "to": 2}]})


def test_person_block_excludes_decision_title_and_doc_no():
    line = ("呼和浩特市公安局回民区分局行政处罚决定书呼公回（环）行罚决字〔2026〕84号"
            "违法行为人温某某，男，33岁，1990年1月1日出生，户籍所在地：丰镇市某镇")
    rec, out = _field_rec(line, "温某某")
    blocks = [f for f in parse_fields(rec, out) if f["label"] == "person_block"]
    assert len(blocks) == 1
    assert "行政处罚决定书" not in blocks[0]["value"] and "84号" not in blocks[0]["value"]
    assert "温某某" in blocks[0]["value"] and blocks[0]["start"] > 0


def test_person_block_keeps_role_prefix_and_masked_target():
    line = ("岳阳市某区公安局公安行政处罚决定书屈公（青）决字[2023]第0268号"
            "被处罚人党**，男，居民身份证：**********，****年**月**日出生，户籍地：湖南省某市")
    rec, out = _field_rec(line, "党**")
    blocks = [f for f in parse_fields(rec, out) if f["label"] == "person_block"]
    assert len(blocks) == 1 and blocks[0]["value"].startswith("被处罚人")
    assert "党**" in blocks[0]["value"] and "行政处罚决定书" not in blocks[0]["value"]


def test_person_block_absent_without_identity_marker():
    line = "某局行政处罚决定书某公决字〔2026〕9号温某某被处以罚款五百元。"
    rec, out = _field_rec(line, "温某某")
    assert not [f for f in parse_fields(rec, out) if f["label"] == "person_block"]
