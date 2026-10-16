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


# ---------------- search ----------------

def test_expand_runs_terms_x_windows():
    from pkulaw_agent.search import expand_runs
    plan = {"lib": "apy", "runs": [
        {"id": "r1", "terms": ["抽头", "渔利"], "region": "江苏省",
         "windows": [["2022-01-01", "2022-12-31"], ["2021-01-01", "2021-12-31"]]},
    ]}
    runs = expand_runs(plan)
    assert len(runs) == 4
    assert {r["term"] for r in runs} == {"抽头", "渔利"}
    assert all(r["region"] == "江苏省" for r in runs)
    assert runs[0]["window"] == ["2022-01-01", "2022-12-31"]
    assert len({r["id"] for r in runs}) == 4  # id 按窗口去重


def test_build_body_from_run_shapes():
    from pkulaw_agent.search import build_body_from_run, select_node, text_node
    plan = {"lib": "apy", "field_names": {"full_text": "FullText", "region": "Regional"}}
    run = {"id": "r", "lib": "apy", "term": "抽头", "region": "江苏省", "window": []}
    body = build_body_from_run(run, plan, page_index=1, page_size=50)
    assert body["pageIndex"] == 1 and body["pageSize"] == 50
    names = [n["fieldName"] for n in body["fieldNodes"]]
    assert names == ["FullText", "Regional"]
    assert body["fieldNodes"][0]["fieldItems"][0]["values"] == "抽头"

    run2 = {"id": "r2", "lib": "apy", "term": "x",
            "field_nodes": [text_node("Title", "y"), select_node("PunishmentType", ["罚款"])]}
    body2 = build_body_from_run(run2, plan)
    assert [n["type"] for n in body2["fieldNodes"]] == ["text", "select"]
    assert body2["fieldNodes"][1]["fieldItems"][0]["items"][0]["value"] == "罚款"


def test_normalize_item_and_key():
    from pkulaw_agent.search import item_key, normalize_item
    item = {"gid": "abc123", "Title": "某某赌博案", "DocumentNo": "苏公（治）行罚决字〔2022〕1号",
            "PublishDate": "2022-06-01", "lawRegional": "江苏省", "docUrl": "/apy/abc123.html"}
    norm = normalize_item(item, "apy")
    assert norm["gid"] == "abc123" and norm["title"] == "某某赌博案"
    assert norm["doc_no"].startswith("苏公") and norm["region"] == "江苏省"
    assert norm["url"] == "/apy/abc123.html" and norm["raw"]["gid"] == "abc123"
    assert item_key(norm) == "abc123"
    # 无 gid 无 url 时用文号兜底
    norm2 = normalize_item({"documentNo": "X公字〔2020〕5号"}, "apy")
    assert item_key(norm2) == "X公字〔2020〕5号"


def test_plan_template_has_required_keys():
    from pkulaw_agent.search import plan_template
    t = plan_template()
    assert {"batch", "lib", "runs", "search", "split", "fetch"} <= set(t)
    assert t["lib"] == "apy" and t["runs"][0]["terms"]


def test_example_plan_loads_and_expands():
    """仓库内的示例作业单要能直接跑（JSON 有效、字段齐全、展开正确）。"""
    from pkulaw_agent.search import expand_runs, load_plan
    plan_path = Path(__file__).resolve().parent.parent / "pkulaw_agent" / "plans" / "example-js-2022.json"
    plan = load_plan(plan_path)
    runs = expand_runs(plan)
    assert {r["term"] for r in runs} == {"现场查获赌资", "抽头"}
    assert all(r["region"] == "江苏省" and r["window"] == ["2022-01-01", "2022-12-31"]
               for r in runs)
    assert plan["fetch"]["only"] == "narrative"


# ---------------- fetch ----------------

NARRATIVE_WEB = """\
李某赌博案(苏公（治）行罚决字〔2022〕0001号)
主题分类： 公安
处罚种类： 行政拘留
行政相对人： 李某
执法机关：南京市公安局某某分局
执法地域： 江苏省
公布日期：2022.01.06
发文案号：苏公（治）行罚决字〔2022〕0001号
执法依据： 中华人民共和国治安管理处罚法(2012修正) 第70条

行政处罚决定书文号苏公（治）行罚决字〔2022〕0001号被处罚对象李某处罚事由赌博
处罚依据《中华人民共和国治安管理处罚法》第七十条处罚结果行政拘留三日
处罚决定日期2022-01-05处罚机关南京市公安局某某分局
现查明：2022年1月3日15时许，李某在南京市某棋牌室内以打麻将方式进行赌博，
被民警当场查获，现场查获赌资人民币2000元。以上事实有李某陈述、查获经过等证据证实。
根据《中华人民共和国治安管理处罚法》第七十条之规定，现决定给予李某行政拘留三日的处罚。
"""

