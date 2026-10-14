"""渠道 B 收割后的赌博案初筛：扫描已抽取的正文 .txt，按关键词命中分级。

关键词分级（初筛用，金标仍由法律组逐件确认）：
  强命中：赌博 / 赌资 / 赌资较大 / 开设赌场 / 麻将 / 赌博机
  弱命中：治安管理处罚法 + 拘留（可能只是引用法条）

用法：python filter_gambling.py          # 扫 research/data/reconsider/ 全部站点
产出：research/data/reconsider/gambling_hits.md（含每件命中的关键词与上下文摘录）
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from common import DATA_DIR, report

ROOT = DATA_DIR / "reconsider"
STRONG = ["赌博", "赌资", "开设赌场", "麻将", "赌博机", "押牌", "抽头"]
WEAK = ["治安管理处罚法", "行政拘留", "公安分局", "派出所"]


def ctx(text: str, kw: str, width: int = 40) -> str:
    m = re.search(kw, text)
    if not m:
        return ""
    s = max(0, m.start() - width)
    return re.sub(r"\s+", "", text[s : m.end() + width])


def main() -> None:
    lines = ["# 渠道 B 赌博案初筛结果", "", f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}", ""]
    n_total = n_strong = 0
    for site_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        txts = sorted(site_dir.glob("*.txt"))
        if not txts:
            continue
        lines += [f"## {site_dir.name}（{len(txts)} 件）", ""]
        s_here = 0
        for t in txts:
            n_total += 1
            text = t.read_text(encoding="utf-8", errors="ignore")
            strong = [k for k in STRONG if k in text]
            weak = [k for k in WEAK if k in text]
            if strong:
                n_strong += 1
                s_here += 1
                lines += [
                    f"### ✅ {t.stem[:60]}",
                    f"- 强命中：{'、'.join(strong)}｜弱特征：{'、'.join(weak) or '无'}",
                    f"- 上下文：…{ctx(text, strong[0])}…",
                    "",
                ]
            elif len(weak) >= 2:
                lines += [f"- ⚠️ 疑似（仅弱特征）：{t.stem[:60]}（{'、'.join(weak)}）"]
        lines += [f"**本站强命中 {s_here}/{len(txts)}**", ""]

    out = ROOT / "gambling_hits.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    report(f"扫描 {n_total} 件，强命中 {n_strong} 件 → {out}")


if __name__ == "__main__":
    main()
