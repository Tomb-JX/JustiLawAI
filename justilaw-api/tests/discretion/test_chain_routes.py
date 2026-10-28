"""§3.12 settings / parse / extract / review：复用 S1 与要素链路，模型调用走网关（测试用假网关，不发真实请求）。"""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from app.auth import current_user
from app.discretion import chain
from app.main import app
from app.model_gateway import gateway
from app.store import discretion_runs_db, settings_db

TEXT = ("违法嫌疑人张三，男，1980年生。经查，2023年7月6日晚，张三在苏州市某镇棋牌室参与打麻将赌博，个人赌资600元。"
        "以上事实有张三陈述等证据证实。根据《治安管理处罚法》第七十条，决定对张三处以罚款500元。")
S1_OUT = {"zones": [{"type": "meta", "from": 1, "to": 1}, {"type": "facts", "from": 2, "to": 2},
                    {"type": "evidence", "from": 3, "to": 3}, {"type": "decision", "from": 4, "to": 4}],
          "subject": {"mention": "张三", "aliases": []},
          "outcome": {"type": "罚款", "detention_days": 0, "fine": 500, "not_executed": "否", "multi_violation": False,
                      "executed_penalty": {"detention_days": 0, "fine": 0}, "confiscation": [], "detention_items": [],
                      "articles": [{"text": "第七十条", "edition": "2012修正"}], "stated_circumstances": []},
          "dates": {"behavior": "2023-07-06", "decision": "2023-07-07"},
          "review": {"result": "无", "changed_outcome": None}, "gambling": {"verdict": "是", "reason": "打麻将赌博"},
          "prior_sentence_ids": [], "meta_fields": [], "confidence": "high"}


def element_payload():
    ns = chain.load()
    out = {}
    for path in ns.engine.FIELD_INFO:
        group, name = path.split(".")
        out.setdefault(group, {})[name] = {"status": "未提及", "value": None, "evidence": []}
    ev = [{"sentence_ids": ["S2.1"]}]
    out["conduct"]["behavior_type"] = {"status": "明确", "value": "参与赌博", "evidence": ev}
    out["conduct"]["method"] = {"status": "明确", "value": "麻将", "evidence": ev}
    out["conduct"]["gambling_form"] = {"status": "推断", "value": "其他", "evidence": ev}
    out["amounts"]["personal_stake"] = {"status": "明确", "value": {"min": 600, "max": 600}, "evidence": ev}
    return out


class FakeGateway:
    """按系统提示区分分段 / 抽取；script 里可放 'bad'（返回无法解析的内容）或 'error'（网络失败）。"""

    def __init__(self, segment=("ok",), extract=("ok",)):
        self.script = {"segment": list(segment), "extract": list(extract)}
        self.calls = []

    async def __call__(self, model_id, messages, params):
        slot = "segment" if "行政处罚文书的结构化抽取器" in messages[0]["content"] else "extract"
        step = self.script[slot].pop(0) if self.script[slot] else "ok"
        self.calls.append((slot, model_id, params))
        receipt = {"platform_model_id": model_id, "provider_id": "fake", "model": model_id.split("/")[-1],
                   "params": {k: params.get(k) for k in ("temperature", "seed")}, "status": "ok",
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "latency_ms": 1,
                   "request_sha256": "r" * 64, "response_sha256": "s" * 64}
        if step == "error":
            e = RuntimeError("连接超时")
            e.receipt = {**receipt, "status": "fail", "error": "连接超时"}
            raise e
        if step == "bad":
            return "不是 JSON", receipt
        return json.dumps(S1_OUT if slot == "segment" else element_payload(), ensure_ascii=False), receipt


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(discretion_runs_db, "data", {})
    monkeypatch.setattr(discretion_runs_db, "save", lambda: None)
    monkeypatch.setattr(settings_db, "data", {})
    monkeypatch.setattr(settings_db, "save", lambda: None)
    monkeypatch.setattr(gateway.provider_store, "all_models",
                        lambda capability=None: [{"id": "fake/a"}, {"id": "fake/b"}])
    monkeypatch.setattr(gateway.provider_store, "default_model", lambda kind: "fake/a")
    fake = FakeGateway()
    monkeypatch.setattr(gateway, "call_json", fake)
    app.dependency_overrides[current_user] = lambda: {"id": "u1", "role": "user"}
    yield TestClient(app), fake, monkeypatch
    app.dependency_overrides.clear()


