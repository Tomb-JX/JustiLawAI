"""S0 清理引擎单测（合成样例，姓名均为虚构）。核心不变量：replay(orig) == cleaned 逐字一致。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleanse import cleanse, replay_edits  # noqa: E402


def r(orig: str, ch: str = "web"):
    res = cleanse(orig, ch)
    assert res.replay(orig) == res.cleaned, f"回放不一致：{res.cleaned!r}"
    # RLE 区间重建长度守恒：kept 长度之和 + 删除长度 = 原文长度
    kept = sum(ln for _s, ln, _cs, _cl in res.kept_intervals())
    dsum = sum(ln for _s, ln in (x for rr in res.deletes.values() for x in rr))
    subs_n = sum(len(v) for v in res.subs.values())
    assert kept + dsum - subs_n == 0 or kept + dsum == res.orig_len
    return res


# ---------- 空白归一 ----------

def test_ws_fold_collapse():
    res = r("甲某在2023年5月赌博。 乙某  丙某")
    assert res.cleaned == "甲某在2023年5月赌博。 乙某 丙某"


def test_ws_fold_newlines():
    assert r("段落甲。\n\n\n段落乙。").cleaned == "段落甲。\n段落乙。"
    assert r("  开头空白").cleaned == "开头空白"
    assert r("结尾空白  ").cleaned == "结尾空白"
    assert r("行尾空格   \n下一行").cleaned == "行尾空格\n下一行"


def test_ws_chars_sub():
    res = r("甲\u3000乙\t丙")
    assert res.cleaned == "甲 乙 丙"
    assert set(res.subs) == {"ws_chars"}


# ---------- 日期变体 ----------

def test_date_variant():
    assert r("行为时间2023．5。8日。").cleaned == "行为时间2023.5.8日。"
    assert r("句号结尾。下句。").cleaned == "句号结尾。下句。"  # 非数字间不触发


# ---------- 管道 ----------

def test_pipe_table_multi():
    # 管道拆行 + 键值感知拼接：标签行接值 → "标签：值"；下行是标签 → 保留换行
    res = r("违法事实|张某某聚赌|处罚种类|行政拘留", "pkulaw")
    assert res.cleaned == "违法事实：张某某聚赌\n处罚种类：行政拘留"


def test_pipe_single_join():
    assert r("张某某在某处聚赌|后被查获").cleaned == "张某某在某处聚赌后被查获"


# ---------- 逗号尾续行（pkulaw 册） ----------

def test_comma_join():
    res = r("张某某等人赌博，\n违法所得五千元。", "pkulaw")
    assert res.cleaned == "张某某等人赌博，违法所得五千元。"


# ---------- 导航样板（白名单：行短、无句号、锚定行首） ----------

def test_nav_removed():
    res = r("首页 > 专题专栏 > 警务公开\n2023年5月，张某某在某棋牌室赌博。\n发布时间：2023-06-01\n来源：某某县公安局")
    assert "首页" not in res.cleaned and "发布时间" not in res.cleaned and "来源：" not in res.cleaned
    assert "张某某在某棋牌室赌博" in res.cleaned


def test_nav_whitelist_keeps_prose():
    text = "来源：当事人自述材料经审查属实，以上事实有证据佐证。"
    assert r(text).cleaned == text  # 含句号的长行不删


# ---------- 短片段裸换行（键值感知），长散文行保留 ----------

def test_cell_wrap_label_becomes_kv():
    assert r("违法事实\n张某某在某棋牌室赌博").cleaned == "违法事实：张某某在某棋牌室赌博"


def test_cell_wrap_keeps_newline_before_next_label():
    # 连续键值块（标签行/值行交替）：标签接值用冒号，值后遇新标签保留换行
    text = "行政处罚机关\n某某县公安局\n行政处罚决定书文号\n某公（行）行罚决字〔2023〕5号"
    assert r(text).cleaned == "行政处罚机关：某某县公安局\n行政处罚决定书文号：某公（行）行罚决字〔2023〕5号"


def test_cell_wrap_value_continuation_joins():
    # 前行已带冒号（值续行）→ 直接拼接
    assert r("案件名称：张某某等人\n赌博案").cleaned == "案件名称：张某某等人赌博案"


def test_cell_wrap_prose_kept():
    text = "经查明，违法行为人张某某伙同他人在某茶楼内以麻将牌九方式进行赌博活动赌资数额较大\n后被公安机关当场查获并依法处理并处罚款人民币叁仟元。"
    assert r(text).cleaned == text  # 两侧长行（>20字）不拼接


# ---------- 编辑日志独立回放 ----------

def test_edits_replay_without_module_rules():
    orig = "首页 > 专题专栏\n违法事实\n张某某聚赌，\n赌资2023．5。8元。 "
    res = cleanse(orig, "web")
    assert replay_edits(orig, res.to_edits()) == res.cleaned


def test_empty():
    assert cleanse("", "web").cleaned == ""
