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
from pkulaw_agent import jobs as jobs_mod  # noqa: E402
from pkulaw_agent import recon as recon_mod  # noqa: E402
from pkulaw_agent import run as run_mod  # noqa: E402
from pkulaw_agent import session as sess  # noqa: E402
from pkulaw_agent import validators as val_mod  # noqa: E402

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


def test_download_patterns_format_preference():
    from pkulaw_agent.download import download_patterns
    auto = download_patterns("auto")
    i_w = next(i for i, p in enumerate(auto) if "WORD" in p.pattern)
    i_p = next(i for i, p in enumerate(auto) if "PDF" in p.pattern)
    assert i_w < i_p  # auto：Word 优先、失败回退 PDF
    assert auto[0].search("下载") and i_w > 0  # 首位仍是"下载"展开器
    word = download_patterns("word")
    assert any("WORD" in p.pattern for p in word)
    assert not any("PDF" in p.pattern for p in word)
    pdf = download_patterns("pdf")
    assert any("PDF" in p.pattern for p in pdf)
    assert not any("WORD" in p.pattern for p in pdf)


def test_fmt_patterns_order_matches_format():
    from pkulaw_agent.download import _fmt_patterns
    w = _fmt_patterns("word")
    assert any("WORD" in p.pattern for p in w) and not any("PDF" in p.pattern for p in w)
    p = _fmt_patterns("pdf")
    assert any("PDF" in p.pattern for p in p) and not any("WORD" in p.pattern for p in p)
    auto = _fmt_patterns("auto")
    i_w = next(i for i, q in enumerate(auto) if "WORD" in q.pattern)
    i_p = next(i for i, q in enumerate(auto) if "PDF" in q.pattern)
    assert i_w < i_p


# ---------------- session v1.1：session.json / CDP 探测 ----------------

def test_session_json_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("JUSTILAW_DATA_DIR", str(tmp_path))
    sess.save_session_info(checked_at="2026-10-16 22:00", lib_ok="apy")
    sess.save_session_info(account="河海大学")
    info = sess.load_session_info()
    assert info["checked_at"] == "2026-10-16 22:00"
    assert info["account"] == "河海大学" and info["lib_ok"] == "apy"
    assert (tmp_path / "session.json").exists()


def test_cdp_probe_closed_port_returns_empty():
    assert sess.cdp_probe(1, timeout_s=0.2) == {}


def test_profile_lock_files_reports_names(tmp_path):
    (tmp_path / "lockfile").write_text("x", encoding="utf-8")
    assert sess.profile_lock_files(tmp_path) == ["lockfile"]
    assert sess.profile_lock_files(tmp_path / "nonexist") == []


def test_doc_no_from_title():
    from pkulaw_agent.fetch import doc_no_from_title
    assert doc_no_from_title(
        "王xx行政处罚(土公（沟）行罚决字〔2026〕527号)-北大法宝V6官网") == "土公（沟）行罚决字〔2026〕527号"
    assert doc_no_from_title("公告-北大法宝") == ""


def test_dedup_page_text_collapses_artifacts():
    from pkulaw_agent.fetch import dedup_page_text
    doubled = "王某，男，49岁，1976年10月06日出生。王某，男，49岁，1976年10月06日出生。"
    assert dedup_page_text(doubled) == "王某，男，49岁，1976年10月06日出生。"
    mixed = ("2026年08月26日2时许，在内蒙古自治区土默特右旗威俊村北王永禄养猪院内，王"
             "2026年08月26日2时许，在内蒙古自治区土默特右旗威俊村北王永禄养猪院内，王小乐招集"
             "张艳平、刘海玲、吕俊兰等人用麻将以推对子形式进行赌博，王永禄提供赌博场地并开车送"
             "参赌人员张艳平、刘海玲等人。")
    got = dedup_page_text(mixed)
    assert got.startswith("2026年08月26日2时许")
    assert got.count("2026年08月26日2时许") == 1 and "王小乐招集" in got
    # 跨段碎片：全文之后又出现句尾、被拆成两个 <p>
    frags = ("现查明\n"
             "2026年08月26日2时许，在内蒙古自治区土默特右旗威俊村北王永禄养猪院内，王小乐招集"
             "张艳平、刘海玲、吕俊兰等人用麻将以推对子形式进行赌博，王永禄提供赌博场地并开车送"
             "参赌人员张艳平、刘海玲等人。\n"
             "小乐招集张艳平、刘海玲、吕俊兰等人用麻将以推对子形式进行赌博，王永禄提供赌博场地并\n"
             "开车送参赌人员张艳平、刘海玲等人。")
    got2 = dedup_page_text(frags)
    assert got2.count("小乐招集") == 1 and got2.count("开车送参赌人员") == 1
    assert "现查明" in got2  # 短标题行保留
    normal = "土默特右旗公安局\n行政处罚决定书\n2026年8月26日凌晨2时许，接群众举报后民警赶赴现场处置。"
    assert dedup_page_text(normal) == normal


