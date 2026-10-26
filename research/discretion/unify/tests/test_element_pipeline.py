"""Regression tests for the reviewed failures; all source examples are synthetic."""
import copy
import hashlib
import json
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


def test_teacher_view_omits_penalty_header_but_keeps_target_meta():
    parts = ["处罚种类：罚款500元。", "行政相对人：张某。", "张某参与赌博。", "决定罚款500元。"]
    text = "".join(parts)
    ends = [sum(map(len, parts[:i])) for i in range(1, len(parts) + 1)]
    sentences = [[0, ends[0]], [ends[0], ends[1]], [ends[1], ends[2]], [ends[2], ends[3]]]
    rec = {"subject_mention": "张某", "text_orig_sha256": hashlib.sha256(text.encode()).hexdigest(),
           "_text_full": text, "cleaned_text": text, "sentences": sentences}
    out = {"zones": [{"type": "meta", "from": 1, "to": 2},
                     {"type": "facts", "from": 3, "to": 3},
                     {"type": "decision", "from": 4, "to": 4}]}
    inp = build_inputs(rec, out, OffsetIndex({"orig_len": len(text), "deletes": []}))
    assert inp["meta_text"] == "行政相对人：张某。"
    assert inp["facts_text"] == "张某参与赌博。"
    assert "罚款" not in "\n".join(v["text"] for v in inp["sentence_view"])


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
    label["status"] = "needs_binding_review"
    label["binding_audit"] = {"counts": {"unverified": 1}}
    label_path.write_text(json.dumps(label, ensure_ascii=False), "utf-8")
    review = assemble(unified / "records.jsonl", source, run, tmp_path / "review", elements=elements)
    assert review["parsed2_candidate_records"] == 1
    review_row = read_rows(tmp_path / "review/records.jsonl")[0]
    assert review_row["elements_status"] == "candidate_needs_binding_review"
    assert "elements" not in review_row
    label["status"] = "valid"
    label["input"]["target"] = "乙"
    label_path.write_text(json.dumps(label, ensure_ascii=False), "utf-8")
    rejected = assemble(unified / "records.jsonl", source, run, tmp_path / "rejected", elements=elements)
    assert rejected["parsed2_candidate_records"] == 0
    assert read_rows(tmp_path / "rejected/excluded.jsonl")[0]["reason"] == "element_commit_input_mismatch"
