"""发现层 L4 栏目扩展单测：只测纯函数，HTML 与 URL 均为合成样例（复刻 M3 实测中遇到的站点形态），不联网。

运行（仓库根目录）：python -m pytest research/discretion/discover/tests -q
"""

from __future__ import annotations

from expand import (
    blocked, breadcrumb_links, cms_family, dominant_seeds, family_params, list_variants, page_count, parent_dirs,
    path_tokens, score_list_page, total_items, url_shape, url_shape_strict,
)


def test_url_shape_loose_collapses_numbers_and_hex():
    a = "http://www.xjbh.gov.cn/xjbhx/c109939/202504/f88f823597154a48849990efae38279b.shtml"
    b = "http://www.xjbh.gov.cn/xjbhx/c109939/202603/1c9f3fd35ad74f8f9253913c94aaaaaa.shtml"
    assert url_shape(a) == url_shape(b)


def test_strict_shape_keeps_category_number():
    gongan = "https://www.dingxing.gov.cn/xzzfcon-467-33736.html"
    shenji = "https://www.dingxing.gov.cn/xzzfcon-426-50001.html"
    assert url_shape(gongan) == url_shape(shenji)
    assert url_shape_strict(gongan) != url_shape_strict(shenji)
    assert url_shape_strict(gongan) == url_shape_strict("https://www.dingxing.gov.cn/xzzfcon-467-44455.html")


def test_strict_shape_trs_and_date_dirs():
    a = "http://www.ahq.gov.cn/swgk/x/xzcfsx/202409/t20240909_2404394.html"
    b = "http://www.ahq.gov.cn/swgk/x/xzcfsx/202511/t20251120_2775046.html"
    assert url_shape_strict(a) == url_shape_strict(b)


def test_strict_shape_keeps_non_id_query_values():
    a = "https://wei.gov.cn/zhifa_show.php?cid=962&id=49988"
    b = "https://wei.gov.cn/zhifa_show.php?cid=962&id=44914"
    c = "https://wei.gov.cn/zhifa_show.php?cid=11&id=44914"
    assert url_shape_strict(a) == url_shape_strict(b) != url_shape_strict(c)


def test_list_variants():
    assert "https://www.dingxing.gov.cn/xzzflist-467-more.html" in list_variants("https://www.dingxing.gov.cn/xzzfcon-467-33736.html")
    assert "https://wei.gov.cn/zhifa.php?cid=962" in list_variants("https://wei.gov.cn/zhifa_show.php?cid=962&id=49988")
    assert "https://www.lixian.gov.cn/xzzf/listXzzfIndex.do" in list_variants("https://www.lixian.gov.cn/xzzf/getXzzfIndexInfo.do?rid=2438")


def test_parent_dirs_skip_date_dirs_and_offer_index_files():
    out = parent_dirs("https://www.hongta.gov.cn/htqzfxxgk/xzcf2/20211227/1325535.html")
    assert out[0] == "https://www.hongta.gov.cn/htqzfxxgk/xzcf2/"
    assert "https://www.hongta.gov.cn/htqzfxxgk/xzcf2/index.html" in out
    assert not any("20211227" in u for u in out)


def test_path_tokens():
    assert "xzzf" in path_tokens("https://www.dingxing.gov.cn/xzzfcon-467-1.html")
    assert {"htqzfxxgk", "xzcf"} <= path_tokens("https://www.hongta.gov.cn/htqzfxxgk/xzcf2/20211227/1.html")
    assert "zhifa" in path_tokens("https://wei.gov.cn/zhifa_show.php?cid=962&id=1")


def test_paging_patterns():
    assert page_count("共计 641 条 当前第 1 / 26 页 下一页") == 26
    assert page_count("<script>createPageHTML('page_div',67, 1,'zfxxgk','shtml',1000)</script>") == 67
    assert page_count("<script>createPageHTML(20, 0, 'index', 'html');</script>") == 20
    assert page_count('<a href="index_9.html">尾页</a>') == 10
    assert page_count("var countPage = 12;") == 12
    assert page_count("<p>没有翻页</p>") == 1
    assert total_items("<span>共计</span> 641 <span>条</span>") == 641
    assert total_items("共 1312 条") == 1312


def test_cms_family_and_params():
    jp = '<script src="/api-gateway/jpaas-publish-server/front/page/build/unit"></script> webId: "3558", tplSetId:"XG03", pageId: "1229150592"'
    assert cms_family(jp, "https://www.zjwy.gov.cn/col/col1229150592/index.html") == "hanweb_jpaas"
    assert family_params(jp, "hanweb_jpaas", "") == {"webId": "3558", "tplSetId": "XG03", "pageId": "1229150592"}
    gk = "<script>var SID = '766261';</script>"
    url = "https://www.yunan.gov.cn/yfyagaj/gkmlpt/content/2/2045/post_2045681.html"
    assert cms_family(gk, url) == "gkmlpt"
    assert family_params(gk, "gkmlpt", url) == {"base": "https://www.yunan.gov.cn/yfyagaj/gkmlpt", "sid": "766261"}
    assert cms_family("", "http://www.ahq.gov.cn/a/202409/t20240909_2404394.html") == "trs"


def _page(item_links: int, other_links: int, cat: str = "467") -> str:
    items = "".join(f'<a href="/xzzfcon-{cat}-{1000 + i}.html">定兴公行罚决字〔2025〕{i}号赌博</a>' for i in range(item_links))
    others = "".join(f'<a href="/news/{i}.html">新闻{i}</a>' for i in range(other_links))
    return f"<html>{items}{others}</html>"


def test_score_prefers_dense_list_over_homepage():
    seeds = ["https://www.dingxing.gov.cn/xzzfcon-467-33736.html"]
    loose, strict = {url_shape(s) for s in seeds}, {url_shape_strict(s) for s in seeds}
    list_score, n_list, _ = score_list_page(_page(20, 5), "https://www.dingxing.gov.cn/", loose, strict)
    home_score, n_home, _ = score_list_page(_page(10, 200), "https://www.dingxing.gov.cn/", loose, strict)
    other_dept, _, _ = score_list_page(_page(25, 5, cat="426"), "https://www.dingxing.gov.cn/", loose, strict)
    assert n_list == 20 and n_home == 10
    assert list_score > home_score
    assert list_score > other_dept  # 同类目优先于跨部门的同构列表


def test_blocked_ignores_captcha_word_on_normal_page():
    normal = "<html>" + "正文" * 3000 + "登录 验证码 </html>"
    assert blocked(200, normal) == ""
    assert blocked(200, "<html>请输入验证码</html>" + "x" * 400) == "blocked_or_js"
    assert blocked(200, "<script>document.cookie='__jsluid_s=1'</script>" + "x" * 6000) == "blocked_or_js"
    assert blocked(403, "x") == "http_403"


def test_dominant_seeds_pick_main_column():
    urls = ["http://www.xjbh.gov.cn/xjbhx/c109939/202504/a.shtml", "http://www.xjbh.gov.cn/xjbhx/c109939/202603/b.shtml",
            "http://www.xjbh.gov.cn/xjbhx/c109920/202601/c.shtml"]
    assert all("c109939" in u for u in dominant_seeds(urls))


def test_breadcrumb_links_skip_home():
    html = '<div class="position">当前位置：<a href="/">首页</a> &gt; <a href="/zfxxgk/fdzdgknr/cfqz">处罚强制</a></div>'
    assert breadcrumb_links(html, "https://www.xjtcsh.gov.cn/x/content_1") == ["https://www.xjtcsh.gov.cn/zfxxgk/fdzdgknr/cfqz"]
