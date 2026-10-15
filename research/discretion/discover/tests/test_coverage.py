"""覆盖统计与定向扩面单测：省份归属投票、按省汇总、定向种子。合成数据，不联网。

运行（仓库根目录）：python -m pytest research/discretion/discover/tests -q
"""

from __future__ import annotations

from coverage import attribute_sites, place_index, summarize, table
from plan import load_config, seeds, seeds_targeted, split

CFG = load_config()


def test_targeted_seeds_use_city_full_names():
    qs = seeds_targeted(CFG, ["山西"])
    assert len(qs) == len(CFG["targets"]["山西"]) * 2
    assert qs[0].text(CFG) == "行政处罚决定书 赌博 太原市 site:gov.cn"
    assert all(q.template not in ("tc", "tf") for q in seeds(CFG))  # 定向模板不进常规种子
    child = split(qs[0], CFG)
    assert child and all(c.region == "太原市" and c.feature for c in child)  # 顶格先按特征词拆


def test_place_index_long_names_first():
    names = [n for n, _ in place_index(CFG)]
    assert names.index("内蒙古") < names.index("北京")  # 省名按长度降序
    assert ("玉溪市", "云南") in place_index(CFG)


def test_attribute_sites_votes():
    rows = [
        # 定向查询命中 + 标题写了地级市：强证据
        {"url": "u1", "host": "www.hongta.gov.cn", "publisher": "玉溪市红塔区人民政府", "title": "", "query_id": "tc|r=玉溪市|t=*|f=*"},
        # 只有摘录里的户籍地写了别省地名：弱证据，不足以改判
        {"url": "u2", "host": "www.hongta.gov.cn", "publisher": "", "title": "", "query_id": "sw|s=hongta.gov.cn"},
        # 无任何地名线索
        {"url": "u3", "host": "www.unknown.gov.cn", "publisher": "某县人民政府", "title": "", "query_id": "fy70|r=*"},
        # 摘录里有省名
        {"url": "u4", "host": "www.dingxing.gov.cn", "publisher": "定兴县人民政府办公室", "title": "", "query_id": "sw"},
    ]
    hits = {"u2": {"content": "户籍地：浙江省杭州市"}, "u4": {"content": "户籍所在地为河北省保定市"}}
    prov = attribute_sites(rows, hits, CFG)
    assert prov["hongta.gov.cn"] == "云南"
    assert prov["unknown.gov.cn"] == "未识别"
    assert prov["dingxing.gov.cn"] == "河北"


def test_query_city_needs_textual_support():
    # "宝山区"定向查询带回了河北定兴的文书：文书里没有"宝山区"，不能因此判给上海
    rows = [{"url": f"d{i}", "host": "www.dingxing.gov.cn", "publisher": "定兴县人民政府办公室", "title": "",
             "query_id": "tc|r=宝山区|t=*|f=*"} for i in range(5)]
    hits = {"d0": {"content": "户籍所在地为河北省保定市"}}
    assert attribute_sites(rows, hits, CFG)["dingxing.gov.cn"] == "河北"
    sh = [{"url": "s", "host": "www.shbsq.gov.cn", "publisher": "上海市宝山区人民政府", "title": "", "query_id": "tc|r=宝山区"}]
    assert attribute_sites(sh, {}, CFG)["shbsq.gov.cn"] == "上海"


def test_summarize_and_table():
    rows = [{"url": "a", "host": "www.hongta.gov.cn", "doc_type": "处罚汇总", "year": "2026", "law_article": "82"},
            {"url": "b", "host": "www.hongta.gov.cn", "doc_type": "复议", "year": "2024", "law_article": "70"}]
    snap = summarize(rows, {"hongta.gov.cn": "云南"}, {"hongta.gov.cn": {"saturated": True}},
                     [{"domain": "www.hongta.gov.cn", "status": "ok", "est_items": "120"}])
    y = snap["云南"]
    assert (y["sites"], y["docs"], y["decisions"], y["reviews"], y["y2026"], y["law82"]) == (1, 2, 1, 1, 1, 1)
    assert (y["sites_swept"], y["sites_saturated"], y["columns_ok"], y["columns_ok_items"]) == (1, 1, 1, 120)
    md = table(snap, ["云南", "山西"], before={"云南": {"docs": 1}})
    assert "| 云南 | 1 → **1** |" not in md and "1 → **2**" in md and "| 山西 | 0 |" in md
