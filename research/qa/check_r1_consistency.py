"""r1 叙事-结构化一致性确定性检查（金标质检线）。

不依赖模型：用正则从 text_decision / text_full 抽取处罚叙述，与 outcome 结构化字段比对，
并做法条版本、日期、不予处罚一致性检查。扫 r1 主文件全部记录。

检查项：
  amount   正文罚款叙述 vs outcome.fine（中文数字转换；不一致=error）
  penalty  正文拘留天数 vs outcome.detention_days（含合并执行；不一致=error）
  nopunish 正文"不予处罚" vs outcome.type=不予处罚（矛盾=error）
  lawver   outcome.articles 引用版本 vs 顶层 law_version（矛盾=error）
  datever  behavior_date>=2026 却引用旧法条文（=error）；决定早于行为（=warn）

用法：python check_r1_consistency.py <r1主文件> <输出目录>
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000, "仟": 1000, "万": 10000}


def cn_to_int(s: str) -> int | None:
    """中文数字转整数（支持 混合阿拉伯数字、五百、一千九百、壹仟、3万五千 等常见形态）。"""
    s = s.replace("佰", "百").replace("拾", "十").replace("捌", "八").replace("陆", "六") \
         .replace("柒", "七").replace("叁", "三").replace("贰", "二").replace("壹", "一")
    if not s:
        return None
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)", s)
    if m:
        return int(float(m.group(1)))
    total, section, num = 0, 0, 0
    ok = False
    for ch in s:
        if ch in CN_NUM:
            num = CN_NUM[ch]
            ok = True
        elif ch in CN_UNIT:
            if ch == "万":
                section = (section + num) * CN_UNIT[ch] if (section + num) else CN_UNIT[ch]
                total += section
                section, num = 0, 0
            else:
                section += (num or 1) * CN_UNIT[ch]
                num = 0
            ok = True
        else:
            return None
    if not ok:
        return None
    return total + section + num


def find_amounts(text: str) -> list[int]:
    """从文本抽罚款叙述金额：'罚款X元' / '罚款人民币X元'。"""
    out = []
    for m in re.finditer(r"罚款(?:人民币)?([0-9一二三四五六七八九十百千两壹贰叁肆伍陆柒捌玖零佰拾万]+)元", text):
        v = cn_to_int(m.group(1))
        if v is not None:
            out.append(v)
    return out


def find_detentions(text: str) -> list[int]:
    out = []
    for m in re.finditer(r"(?:拘留|合并执行行政拘留|行政拘留)([0-9一二三四五六七八九十两壹贰叁肆伍陆柒捌玖零佰拾]+)日", text):
        v = cn_to_int(m.group(1))
        if v is not None:
            out.append(v)
    return out


def d(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.strptime(s[:7], "%Y-%m")
        except ValueError:
            return None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, outdir = Path(argv[1]), Path(argv[2])
    issues = []
    n = 0
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n += 1
        rid = r["id"]
        dec_text = r.get("text_decision") or ""
        full = r.get("text_full") or ""
        oc = r.get("outcome") or {}

        # amount
        fines = find_amounts(dec_text) or find_amounts(full[: len(dec_text) + 200])
        fine_field = oc.get("fine")
        if fines and isinstance(fine_field, (int, float)) and fine_field > 0:
            if fine_field not in fines:
                issues.append({"id": rid, "check": "amount", "level": "error",
                               "detail": f"outcome.fine={fine_field} 但正文罚款叙述为 {fines}",
                               "evidence": ""})
        # penalty
        dets = find_detentions(dec_text)
        det_field = oc.get("detention_days")
        if dets and isinstance(det_field, (int, float)) and det_field > 0:
            if det_field not in dets and det_field != sum(dets) and max(dets) != det_field:
                issues.append({"id": rid, "check": "penalty", "level": "error",
                               "detail": f"outcome.detention_days={det_field} 但正文拘留叙述为 {dets}",
                               "evidence": ""})
        # nopunish
        t = oc.get("type")
        if t and t != "不予处罚" and re.search(r"不予处罚", dec_text) and not re.search(r"不得不予处罚|不予处罚的", dec_text):
            if "不予处罚" in (r.get("text_review") or ""):
                pass  # 复议段出现不算
            else:
                issues.append({"id": rid, "check": "nopunish", "level": "warn",
                               "detail": f"决定段含'不予处罚'但 outcome.type={t}",
                               "evidence": ""})
        # lawver
        arts = oc.get("articles") or []
        has2025 = any("2025" in a for a in arts)
        has2012 = any("2012" in a or ("第七十条" in a and not has2025) for a in arts)
        lv = r.get("law_version")
        if has2025 and lv == "旧法":
            issues.append({"id": rid, "check": "lawver", "level": "error",
                           "detail": f"引用 2025 条文但 law_version=旧法: {arts}",
                           "evidence": ""})
        if has2012 and lv == "新法":
            issues.append({"id": rid, "check": "lawver", "level": "error",
                           "detail": f"引用旧法条文但 law_version=新法: {arts}", "evidence": ""})
        # datever
        b, dd = d(r.get("behavior_date")), d(r.get("decision_date"))
        if b and b.year >= 2026 and lv == "旧法":
            issues.append({"id": rid, "check": "datever", "level": "error",
                           "detail": f"行为 {r.get('behavior_date')} 在 2026 后却适用旧法", "evidence": ""})
        if b and dd and dd < b:
            issues.append({"id": rid, "check": "datever", "level": "warn",
                           "detail": f"决定 {r.get('decision_date')} 早于行为 {r.get('behavior_date')}",
                           "evidence": ""})

    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "consistency_issues.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "check", "level", "detail", "evidence"])
        w.writeheader()
        w.writerows(issues)
    c: dict[str, dict[str, int]] = {}
    for i in issues:
        c.setdefault(i["check"], {})[i["level"]] = c.setdefault(i["check"], {}).get(i["level"], 0) + 1
    print(json.dumps({"n_records": n, "n_issues": len(issues), "by_check": c}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