def job(client, path, body):
    """提交 → 202 + run_id → 轮询一次（TestClient 中后台任务在响应返回前已执行完）。"""
    r = client.post(path, json=body)
    assert r.status_code == 202, r.text
    sub = r.json()["data"]
    assert sub["status"] == "running" and sub["poll"].endswith(sub["run_id"])
    return client.get(sub["poll"]).json()["data"]


def done(client, path, body):
    run = job(client, path, body)
    assert run["status"] == "succeeded", run.get("error")
    return {"run_id": run["run_id"], **run["result"]}


def as_admin():
    app.dependency_overrides[current_user] = lambda: {"id": "adm", "role": "admin"}


def test_settings_slots_validate_and_require_admin(env):
    client, _, _ = env
    got = client.get("/api/v1/discretion/settings").json()["data"]
    assert got["models"]["segment"]["effective_model_id"] == "fake/a" and got["chain"]["available"]
    assert got["chain"]["segment_prompt"]["version"] == "seg-v2"
    body = {"models": {"extract": {"model_id": "fake/b", "params": {"temperature": 0.1}}}}
    assert client.put("/api/v1/discretion/settings", json=body).status_code == 403
    as_admin()
    data = client.put("/api/v1/discretion/settings", json=body).json()["data"]
    assert data["models"]["extract"]["effective_model_id"] == "fake/b"
    assert data["models"]["extract"]["params"]["temperature"] == 0.1 and data["models"]["extract"]["params"]["seed"]
    bad = {"models": {"extract": {"model_id": "nope/x", "params": {"api_key": "x"}}}}
    assert client.put("/api/v1/discretion/settings", json=bad).status_code == 422


def test_parse_returns_zones_and_model_receipts(env):
    client, fake, _ = env
    data = done(client, "/api/v1/discretion/parse", {"text": TEXT, "doc_kind": "决定书"})
    assert len(data["sentences"]) == 4 and data["zones"][1]["type"] == "facts"
    assert data["outcome"]["type"] == "罚款" and data["validation"]["ok"]
    call = data["trace"]["model_calls"][0]
    assert call["slot"] == "segment" and call["prompt"]["version"] == "seg-v2" and call["usage"]
    assert fake.calls[0][2]["json"] is True and fake.calls[0][2]["temperature"] == 0


def test_parse_retries_with_feedback_then_falls_back(env):
    client, fake, _ = env
    as_admin()
    client.put("/api/v1/discretion/settings", json={"models": {"segment": {"fallback_model_id": "fake/b"}}})
    fake.script["segment"] = ["bad", "error", "ok"]
    calls = done(client, "/api/v1/discretion/parse", {"text": TEXT})["trace"]["model_calls"]
    assert [c["status"] for c in calls] == ["ok", "fail", "ok"] and calls[0]["validation"]["ok"] is False
    assert calls[-1]["platform_model_id"] == "fake/b"


def test_parse_failure_is_reported_on_poll_with_receipts(env):
    client, fake, _ = env
    fake.script["segment"] = ["error", "error"]
    run = job(client, "/api/v1/discretion/parse", {"text": TEXT})
    assert run["status"] == "failed" and run["error"]["code"] == 50200 and run["error"]["http_status"] == 502
    assert len(run["partial"]["model_calls"]) == 2 and run["finished_at"]


def test_extract_from_parse_run_gives_evidence_and_assess_input(env):
    client, fake, _ = env
    run_id = done(client, "/api/v1/discretion/parse", {"text": TEXT, "doc_kind": "决定书"})["run_id"]
    data = done(client, "/api/v1/discretion/extract", {"parse_run_id": run_id, "region": "320582"})
    assert [c[0] for c in fake.calls] == ["segment", "extract"]          # 不重复分段
    stake = data["elements"]["amounts.personal_stake"]
    assert stake["value"] == {"min": 600, "max": 600} and stake["evidence"][0]["sentence"] == 2
    assert "600元" in stake["evidence"][0]["quote"] and stake["fact_field"] == "personal_stake"
    ai = data["assess_input"]
    assert ai["behavior_date"] == "2023-07-06" and ai["region"] == "320582" and ai["method"] == "麻将"
    assert ai["provenance"]["personal_stake"]["origin"] == "extracted"
    assert data["trace"]["model_calls"][0]["prompt"]["version"] == chain.load().engine.PROMPT_VERSION
    assessed = client.post("/api/v1/discretion/assess", json=ai).json()["data"]
    assert assessed["written"]["type"] == "罚款"
    assert assessed["trace"]["inputs"]["elements"]["personal_stake"]["origin"] == "extracted"