def test_fold_wrapped_lines_pdf_case():
    """PDF 硬换行折回段落后，去伪影规则可正常生效（实测 527 号：截断前缀跨两行）。"""
    import pkulaw_ingest as ingest
    wrapped = ("2026年08月26日2时许，在内蒙古自治区土默特右旗威俊村北王永禄养猪院内，王2026年08\n"
               "月26日2时许，在内蒙古自治区土默特右旗威俊村北王永禄养猪院内，王小乐招集张艳平、刘海玲、\n"
               "吕俊兰等人用麻将以推对子形式进行赌博，王永禄提供赌博场地并开车送参赌人员张艳平、刘海玲等\n"
               "人。\n小乐招集张艳平、刘海玲、吕俊兰等人用麻将以推对子形式进行赌博，王永禄提供赌博场地并\n"
               "开车送参赌人员张艳平、刘海玲等人。\n以上事实有")
    got = ingest.dedup_page_text(ingest._fold_wrapped_lines(wrapped))
    assert got.count("2026年08月26日2时许") == 1
    assert got.count("小乐招集") == 1
    assert "以上事实有" in got  # 短标题行保留
    assert ingest.dedup_page_text(got) == got  # 幂等


# ---------------- validators：六项校验 ----------------

def test_check_doc_no_fullwidth_and_brackets():
    ok, _ = val_mod.check_doc_no("土公（沟）行罚决字〔2026〕527号",
                                 "土公(沟)行罚决字〔2026〕527号")
    assert ok  # 全/半角括号归一后一致
    ok, _ = val_mod.check_doc_no("", "苏公字〔2022〕1号")
    assert not ok  # 页面没取到文号 → 不通过
    ok, note = val_mod.check_doc_no("任意", "")
    assert ok and "跳过" in note  # 作业无文号 → 跳过比对


def test_check_gambling_excludes_tobacco():
    assert val_mod.check_gambling("现查明：甲参与赌博，查获赌资 1000 元")[0]
    ok, note = val_mod.check_gambling("以营利为目的违法储存烟草制品香烟")
    assert not ok and "烟草" in note
    assert not val_mod.check_gambling("该文书记载了其他违法行为")[0]


def test_check_year_ignores_law_version_marks():
    job = {"punishment_date": "2026.09.03"}
    assert val_mod.check_year(job, "正文无日期", (2026, 2026))[0]
    assert not val_mod.check_year({"punishment_date": "2025.12.01"},
                                  "2025年1月1日实施", (2026, 2026))[0]
    assert not val_mod.check_year({}, "根据2025年修订的治安管理处罚法", (2026, 2026))[0]
    assert not val_mod.check_year({}, "依据(2025修订)第82条", (2026, 2026))[0]
    assert val_mod.check_year({}, "于2026年6月6日实施赌博行为", (2026, 2026))[0]
    assert val_mod.check_year({}, "任意", None)[0]  # 不限窗


def test_check_narrative_and_masked():
    assert not val_mod.check_narrative({"form": "table", "facts_len": 200})[0]
    assert not val_mod.check_narrative({"form": "narrative", "facts_len": 10})[0]
    assert val_mod.check_narrative({"form": "narrative", "facts_len": 80})[0]
    assert not val_mod.check_masked("决定对其处罚款 xx 元")[0]
    assert not val_mod.check_masked("查获赌资＊元、赌具一批")[0]
    assert not val_mod.check_masked("罚款人民币□□□元")[0]
    assert not val_mod.check_masked("现场查获赌资****元，赌具麻将*副")[0]  # 法宝源 * 号打码
    assert not val_mod.check_masked("20**年**月**日**时许在**栋")[0]
    assert val_mod.check_masked("处罚款五百元整；王xx（男，45岁）到场")[0]  # 人名 xx 不误报
    assert val_mod.check_masked("依据《治安管理处罚法》第**条、第**条第**款处罚")[0]  # 只遮条号不遮金额/日期
    assert val_mod.check_masked("张**，李*，杨**，石**四人以打*方式赌博")[0]  # 只遮人名
    assert val_mod.check_masked("男，年龄**岁，****年**月**日出生，居民身份证号码：1522**")[0]  # 出生日期豁免
    assert val_mod.check_masked("违法犯罪记录：****年**月**日之前无违法犯罪记录")[0]  # 前科句豁免


