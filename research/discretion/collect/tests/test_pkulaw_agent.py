"""pkulaw_agent 单测：纯函数与包装逻辑，不联网、不开浏览器。

运行（仓库根目录）：python -m pytest research/discretion/collect/tests/test_pkulaw_agent.py -q
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pkulaw_agent import api as api_mod  # noqa: E402
from pkulaw_agent import recon as recon_mod  # noqa: E402
from pkulaw_agent import session as sess  # noqa: E402

# ---------------- recon ----------------

def test_should_record_skips_login_and_static():
    assert not recon_mod.should_record("xhr", "https://www.pkulaw.com/newlogin")
    assert not recon_mod.should_record("xhr", "https://www.pkulaw.com/VerificationCode/img")
    assert not recon_mod.should_record("xhr", "https://www.pkulaw.com/usercenter/info")
    assert not recon_mod.should_record("script", "https://www.pkulaw.com/Scripts/app.js")
    assert not recon_mod.should_record("document",
                                       "https://www.pkulaw.com/auth/realms/fabao/sms/kc-sessions")
    assert not recon_mod.should_record("document",
                                       "https://www.pkulaw.com/help/CheckKcIsLoginPage")
    assert recon_mod.should_record("xhr", "https://www.pkulaw.com/searchingapi/adv/list/apy")
    assert recon_mod.should_record("document", "https://www.pkulaw.com/apy/abc.html")


def test_collect_replays_dedupes_and_skips_non_json(tmp_path):
    lines = [
        {"kind": "api", "method": "POST", "path": "/searchingapi/adv/list/apy", "req": {"pageIndex": 0}},
        {"kind": "api", "method": "POST", "path": "/searchingapi/adv/list/apy", "req": {"pageIndex": 0}},
        {"kind": "api", "method": "POST", "path": "/x", "req": {"_raw_len": 10}},
        {"kind": "nav", "method": "GET", "path": "/penalty"},
    ]
    f = tmp_path / "recon-x.jsonl"
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    got = recon_mod.collect_replays(f)
    assert got == [{"path": "/searchingapi/adv/list/apy", "body": {"pageIndex": 0}}]


def test_record_kind_classification():
    assert recon_mod.record_kind("xhr", "https://www.pkulaw.com/searchingapi/adv/list/apy") == "api"
    assert recon_mod.record_kind("fetch", "https://www.pkulaw.com/api/whatever") == "api"
    assert recon_mod.record_kind("document", "https://www.pkulaw.com/apy/abc.html") == "nav"
    assert recon_mod.record_kind("xhr", "https://www.pkulaw.com/some/track.gif") == ""
    assert recon_mod.record_kind("document", "https://www.pkulaw.com/newlogin") == ""


def test_path_only_strips_query_values():
    assert recon_mod._path_only("https://www.pkulaw.com/apy/x.html") == "/apy/x.html"
    got = recon_mod._path_only("https://www.pkulaw.com/x?uid=123&kw=赌博")
    assert "123" not in got and "赌博" not in got and "kw" in got


def test_scrub_keys_masks_sensitive_and_truncates():
    data = {"userName": "张三", "password": "p@ss", "access_token": "abc",
            "note": "x" * 200, "nested": {"smsCode": "1234", "ok": 1}}
    out = recon_mod.scrub_keys(data)
    assert out["password"] == "***"
    assert out["access_token"] == "***"
    assert out["nested"]["smsCode"] == "***"
    assert out["userName"] == "张三"
    assert len(out["note"]) <= recon_mod._VALUE_SUMMARY_MAX + 1


def test_shrink_json_keeps_schema_only():
    data = {"total": 123, "data": [{"gid": "a", "title": "t", "secret": "s"}]}
    out = recon_mod.shrink_json(data)
    assert out["_total"] == 123
    assert out["_list_key"] == "data" and out["_list_len"] == 1
    assert set(out["_item_keys"]) == {"gid", "title", "secret"}
    dumped = json.dumps(out, ensure_ascii=False)
    assert '"a"' not in dumped and '"s"' not in dumped  # 样本值不落盘（只留键名）


# ---------------- api ----------------

def test_error_predicates():
    assert api_mod.is_token_error({"code": "1", "message": "token error"})
    assert not api_mod.is_token_error({"code": "0", "message": "ok"})
    assert api_mod.is_security_block({"code": "SecurityProtection"})
    assert api_mod.is_captcha({"error": {"code": "NEED_CAPTCHA"}})
    assert not api_mod.is_captcha({"error": {"code": "other"}})
    assert api_mod.is_ok_list({"total": 0, "data": []})
    assert not api_mod.is_ok_list({"code": "1"})


def test_build_bodies():
    b = api_mod.build_search_body(page_index=2, page_size=50)
    assert b["pageIndex"] == 2 and b["pageSize"] == 50
    assert b["fieldNodes"] == [] and b["clusterFilters"] == {}
    assert api_mod.build_cluster_body("CategoryNew") == {"dimensionId": "CategoryNew"}
    assert api_mod.build_cluster_body(None) == {}


class _FakePage:
    def wait_for_timeout(self, ms: int) -> None:  # noqa: ARG002
        pass


class _FakeSession:
    def __init__(self, responses: list[dict]) -> None:
        self.page = _FakePage()
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def api_post(self, path: str, body: dict | None = None, **kw):  # noqa: ANN003, ARG002
        self.calls.append((path, body or {}))
        return self.responses.pop(0)


def test_api_wrapper_maps_errors():
    ok = api_mod.PkulawApi(_FakeSession(
        [{"status": 200, "text": json.dumps({"total": 5, "data": []})}]), min_interval_s=0)
    assert ok.search("apy", api_mod.build_search_body())["total"] == 5

    import pytest
    bad_token = api_mod.PkulawApi(_FakeSession(
        [{"status": 401, "text": '{"code":"1","message":"token error"}'}]), min_interval_s=0)
    with pytest.raises(PermissionError):
        bad_token.search("apy", {})

    risk = api_mod.PkulawApi(_FakeSession(
        [{"status": 200, "text": '{"code":"SecurityProtection"}'}]), min_interval_s=0)
    with pytest.raises(RuntimeError, match="风控"):
        risk.search("apy", {})


def test_api_verify_login_path():
    fs = _FakeSession([{"status": 200, "text": '{"total": 1, "data": [{}]}'}])
    api = api_mod.PkulawApi(fs, min_interval_s=0)
    assert api.verify_login("apy")
    assert fs.calls[0][0] == "/searchingapi/adv/list/apy"
    assert fs.calls[0][1]["pageSize"] == 1


# ---------------- session ----------------

def test_mask_token_and_entry_urls():
    assert sess.mask_token("") == "***"
    assert sess.mask_token("short") == "***"
    masked = sess.mask_token("abcdefghij0123456789XYZ")
    assert masked.startswith("abcdefghij") and masked.endswith("XYZ")
    assert set(sess.LIB_ENTRY) == {"apy", "pfnl", "chl"}
    assert "penalty" in sess.LIB_ENTRY["apy"] and "case" in sess.LIB_ENTRY["pfnl"]


def test_jwt_exp_hint():
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 4102444800}).encode()).decode()
    token = f"header.{payload.rstrip('=')}.sig"
    hint = sess.jwt_exp_hint(token)
    assert hint.startswith(("2100", "2099")) and len(hint) == 16
    assert sess.jwt_exp_hint("not-a-jwt") == ""