def test_review_from_decision_text(env):
    client, _, _ = env
    data = done(client, "/api/v1/discretion/review", {"text": TEXT, "region": "320582"})
    assert data["actual"] == {"type": "罚款", "detention_days": None, "fine": 500}
    levels = {lv["level"]: lv for lv in data["deviation"]["levels"]}
    assert levels["legal_space"]["ok"] and levels["written_band"]["ok"] and "未发现偏离" in data["deviation"]["summary"]
    assert len(data["trace"]["model_calls"]) == 2 and data["parse"]["outcome"]["fine"] == 500
    assert discretion_runs_db.data[data["run_id"]]["kind"] == "review"


def test_review_missing_date_keeps_paid_results(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setitem(S1_OUT, "dates", {"behavior": None, "decision": None})
    run = job(client, "/api/v1/discretion/review", {"text": TEXT, "region": "320582"})
    assert run["status"] == "failed" and run["error"]["code"] == 42200 and "behavior_date" in run["error"]["message"]
    assert run["partial"]["extraction"]["elements"] and len(run["partial"]["model_calls"]) == 2


def test_review_from_confirmed_elements_needs_no_model(env):
    client, fake, _ = env
    body = {"elements": {"behavior_date": "2023-07-06", "region": "320582", "behavior_type": "参与赌博",
                         "method": "麻将", "gambling_form": "其他", "personal_stake": {"min": 600, "max": 600}},
            "actual": {"type": "拘留", "detention_days": 5}}
    data = done(client, "/api/v1/discretion/review", body)
    assert not fake.calls and "存在偏离：省级基准档位" in data["deviation"]["summary"]


def test_extract_drops_unsupported_field_instead_of_failing(env, monkeypatch):
    client, fake, _ = env
    bad = element_payload()
    bad["amounts"]["commission"] = {"status": "明确", "value": {"min": 5, "max": 5}, "evidence": [{"sentence_ids": ["S2.1"]}]}
    monkeypatch.setattr(sys.modules[__name__], "element_payload", lambda: bad)
    data = done(client, "/api/v1/discretion/extract", {"text": TEXT, "region": "320582"})
    assert [d["path"] for d in data["dropped"]] == ["amounts.commission"]
    assert data["elements"]["amounts.commission"]["status"] == "待核实" and "commission" not in data["assess_input"]
    assert data["elements"]["amounts.personal_stake"]["value"] == {"min": 600, "max": 600}
    assert all("_raw" not in c for c in data["trace"]["model_calls"])
    assert discretion_runs_db.data[data["run_id"]]["archive"]["model_calls"][-1]["_raw"]


def test_config_errors_return_immediately_without_job(env):
    client, _, _ = env
    assert client.post("/api/v1/discretion/parse", json={"text": TEXT, "model_id": "fake/b"}).status_code == 403
    assert client.post("/api/v1/discretion/extract", json={"region": "320582"}).status_code == 422
    assert not discretion_runs_db.data


def test_interrupted_job_is_reported_failed(env):
    client, _, _ = env
    discretion_runs_db.data["dr_x"] = {"run_id": "dr_x", "kind": "parse", "owner": "u1", "status": "running"}
    run = client.get("/api/v1/discretion/runs/dr_x").json()["data"]
    assert run["status"] == "failed" and run["error"]["code"] == 50001


def test_run_directory_exposes_only_owned_summaries(env):
    client, _, _ = env
    own = job(client, "/api/v1/discretion/parse", {"text": TEXT})
    assert own["phase"] == "completed"
    discretion_runs_db.data["dr_other"] = {
        "run_id": "dr_other", "kind": "review", "owner": "u2", "status": "succeeded",
        "created_at": "2026-10-28T00:00:00+08:00", "result": {"written": {"type": "罚款"}},
        "archive": {"raw_text": "private"},
    }
    rows = client.get("/api/v1/discretion/runs").json()["data"]
    assert [row["run_id"] for row in rows] == [own["run_id"]]
    assert all("archive" not in row and "result" not in row for row in rows)
    as_admin()
    admin_rows = client.get("/api/v1/discretion/runs").json()["data"]
    assert {row["run_id"] for row in admin_rows} == {own["run_id"], "dr_other"}
    assert next(row for row in admin_rows if row["run_id"] == "dr_other")["summary"] == "罚款"
