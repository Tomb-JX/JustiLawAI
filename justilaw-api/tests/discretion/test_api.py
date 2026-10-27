import pytest
from fastapi.testclient import TestClient

from app.auth import current_user
from app.main import app


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: {"id": "u_test", "role": "user"}
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_meta_lists_provinces_and_enums(client):
    data = client.get("/api/v1/discretion/meta").json()["data"]
    assert {p["code"] for p in data["provinces"]} == {"130000", "320000"}
    assert "网络赌博" in data["methods"] and "聚众赌博" in data["gambling_forms"]


def test_decide_returns_type_space_and_distribution(client):
    body = {"behavior_date": "2026-09-01", "decision_date": "2026-09-10", "region": "130102",
            "behavior_type": "参与赌博", "personal_stake": {"min": 700, "max": 700}}
    data = client.post("/api/v1/discretion/decide", json=body).json()["data"]
    assert (data["penalty_type"], data["route"]) == ("拘留", "rule_single")
    assert data["assessment"]["law_id"] == "psal-2025"
    assert data["assessment"]["tiers"]["一般"]["options"][0]["kind"] in ("拘留", "罚款")
    assert data["quantities"]["detention_days"]
    assert any("推定沿用" in n for n in data["notes"])


def test_decide_rejects_bad_input(client):
    r = client.post("/api/v1/discretion/decide", json={"behavior_date": "2026-09-01", "behavior_type": "打牌"})
    assert r.status_code == 422
    r = client.post("/api/v1/discretion/decide", json={"behavior_date": "2026-09-10", "decision_date": "2026-09-01",
                                                       "behavior_type": "参与赌博"})
    assert r.status_code == 422 and "早于" in r.json()["message"]
