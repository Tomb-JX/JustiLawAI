"""§3.12 assess：结论与完整追踪（依据原文、计算过程、要素来源、偏离、版本、存档）。"""
import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth import current_user
from app.discretion.norm_store import NORMS_DIR
from app.main import app
from app.store import discretion_runs_db

JIANGSU = {"behavior_date": "2023-07-06", "decision_date": "2023-07-07", "region": "320582",
           "behavior_type": "参与赌博", "method": "麻将", "gambling_form": "其他",
           "personal_stake": {"min": 600, "max": 600}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(discretion_runs_db, "data", {})
    monkeypatch.setattr(discretion_runs_db, "save", lambda: None)
    app.dependency_overrides[current_user] = lambda: {"id": "u_test", "role": "user"}
    yield TestClient(app)
    app.dependency_overrides.clear()


def _steps(data):
    return {s["id"]: s for s in data["trace"]["steps"]}


def test_assess_traces_law_space_band_with_original_text(client):
    data = client.post("/api/v1/discretion/assess", json=JIANGSU).json()["data"]
    assert data["written"]["type"] == "罚款" and data["written"]["route"] == "rule_single"
    s = _steps(data)
    assert s["law"]["result"]["id"] == "psal-2012" and "2012" in s["law"]["reasoning"]
    basis = s["legal_space"]["result"]["一般"]["options"][0]["basis"][0]
    assert basis["ref"] == "psal-2012#70" and "赌资较大" in basis["text"]
    band = s["band"]
    assert band["status"] == "determined" and band["result"] == ["第一档"]
    assert any("600 元" in line and "500 / 2000 / 5000" in line for line in band["computation"])
    assert "参与其他赌博活动" in band["basis"]["clauses"][0]["text"]
    assert band["basis"]["document"] == "苏公规〔2019〕1号" and band["basis"]["verified"] is True
    v = data["trace"]["versions"]
    assert v["engine"] and v["schema"] and len(v["norm_library_sha256"]) == 64
    assert v["province_benchmark"]["number"] == "苏公规〔2019〕1号"
    assert s["amount"]["source"]["source_sha256"] and s["practice"]["status"] == "reference"


def test_assess_records_provenance_deviation_and_archives_run(client):
    body = {**JIANGSU,
            "provenance": {"personal_stake": {"status": "明确", "origin": "extracted_then_confirmed",
                                              "evidence": [{"quote": "其中金xx的赌资350元", "sentence": 7}]}},
            "proposed": {"type": "拘留", "detention_days": 5}}
    data = client.post("/api/v1/discretion/assess", json=body).json()["data"]
    el = data["trace"]["inputs"]["elements"]["personal_stake"]
    assert el["origin"] == "extracted_then_confirmed" and el["evidence"][0]["quote"].startswith("其中")
    assert data["trace"]["inputs"]["elements"]["method"]["origin"] == "human"
    levels = {lv["level"]: lv for lv in data["deviation"]["levels"]}
    assert levels["legal_space"]["ok"] is True and levels["written_band"]["ok"] is False
    assert "不比较数额" in levels["amount_reference"]["detail"]
    run = client.get(f"/api/v1/discretion/runs/{data['run_id']}").json()["data"]
    assert run["kind"] == "assess" and len(run["request_sha256"]) == 64 and run["result"]["run_id"] == data["run_id"]


def test_assess_explains_elevation_with_unknown_stake_and_missing_items(client):
    body = {"behavior_date": "2023-04-26", "decision_date": "2023-05-01", "region": "130102",
            "behavior_type": "参与赌博", "method": "网络赌博"}
    data = client.post("/api/v1/discretion/assess", json=body).json()["data"]
    band = _steps(data)["band"]
    assert band["status"] == "candidates" and len(band["result"]) == 4
    assert any("升档条件成立" in line and "赌资不明" in line for line in band["computation"])
    assert {"personal_stake", "onsite_stake_total"} <= {m["field"] for m in data["missing"]}


def test_assess_rejects_unknown_provenance_field(client):
    r = client.post("/api/v1/discretion/assess", json={**JIANGSU, "provenance": {"stake": {"status": "明确"}}})
    assert r.status_code == 422


def test_run_not_visible_to_other_users(client):
    run_id = client.post("/api/v1/discretion/assess", json=JIANGSU).json()["data"]["run_id"]
    app.dependency_overrides[current_user] = lambda: {"id": "u_other", "role": "user"}
    assert client.get(f"/api/v1/discretion/runs/{run_id}").status_code == 404


@pytest.mark.parametrize("code", ["130000", "320000"])
def test_band_clauses_are_verbatim_from_document(code):
    d = yaml.safe_load((NORMS_DIR / "provinces" / f"{code}.yaml").read_text(encoding="utf-8"))
    text = d["documents"][0]["text"]
    for bt, bands in d["clauses"].items():
        for k, clause in bands.items():
            if k != "ref":
                assert clause in text, (code, bt, k)


def test_practice_reference_is_decomposable(client):
    data = client.post("/api/v1/discretion/assess", json={**JIANGSU, "proposed": {"type": "拘留", "detention_days": 5}}).json()["data"]
    p = data["practice"]
    assert p["status"] == "reference" and abs(sum(p["distribution"].values()) - 1) < 1e-3
    step = _steps(data)["practice"]
    ex = step["explanation"]
    for k, logit in ex["logits"].items():          # 基线 + 逐项贡献 = 对数几率（精确分解）
        total = ex["baseline_logits"][k] + sum(c["contribution"][k] for c in ex["contributions"])
        assert abs(total - logit) < 1e-2
    assert step["model"]["version"] == "rap-ruleonly-v2" and step["model"]["limits"]
    assert data["trace"]["versions"]["practice_model"]["training_n"] > 0
    lv = {x["level"]: x for x in data["deviation"]["levels"]}["practice"]
    assert lv["probability"] == p["distribution"]["拘留"]


def test_practice_not_extrapolated_to_new_law(client):
    body = {**JIANGSU, "behavior_date": "2026-03-01", "decision_date": "2026-03-05"}
    p = client.post("/api/v1/discretion/assess", json=body).json()["data"]["practice"]
    assert p["status"] == "out_of_scope" and "旧法" in p["note"]


def test_practice_features_match_spec():
    from app.discretion import practice
    from app.discretion.norm_layer import Facts
    assert len(practice.features(Facts(), [], "320000")) == len(practice.feature_spec())
    model = practice.load_model()
    assert model and not model.get("stale")
    names = [s["name"] for s in practice._spec_of(model)]
    if model.get("feature_set") == "rule":
        assert set(model["features"]) <= set(names)
    else:
        assert model["features"] == names
