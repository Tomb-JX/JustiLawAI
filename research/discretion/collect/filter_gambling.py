"""渠道 B 收割后的赌博案初筛：扫描已抽取的正文 .txt，按关键词命中分级。

关键词分级（初筛用，金标仍由法律组逐件确认）：
  强命中：行为词（参与赌博/为赌博提供条件/赌资/赌具/聚众赌博/开设赌场/赌博机/押牌/抽头），
          或扣除两类噪声后仍有"赌博"且伴随处罚结果词
  弱命中：治安管理处罚法 + 拘留（可能只是引用法条）
两类已知噪声（2026-10-16 按引擎 triage.py 与裁判文书网实测规则移植）：
  ① 管辖条款："卖淫、嫖娼、赌博、毒品"（《公安机关办理行政案件程序规定》第十条，
     任何治安案件都可引用——裁判文书网实测该句使行政判决全文"赌博"检索噪声过半）；
  ② 纯法条引用：除管辖条款外全文只有"赌博"字样、无任何行为/结果语境（东城唯一"强命中"即此误报）。

用法：python filter_gambling.py          # 扫 $JUSTILAW_DATA_DIR/reconsider/ 全部站点
产出：$JUSTILAW_DATA_DIR/reconsider/gambling_hits.md（含每件命中的关键词与上下文摘录）
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from common import DATA_DIR, report

ROOT = DATA_DIR / "reconsider"
CORE = ["参与赌博", "为赌博提供条件", "赌资", "赌具", "聚众赌博", "开设赌场", "赌博机", "押牌", "抽头"]
WEAK = ["治安管理处罚法", "行政拘留", "公安分局", "派出所"]
RESULT = ["拘留", "罚款", "处罚", "不予处罚", "警告"]
# 管辖条款：四个违法行为并列列举，无论顿号/逗号/顺序微差
JURISDICTION = re.compile(r"卖淫\s*[、，,]\s*嫖娼\s*[、，,]\s*赌博(\s*[、，,]\s*毒品)?")
# 条文语境：命中词 ±25 字内出现"第×条"，或落在含"第×条"的整段引文（“……”）内，均视为引用法条原文
ARTICLE_REF = re.compile(r"第[一二三四五六七八九十百零\d]{1,4}条")
QUOTED = re.compile(r"“(.*?)”", re.S)


def strip_jurisdiction(text: str) -> str:
    return JURISDICTION.sub("。", text)


def _statute_spans(text: str) -> list[tuple[int, int]]:
    spans = [(m.start() - 40, m.end() + 40) for m in ARTICLE_REF.finditer(text)]
    spans += [(m.start(1), m.end(1)) for m in QUOTED.finditer(text) if ARTICLE_REF.search(m.group(1))]
    return spans


def hits_outside_statute(text: str, kw: str) -> int:
    """统计不在条文引用语境里的关键词出现次数。"""
    n = 0
    for m in re.finditer(re.escape(kw), text):
        if not any(s <= m.start() <= e for s, e in _statute_spans(text)):
            n += 1
    return n


def ctx(text: str, kw: str, width: int = 40) -> str:
    m = re.search(kw, text)
    if not m:
        return ""
    s = max(0, m.start() - width)
    return re.sub(r"\s+", "", text[s : m.end() + width])


def main() -> None:
    lines = [
        "# 渠道 B 赌博案初筛结果",
        "",
        f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M')}｜规则：行为词强命中；纯法条引用与管辖条款不算（详见脚本头注）",
        "",
    ]
    n_total = n_strong = 0
    for site_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        txts = sorted(site_dir.glob("*.txt"))
        if not txts:
            continue
        lines += [f"## {site_dir.name}（{len(txts)} 件）", ""]
        s_here = 0
        for t in txts:
            n_total += 1
            text = strip_jurisdiction(t.read_text(encoding="utf-8", errors="ignore"))
            core = [k for k in CORE if hits_outside_statute(text, k)]
            weak = [k for k in WEAK if k in text]
            bare = hits_outside_statute(text, "赌博") and any(r in text for r in RESULT)
            if core or bare:
                n_strong += 1
                s_here += 1
                show = core or ["赌博(伴随结果词)"]
                lines += [
                    f"### ✅ {t.stem[:60]}",
                    f"- 强命中：{'、'.join(show)}｜弱特征：{'、'.join(weak) or '无'}",
                    f"- 上下文：…{ctx(text, core[0] if core else '赌博')}…",
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