def test_check_dedupe_manifest_and_seen():
    ok, note = val_mod.check_dedupe("土公（沟）行罚决字〔2026〕527号", "s1",
                                    manifest_ids={"土公（沟）行罚决字〔2026〕527号"},
                                    seen=set())
    assert not ok and "台账" in note
    ok, note = val_mod.check_dedupe("新文号〔2026〕1号", "s1", manifest_ids=set(),
                                    seen={"s1"})
    assert not ok and "正文重复" in note
    ok, _ = val_mod.check_dedupe("新文号〔2026〕2号", "s2", manifest_ids=set(), seen={"s1"})
    assert ok


def test_validate_article_pass_then_mask_fail():
    job = {"doc_no": "土公（沟）行罚决字〔2026〕527号", "punishment_date": "2026.09.03"}
    probe = {"doc_no": "土公（沟）行罚决字〔2026〕527号", "form": "narrative",
             "facts_len": 120}
    text = ("土公（沟）行罚决字〔2026〕527号 现查明：2026年1月5日，甲参与赌博，"
            "现场查获赌资 1000 元。根据《中华人民共和国治安管理处罚法》(2025修订)"
            "第八十二条之规定，给予处罚。") * 3
    val = val_mod.validate_article(job, text=text, probe=probe, text_sha="sha-x",
                                   window=(2026, 2026), manifest_ids=set(), seen=set())
    assert val["pass"], val["fails"]
    assert set(val["checks"]) == {"doc_no", "gambling", "year", "narrative", "masked", "dedupe"}
    text2 = text.replace("1000 元", "xx 元")
    val2 = val_mod.validate_article(job, text=text2, probe=probe, text_sha="sha-y",
                                    window=(2026, 2026), manifest_ids=set(), seen=set())
    assert not val2["pass"] and any(f.startswith("masked:") for f in val2["fails"])


def test_parse_window():
    assert val_mod.parse_window("2026") == (2026, 2026)
    assert val_mod.parse_window("2025-07:2026") == (2025, 2026)
    assert val_mod.parse_window("") is None


# ---------------- jobs：作业单 ----------------

