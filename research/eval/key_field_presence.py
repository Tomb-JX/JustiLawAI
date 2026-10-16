"""关键字段出现率扫描：判断一批交付数据能不能支撑 M1 抽取器（引擎侧约束的对齐度量）。

为什么需要：门禁 G2.1 要求"关键字段准确率 ≥0.95"，但如果金标里某个字段绝大多数是"未提及"，
模型只要学会输出"未提及"就能拿高准确率——指标虚高而能力为零。所以**每个批次交付前**先量一遍：
这 10 个关键字段（schema v1.0.0 KEY_FIELDS）在文本里到底出现多少。

用法（仓库根目录）：
  python research/eval/key_field_presence.py --jsonl <交付 JSONL 或目录> [--tier L1]
输出：每个关键字段的出现率 + 组合指标（可算人均赌资、可判营利目的）+ 标签完整度。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter

# 关键字段 → 文本标记（口径依据 justilaw-api/app/discretion/schema.py 的字段说明）
MARKERS: dict[str, str] = {
    "conduct.behavior_type": r"参与赌博|为赌博提供条件|提供条件|聚众赌博|赌博活动|以赌博为业|开设赌场|参与网络赌博",
    "conduct.role": r"召集|组织|提供条件|望风|放贷|抽头|受雇|监管场子|坐庄",
    "conduct.method": r"麻将|扑克|牌九|斗牛|比鸡|进园子|德州|六合彩|赌博机|老虎机|网络|手机|微信|棋牌|骰子|炸金花|龙虎|游戏|网银|充值",
    "amounts.personal_stake": r"携带赌资|个人赌资|本人赌资|携带.{0,4}元|带赌资",
    "amounts.onsite_stake_total": r"现场查获赌资|查获赌资|赌资共计|赌资合计|查获赌博资金|现场查获.{0,4}赌资",
    "amounts.commission": r"抽头|渔利|台费|头钱|提成|抽水|抽成",
    "persons.participant_count": r"参赌人员|余名|余人|等人|人参与|人进行赌博|同案|伙同|共[0-9一二三四五六七八九十]+人",
    "intent.profit_purpose": r"营利|抽头|台费|收费|牟利|获利|赢利",
    "circumstances.last_prior_penalty_date": r"(因赌博|曾因|前科|受过).{0,20}?(行政拘留|行政处罚|治安管理处罚|处罚)",
    "person.age": r"[0-9一二三四五六七八九十]{1,3}\s*岁|周岁|\d{4}年\d{1,2}月\d{1,2}日出生",
}
# 组合指标：这些字段同时出现时，引擎才能算衍生量/判定性
COMBOS = {
    "可算人均赌资（现场赌资 + 人数）": (r"现场查获赌资|查获赌资", r"参赌人员|等人|余人|伙同"),
    "可判营利目的（抽头/台费/收费）": (r"抽头|渔利|台费|头钱|抽成", None),
    "有前科可判从重（日期+处罚）": (r"(因赌博|曾因).{0,20}?(行政拘留|行政处罚)", None),
}


def load(path: pathlib.Path, tier: str) -> list[dict]:
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if tier and not str(r.get("quality", {}).get("tier", "")).startswith(tier):
                continue
            out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="交付 JSONL 或含 JSONL 的目录")
    ap.add_argument("--tier", default="L1", help="只统计该分级（默认 L1；空字符串=全部）")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK，否则中文和 ⚠ 会乱码或报错

    records = load(pathlib.Path(args.jsonl), args.tier)
    if not records:
        raise SystemExit("没有记录（检查路径与 --tier）")
    n = len(records)
    print(f"样本 {n} 件（tier={args.tier or '全部'}）\n")

    print(f"{'关键字段':<44}{'出现率':>7}  评价")
    rates = {}
    for k, pat in MARKERS.items():
        rx = re.compile(pat)
        c = sum(1 for r in records if rx.search(r.get("text_facts") or ""))
        rates[k] = c / n
        verdict = ("可学" if c / n >= .6 else "偏少（大量会是'未提及'）" if c / n >= .2 else "极缺（该字段基本学不到）")
        print(f"{k:<44}{c / n:>6.0%}  {verdict}")

    print("\n组合指标（引擎侧衍生量/定性判断的前置）:")
    for name, (p1, p2) in COMBOS.items():
        rx1, rx2 = re.compile(p1), (re.compile(p2) if p2 else None)
        c = sum(1 for r in records
                if rx1.search(r.get("text_facts") or "") and (rx2 is None or rx2.search(r.get("text_facts") or "")))
        print(f"  {name}: {c}/{n} = {c / n:.0%}")

    lab = Counter()
    for r in records:
        o = r.get("outcome") or {}
        lab["有数额（拘留天数或罚款额）"] += bool(o.get("detention_days") or o.get("fine"))
        lab["只有类型无数额"] += bool(o.get("type") and not (o.get("detention_days") or o.get("fine")))
        lab["引用了法条"] += bool(o.get("articles"))
    print("\n标签侧完整度:", dict(lab))
    low = [k for k, v in rates.items() if v < .2]
    if low:
        print(f"\n⚠ 低出现率字段（{len(low)}/10）：{', '.join(low)}")
        print("  提醒：这些字段的报告必须同时给'非空字段准确率'，否则'未提及'占多数会让准确率虚高（门禁 G2.1 的陷阱）。")


if __name__ == "__main__":
    main()
