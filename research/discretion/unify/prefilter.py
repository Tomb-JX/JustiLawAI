"""预筛 v2 放行阀（parse-format-chain-design v1.2 §6，Q9/Q10 决策）。

放行规则（定稿）= 是 ∪ 待定 ∪ borderline（133 中的 72：引证简写 56 + 无公安有治安法 16）
                ∪ "否"池 5% 分层抽样（≈140，种子固定可复现）。
in_scope 语义判定不在本层——组装层按模型产出重推导；本层只是成本阀门。

两源词表并集 19+1 词（Q10）：web 15 词 + pkulaw 12 词去重；消除同案异判。
"""

from __future__ import annotations

import random
import re

SAMPLE_SEED = 20261017
SAMPLE_TARGET = 140  # 否池抽检目标（2,814 的 5% ≈ 140）

# 两源词表并集（web 独有 7 + pkulaw 独有 4 + 共有 8）
GAMBLING_UNION = re.compile(
    r"赌博|赌资|参赌|聚赌|开设赌场|抽头|炸金花|推饼|六合彩|牛牛|押宝|赌具|涉赌|麻将"
    r"|斗地主.{0,10}输赢|牌九|比鸡|老虎机|赌博机")

# 前科句式（web 预筛"前科护栅"的针对面，抽样分层 A）
PRIOR_RECORD = re.compile(r"(?:另查明|此前|曾经|曾)[^。]{0,30}?因(?:参与)?赌博")
# 简写引证（分层 B）：含条号字样但缺"治安管理处罚法"全称
ABBR_CITE = re.compile(r"第七十条|第八十二条")
LAW_FULL = "治安管理处罚法"


def judged_zone(rec: dict, cleaned: str) -> str:
    """预筛判定区：与 web 现行口径一致——有事实段取 facts+decision+review，否则全文。"""
    facts = (rec.get("text_facts") or "").strip()
    if facts:
        return facts + (rec.get("text_decision") or "") + (rec.get("text_review") or "")
    return cleaned


def _ctx(rec: dict) -> str:
    """机关名可能只出现在页头/标题/发布方（web）或事件线索里（pkulaw）——police 判定的上下文。"""
    ex = rec.get("extra") or {}
    parts = [ex.get("title") or "", ex.get("publisher") or ""]
    legacy = ex.get("legacy")
    if isinstance(legacy, dict):
        hint = legacy.get("event_hint")
        if isinstance(hint, dict):
            parts.append(str(hint.get("authority") or ""))
    return "".join(str(p) for p in parts if p)


def borderline_of(rec: dict, cleaned: str) -> str:
    """gambling=是 时的边缘标记：cite_abbrev（有公安缺治安法全称，实测 56 件）/
    authority_ctx（无公安有治安法，16 件）/ ""（两者皆缺 61 件 → 不放行，进抽样池）。"""
    zone = rec.get("text_decision") or ""
    has_gongan = bool(re.search("公安", (rec.get("authority") or "") + zone + cleaned[:400] + _ctx(rec)))
    has_zhian = LAW_FULL in (zone + cleaned)
    if has_gongan and not has_zhian:
        return "cite_abbrev"
    if has_zhian and not has_gongan:
        return "authority_ctx"
    return ""


def stratum_of(rec: dict, cleaned: str) -> str:
    """"否"池分层（抽样优先级 A>B>C>D，实测边缘面：前科 20 / 简写 11 / 判定区外命中 8）。"""
    zone = judged_zone(rec, cleaned)
    if PRIOR_RECORD.search(cleaned):
        return "A_前科句式"
    if ABBR_CITE.search(cleaned) and LAW_FULL not in cleaned:
        return "B_简写引证"
    if GAMBLING_UNION.search(zone):
        return "C_判定区涉赌词"
    return "D_其余"


# 程序性页面（min-40 队列上游修复项 a：权责清单/裁量基准/结果汇总表等非个案页）
NORM_PAGE = re.compile(r"权责清单|责任清单|事项清单|实施依据.{0,20}责任|送达.{0,6}责任|"
                       r"行使该职权的责任|^\s*行政处罚结果.{0,20}(索引号|有效性)")


def eval_prefilter(rec: dict, cleaned: str) -> dict:
    """单记录预筛字段（抽样在批级 sample_pool 完成）。
    norm_page（程序性页面，队列件 W-000648-45 类）即使三态=是 也拦截——上游 min-40 稳定化。"""
    q = rec.get("quality") or {}
    gamb = q.get("gambling") or "待定"
    norm = bool(NORM_PAGE.search((rec.get("authority") or "") + cleaned[:500]))
    borderline = borderline_of(rec, cleaned) if gamb == "是" else ""
    if norm:
        release, reason = False, "norm_page"
    elif gamb in ("是", "待定"):
        release, reason = True, f"gamb:{gamb}"
    elif borderline:
        release, reason = True, f"borderline:{borderline}"
    else:
        release, reason = False, ""
    return {
        "gambling": gamb,
        "borderline": borderline,
        "norm_page": norm,
        "release": release,
        "release_reason": reason,
        "stratum": "" if gamb != "否" else stratum_of(rec, cleaned),
        "in_scope_v1": bool(q.get("in_scope")),
    }


def sample_pool(pool: list[dict], target: int = SAMPLE_TARGET, seed: int = SAMPLE_SEED) -> set[str]:
    """"否"池分层抽样：A/B/C 边缘层全取，不足目标再从 D 层按固定种子随机补齐（同种子可复现）。"""
    by_stratum: dict[str, list[str]] = {}
    for rec in pool:
        s = rec["_unified"]["prefilter"]["stratum"]
        by_stratum.setdefault(s, []).append(rec["id"])
    picked: list[str] = []
    for s in ("A_前科句式", "B_简写引证", "C_判定区涉赌词"):
        ids = sorted(by_stratum.get(s, []))
        if len(picked) + len(ids) <= target:
            picked.extend(ids)
        else:
            rng = random.Random(seed)
            rng.shuffle(ids)
            picked.extend(sorted(ids[: target - len(picked)]))
    rest = sorted(by_stratum.get("D_其余", []))
    remain = target - len(picked)
    if remain > 0 and rest:
        rng = random.Random(seed)
        rng.shuffle(rest)
        picked.extend(sorted(rest[:remain]))
    return set(picked)