def _fake_mcp_cache(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    f1 = {"path": "/pkulaw-enforcement-doc/mcp", "tool": "search_enforcement",
          "arguments": {"queryText": "现场查获赌资"}, "fetched_at": "2026-10-16T20:18:29",
          "structured": {"message": "查询成功", "total": 3, "data": [
              {"title": "王xx行政处罚(土公（沟）行罚决字〔2026〕527号)",
               "documentNo": "土公（沟）行罚决字〔2026〕527号",
               "punishOrgan": "土默特右旗公安局", "punishmentDate": "2026.09.03",
               "accordingLaw": ["中华人民共和国治安管理处罚法(2025修订)第82条"],
               "url": "https://www.pkulaw.com/apy/aaa.html?way=mcp"},
              {"title": "旧案", "documentNo": "龙公（开）行罚决字〔2025〕437号",
               "punishOrgan": "龙口市公安局", "punishmentDate": "2025.12.01",
               "accordingLaw": ["中华人民共和国治安管理处罚法(2012修正)第70条"],
               "url": "https://www.pkulaw.com/apy/bbb.html?way=mcp"},
              {"title": "无链接条目", "documentNo": "X公（行）行罚决字〔2026〕001号",
               "punishOrgan": "某局", "punishmentDate": "2026.01.05",
               "accordingLaw": ["中华人民共和国治安管理处罚法(2025修订)第82条"],
               "url": ""}]}}
    (cache / "f1.json").write_text(json.dumps(f1, ensure_ascii=False), encoding="utf-8")
    f2 = {"path": "/pkulaw-enforcement-doc/mcp", "tool": "search_enforcement",
          "arguments": {"queryText": "参赌人员"}, "fetched_at": "2026-10-16T20:18:31",
          "structured": {"message": "查询成功", "total": 1, "data": [
              {"title": "重复件（另一检索词命中）",
               "documentNo": "土公（沟）行罚决字〔2026〕527号",
               "punishOrgan": "土默特右旗公安局", "punishmentDate": "2026.09.03",
               "accordingLaw": ["中华人民共和国治安管理处罚法(2025修订)第82条"],
               "url": "https://www.pkulaw.com/apy/aaa2.html?way=mcp"}]}}
    (cache / "f2.json").write_text(json.dumps(f2, ensure_ascii=False), encoding="utf-8")
    (cache / "other.json").write_text(json.dumps({"structured": {"data": "非列表"}}),
                                      encoding="utf-8")
    return cache


def test_jobs_from_mcp_filters_and_dedup(tmp_path):
    cache = _fake_mcp_cache(tmp_path)
    out = tmp_path / "jobs.jsonl"
    stats = jobs_mod.jobs_from_mcp(cache, out=out, year="2026", law="新法")
    jobs = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert stats["jobs"] == 1
    assert jobs[0]["doc_no"] == "土公（沟）行罚决字〔2026〕527号"
    assert jobs[0]["law"] == "新法" and jobs[0]["source"] == "mcp"
    meta = json.loads((tmp_path / "jobs.meta.json").read_text(encoding="utf-8"))
    assert meta["cache_rows"] == 4 and meta["filters"]["year"] == "2026"
    assert meta["skipped_no_url"] == 1
    # 无过滤：2025 旧案进入；无链接条目被剔除；重复文号去重
    stats2 = jobs_mod.jobs_from_mcp(cache, out=tmp_path / "j2.jsonl")
    assert stats2["jobs"] == 2
    stats3 = jobs_mod.jobs_from_mcp(cache, out=tmp_path / "j3.jsonl", organ="土默特")
    assert stats3["jobs"] == 1


def test_jobs_from_csv_year_filter_and_skip_nourl(tmp_path):
    csv_path = tmp_path / "w.csv"
    csv_path.write_text(
        "发文案号,标题,处罚机关,公布日期,处罚种类,依据法条,原文链接,叙述式,已下全文\n"
        "A〔2026〕1号,标题A,某局,2026.01.05,罚款,治安管理处罚法(2025修订)第82条,"
        "https://www.pkulaw.com/apy/a.html,是,\n"
        "B〔2025〕2号,标题B,某局,2025.03.01,罚款,治安管理处罚法(2012修正)第70条,"
        "https://www.pkulaw.com/apy/b.html,是,\n"
        "C〔2026〕3号,标题C,某局,2026.02.02,罚款,治安管理处罚法(2025修订)第82条,,是,\n",
        encoding="utf-8-sig")
    out = tmp_path / "jobs.jsonl"
    stats = jobs_mod.jobs_from_csv(csv_path, out=out, year="2026")
    jobs = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert stats["jobs"] == 1 and jobs[0]["doc_no"] == "A〔2026〕1号"
    assert jobs[0]["law"] == "新法"
    meta = json.loads((tmp_path / "jobs.meta.json").read_text(encoding="utf-8"))
    assert len(meta["csv_sha256"]) == 16


# ---------------- run：状态机与下载完整性 ----------------

def test_run_state_resume_and_seen(tmp_path):
    st = run_mod.RunState(tmp_path / "run.jsonl")
    st.put({"doc_no": "A〔2026〕1号", "url": "u1", "status": "downloaded",
            "text_sha256": "s1"})
    st.put({"doc_no": "B〔2026〕2号", "url": "u2", "status": "error"})
    st2 = run_mod.RunState(tmp_path / "run.jsonl")  # 重开 = 续跑视角
    assert st2.get({"doc_no": "A〔2026〕1号"})["status"] == "downloaded"
    assert st2.get({"doc_no": "B〔2026〕2号"})["status"] == "error"
    seen = st2.seen_set()
    assert "s1" in seen and "A〔2026〕1号" in seen
    assert run_mod.TERMINAL == {"downloaded", "skipped", "validated"}


def test_verify_download_magic_and_ext(tmp_path):
    good = tmp_path / "a.doc"
    good.write_bytes(b"\xd0\xcf\x11\xe0" + b"0" * 100)
    assert run_mod.verify_download(good)[0]
    html = tmp_path / "b.doc"
    html.write_bytes(b"<html><body>x</body></html>")
    assert not run_mod.verify_download(html)[0]
    empty = tmp_path / "c.docx"
    empty.write_bytes(b"")
    assert not run_mod.verify_download(empty)[0]
    exe = tmp_path / "d.exe"
    exe.write_bytes(b"MZ" + b"0" * 20)
    assert not run_mod.verify_download(exe)[0]
    assert not run_mod.verify_download(tmp_path / "missing.doc")[0]


def test_load_manifest_ids_extracts_docnos(tmp_path):
    m = tmp_path / "manifest.csv"
    m.write_text(
        "id,title,notes\n"
        "P-1,张xx行政处罚(稀公（民）行罚决字〔2026〕311号)(FBM-CLI.ALE.49354610),批次A\n",
        encoding="utf-8-sig")
    ids = run_mod.load_manifest_ids(m)
    assert "稀公（民）行罚决字〔2026〕311号" in ids
    assert run_mod.load_manifest_ids(tmp_path / "none.csv") == set()
