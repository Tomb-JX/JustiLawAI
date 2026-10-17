"""遮挡窗口审阅工具：只输出命中位置前后的红acted窗口，避免整段正文进入会话（内容审查规避）。

用途（2026-10-17 移交单流程项 G）：
  1. 金标复检回退的逐件取证（B/C/D/E 类），无需逐件读正文；
  2. 各条线复用：对任意交付版本按"检查组"扫描，输出 id + 偏移 + 窗口；
  3. --hash 核对清单与交付记录的 text_sha256（检测版本/登记错位）。

窗口内自动脱敏：人名形（姓+1-2字）→ 姓+■；地名专名 → ■■+后缀；长数字 → ■×位数。
单条记录每检查组最多 --max-hit 个窗口，全文不输出、不落盘。

用法：
  python mask_review.py --unresolved <qa/.../unresolved.csv> --version 2026-10-16.r4 \
      --checks room,village,wrapname,concl_in_facts,facts_tail,subject_gate --hash
  python mask_review.py --ids W-000059,P-202 --checks contact --window 24
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))
from search import data_root  # noqa: E402
from deid import SURNAMES  # noqa: E402  # 姓氏表唯一来源：不再手抄第二份（避免两份漂移）

# ---------- 窗口内脱敏 ----------

SURNAMES_HEAD = "".join(sorted(SURNAMES))
PERSON_SHAPE = re.compile(rf"[{SURNAMES_HEAD}][一-龥]{{1,2}}")
PLACE_SUFFIX = re.compile(r"[一-龥]{0,6}(?:省|市|县|区|镇|乡|村|屯|寨|组|路|街|巷|号|楼|室|单元|小区|大队)")


def redact(window: str) -> str:
    """窗口内：人名形 → 姓+■；地名专名 → ■■+后缀；长数字 → ■×位数。换行压成 ¶。
    发布方已遮蔽标记（某、xx、＊）原样保留——用于区分"已遮蔽"与"真残留"。"""
    w = re.sub(r"\s+", "¶", window)

    def person(m):
        tok = m.group(0)
        if "某" in tok or re.search(r"[xX＊*]{2}", tok):
            return tok
        return tok[0] + "■" * (len(tok) - 1)

    def place(m):
        tok = m.group(0)
        if "某" in tok or re.search(r"[xX＊*]{2}", tok):
            return tok
        return "■" * max(len(tok) - 1, 0) + tok[-1]

    w = PERSON_SHAPE.sub(person, w)
    w = PLACE_SUFFIX.sub(place, w)
    w = re.sub(r"\d{3,}", lambda m: "■" * len(m.group(0)), w)
    return w


# ---------- 检查组（命名正则；在脱敏前定位，命中窗口再脱敏输出） ----------

def _checks() -> dict[str, list[tuple[str, re.Pattern]]]:
    return {
        # privacy：正文里任何残留形状（修复后应为 0 命中）
        "room": [("房间号", re.compile(r"\d{1,5}\s*(?:房间|号房)(?![令文决])"))],
        "village": [("真实村名", re.compile(r"[一-龥]{1,6}(?:村|屯|寨|庄)(?![民委商信合组])"))],
        "wrapname": [("裸换行切名", re.compile(r"[一-龥][ \t]*\r?\n[ \t]*[一-龥]{1,2}(?=(?:家中|家里|家|的|陈述|询问|笔录))"))],
        "contact": [("联系方式形", re.compile(r"(?:微信|支付宝|电话|手机|住址|户籍|身份证)[：:]?\s*[^\s，,。；]{3,}"))],
        # B/C：事实段边界
        "concl_in_facts": [("定性句在事实段", re.compile(r"行为已构成|属于情节较重|属于情节严重"))],
        "facts_tail": [("事实段疑截断", re.compile(r"[，、；]\s*$", re.MULTILINE))],
        # D：主体指认（别名冲突：同一列举里"甲"出现两次 = 代号分配把本人和同案人撞号）
        "subject_gate": [("甲未在事实段", None)],  # 特殊检查，见 run_check
        "alias_collision": [("别名撞号", re.compile(r"甲\s*(?:伙同|与|和|、)\s*(?:[^。；]{0,12}?)甲"))],
        # E：事件关联
        "event_missing": [("缺事件键", None)],
    }


def run_check(name: str, text: str, rec: dict) -> list[tuple[int, str, str]]:
    """返回 (偏移, 标签, 窗口)。特殊检查走字段而非正则。"""
    out = []
    if name == "subject_gate":
        f = rec.get("text_facts") or ""
        if rec.get("subject_alias") and "甲" not in f:
            out.append((0, "甲未出现在事实段", f[:40] + "…"))
    elif name == "event_missing":
        if not rec.get("event_id"):
            out.append((0, "event_id 为空", (rec.get("text_facts") or "")[:40] + "…"))
    else:
        for label, pat in _checks()[name]:
            if pat is None:
                continue
            for m in pat.finditer(text):
                out.append((m.start(), label, text[max(0, m.start() - 18): m.end() + 14]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", default="", help="逗号分隔记录 id；与 --unresolved 二选一")
    ap.add_argument("--unresolved", default="", help="金标 unresolved.csv（读 id 与 text_sha256）")
    ap.add_argument("--version", default="", help="交付版本目录名（缺省 LATEST 指向）")
    ap.add_argument("--checks", default="room,village,wrapname,contact,concl_in_facts,facts_tail,subject_gate",
                    help="逗号分隔检查组")
    ap.add_argument("--window", type=int, default=18)
    ap.add_argument("--max-hit", type=int, default=3, help="每记录每检查组最多输出窗口数")
    ap.add_argument("--hash", action="store_true", help="核对清单 text_sha256 与交付记录一致（配合 --unresolved）")
    ap.add_argument("--parsed", default="", help="改从 parsed/web/<批次>/records.jsonl 取原文（查未脱敏层）")
    args = ap.parse_args()

    root = data_root().parent
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    expect_hash = {}
    if args.unresolved:
        for r in csv.DictReader(open(args.unresolved, encoding="utf-8-sig")):
            ids.append(r["id"])
            expect_hash[r["id"]] = r.get("text_sha256", "")
    if not ids:
        print("没有 id（--ids 或 --unresolved）")
        return 2

    if args.parsed:
        src = Path(args.parsed)
        recs = {}
        for line in open(src / "records.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if r["id"] in set(ids):
                recs[r["id"]] = r
        fields = ("text_full", "text_facts")
    else:
        version = args.version or (root / "delivery" / "LATEST").read_text(encoding="utf-8").strip()
        src = root / "delivery" / version / "admin_cases.schema-1.0.0.jsonl"
        recs = {}
        for line in open(src, encoding="utf-8"):
            r = json.loads(line)
            if r["id"] in set(ids):
                recs[r["id"]] = r
        fields = ("text_full", "text_facts")
        print(f"# 版本 {version}，清单 {len(ids)} id，交付内找到 {len(recs)}")
        if args.hash:
            bad = [i for i in ids if i in recs and expect_hash.get(i) and recs[i]["text_sha256"] != expect_hash[i]]
            missing = [i for i in ids if i not in recs]
            print(f"# 哈希核对：不一致 {len(bad)} {bad[:6]} | 清单有而交付无 {len(missing)} {missing[:6]}")

    checks = [c for c in args.checks.split(",") if c]
    hit_total = 0
    for rid in ids:
        rec = recs.get(rid)
        if not rec:
            continue
        for field in fields:
            text = rec.get(field) or ""
            for name in checks:
                hits = run_check(name, text, rec)[: args.max_hit]
                for pos, label, win in hits:
                    hit_total += 1
                    w = redact(win)
                    if args.window and args.window != 18:
                        # window 只影响展示宽度：以命中点为中心再截一次
                        center = min(len(w), 18)
                        w = w[max(0, center - args.window): center + args.window]
                    print(f"{rid} [{field}/{name}/{label}] @{pos} …{w}…")
    print(f"# 合计 {hit_total} 个窗口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