TABLE_WEB = """\
王某赌博案(沪公长(长新)行罚决字〔2025〕0002号)
主题分类： 公安
处罚种类： 罚款
执法地域： 上海市
公布日期：2025.12.29

行政处罚决定书文号沪公长(长新)行罚决字〔2025〕0002号被处罚对象王某处罚事由赌博
处罚依据《中华人民共和国治安管理处罚法》第七十条处罚结果罚款三百元
处罚决定日期2025-12-29处罚机关上海市公安局某分局
"""


def test_probe_text_forms():
    from pkulaw_agent.fetch import probe_text
    p1 = probe_text(NARRATIVE_WEB)
    assert p1["form"] == "narrative" and p1["is_narrative"]
    assert p1["parsed_form"].startswith("叙述式")  # 独立成篇 / 结果栏内 都映射为 narrative
    assert p1["has_amount"] and p1["gambling_hint"]
    assert p1["doc_no"].startswith("苏公")
    # 注：table_rows_hit 基于 antiword 管道表格排版，网页抓取文本要先看一份真实样本再适配
    p2 = probe_text(TABLE_WEB)
    assert p2["form"] == "table" and p2["parsed_form"] == "字段式公示"
    assert not p2["has_amount"]
    p3 = probe_text("首页 检索 帮助 联系 数据库")
    assert p3["form"] == "other"


def test_safe_filename_and_ingest_head():
    from pkulaw_agent.fetch import make_ingest_doc_text, safe_filename
    assert safe_filename('苏公（治）行罚决字〔2022〕0001号') == "苏公（治）行罚决字〔2022〕0001号"
    assert "/" not in safe_filename("a/b:c*d?") and " " not in safe_filename("a b")
    head = make_ingest_doc_text({"doc_no": "苏公字〔2022〕1号", "title": "李某赌博案"},
                                {"pklaw_id": "FBM-CLI.AP.1"}, "正文")
    assert head.splitlines()[0] == "苏公字〔2022〕1号 李某赌博案 (FBM-CLI.AP.1)"


def test_probe_then_parse_roundtrip(tmp_path):
    """抓取文本 → 落 .txt → 既有解析链能直接解析出叙述式记录。"""
    import pkulaw_ingest as ingest
    from pkulaw_agent.fetch import make_ingest_doc_text
    text = make_ingest_doc_text({"doc_no": "苏公（治）行罚决字〔2022〕0001号", "title": "李某赌博案"},
                                {"pklaw_id": "FBM-CLI.AP.999"}, NARRATIVE_WEB)
    p = tmp_path / "doc.txt"
    p.write_text(text, encoding="utf-8")
    got, how = ingest.doc_to_text(p)
    assert how == "plain"
    parsed = ingest.parse_any_doc(got, filename=p.name)
    assert parsed["doc_no"].startswith("苏公")
    assert "打麻将" in parsed["facts"] or "李某" in parsed["facts"]


# ---------------- download ----------------

class _FakeDownload:
    def __init__(self, name: str) -> None:
        self.suggested_filename = name
        self.saved_to: Path | None = None

    def save_as(self, path: str) -> None:
        self.saved_to = Path(path)
        Path(path).write_bytes(b"fake")


class _FakeContext:
    def __init__(self) -> None:
        self.handlers: list = []

    def on(self, event: str, fn) -> None:  # noqa: ANN001
        if event == "download":
            self.handlers.append(fn)

    def remove_listener(self, event: str, fn) -> None:  # noqa: ANN001, ARG002
        if fn in self.handlers:
            self.handlers.remove(fn)


def test_download_sink_saves_and_dedupes(tmp_path):
    from pkulaw_agent.download import DownloadSink
    ctx = _FakeContext()
    sink = DownloadSink(ctx, tmp_path)
    assert ctx.handlers, "应挂上 context 级 download 监听"
    sink.handlers = None  # 只读提示：处理器由 context 触发
    d1, d2 = _FakeDownload("苏公字〔2022〕1号.doc"), _FakeDownload("苏公字〔2022〕1号.doc")
    for h in ctx.handlers:
        h(d1)
        h(d2)
    assert sink.count() == 2
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["苏公字〔2022〕1号-1.doc", "苏公字〔2022〕1号.doc"]  # 重名自动加序号
    sink.write_manifest(tmp_path / "downloads.json")
    data = json.loads((tmp_path / "downloads.json").read_text(encoding="utf-8"))
    assert len(data) == 2 and data[0]["file"].endswith(".doc")


def test_download_patterns_cover_menu_items():
    from pkulaw_agent.download import DOWNLOAD_TEXT
    assert DOWNLOAD_TEXT.search("下载")
    assert DOWNLOAD_TEXT.search("导出目录")
