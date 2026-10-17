"""R6 隐私扫描（文本处理规范 docs/04-plan/text-processing-spec.md §4.3）：脱敏后的文本零硬命中才算通过。

硬命中（任一即不通过）：身份证号（含部分遮挡）、长串数字（银行卡、账号）、手机号、固话、车牌、邮箱、门牌（"12号""3单元""501室"）、
  残留的遮挡人名（"李xx""韦*林"）、残留的称谓 + 遮挡写法、精确到日的日期与时分、出生日期。
软命中（交人工复核，不阻断）：未替换成代号的姓名候选（百家姓开头、出现在人名语境里）、带名称的派出所、"民警××"。
  复核后确认不是人名的词写进 r6_whitelist.txt（一行一个，入库；只放普通词，不放人名）。
两次扫描：build.py 交付前对每件扫一次（硬命中的案例不交付，列入排除清单）；封存测试集前再对交付文件整体扫一次：
  python research/discretion/harvest/r6_scan.py $JUSTILAW_DATA_DIR/admin/admin_cases.schema-1.0.0.jsonl
扫描报告写在交付文件旁（r6_report.json；命中片段可能含原文，不入库）。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from deid import (ALIASES, FUNC, MASK, MASK_CH, MASKED, REAL, SEP, STATION_STOP, STOP_WORDS, apply,  # noqa: E402
                  cell_wraps, looks_like_name)

WHITELIST = HERE / "r6_whitelist.txt"
TEXT_FIELDS = ("text_full", "text_facts", "text_evidence", "text_reasoning", "text_decision", "text_review", "title")
ADMIN = "区县市省镇乡村街路旗州盟"

HARD = [
    ("id", re.compile(r"(?<![\dA-Za-z])\d{17}[\dXx](?![\dA-Za-z])")),
    ("id_masked", re.compile(rf"(?<![\dA-Za-z])\d{{1,6}}{MASK}{{3,}}\d{{0,4}}(?![\d{MASK_CH}.]*元)|{MASK}{{6,}}")),
    ("long_number", re.compile(r"(?<![\d.])\d{12,}(?![\d.])")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")),
    ("plate", re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][·\s]?[A-Z0-9]{5,6}(?![A-Za-z0-9])")),
    ("email", re.compile(r"[\w.-]+@[\w-]+\.[A-Za-z]{2,}")),
    ("house", re.compile(r"(?<![第\d])\d+\s*(号楼|号院|栋|幢|单元|室)|(?<![第\d])\d{1,5}\s*号(?![令文决])")),
    ("person_masked", re.compile(rf"{MASKED}")),
    ("date_day", re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*日"
                            r"|[〇○零一二三四五六七八九]{4}年[一二三四五六七八九十]{1,2}月[一二三四五六七八九十]{1,3}日"
                            r"|(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)")),
    ("time", re.compile(r"(?<![\d第])\d{1,2}\s*[时点]\s*(\d{1,2}\s*分|许|左右)|(?<!\d)\d{1,2}:\d{2}(?!\d)")),
    ("birth", re.compile(r"\d{4}\s*年[^，,。；\n]{0,8}(出生|生)(?![活产效意])")),
]
SOFT = [
    ("station_named", re.compile(r"(?P<pre>[^\s，,。；;、：:（）()“”\"\d局]{1,6})派出所")),
    ("officer_named", re.compile(r"(民警|辅警|执法人员)(?!某)[一-龥]{2,3}(?=[、，,在于对到将])")),
]
# 当事人称谓后紧跟真名（脱敏后这里应是代号）：硬命中（2026-10-16 实测法宝表格案卷"行为人张伟"式漏网 12 件）
# （复议文书的"申请人/被申请人"后面多是动词："申请人宣读""被申请人于同日"，不收）
ROLE_REAL = re.compile(rf"(?:违法行为人|行为人|违法嫌疑人|被处罚人|当事人)\s*(?P<name>{REAL})"
                       r"(?=[，,。；;、（(\s于因在等和与及系的被将从对后]|$)")
NAME_CTX = re.compile(rf"(?:(?<=[、，,和与及对])|(?<=伙同)|(?<=给予)|(?<=违法行为人)|(?<=被处罚人)|(?<=违法嫌疑人)|(?<=申请人)|(?<=当事人))"
                      rf"(?P<name>{REAL})(?={SEP}|等|在|于|因|的|被|行政拘留|罚款|，|。|$)")


@dataclass
class Hit:
    cat: str
    hard: bool
    field: str
    start: int
    end: int
    snippet: str


def load_whitelist(path: Path = WHITELIST) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")}


def _excluded(cat: str, text: str, m: re.Match) -> bool:
    s = m.group(0)
    if cat == "person_masked":
        # "区某麻将馆""县某村"：行政区划用字后面的"某"是脱敏留下的地名占位
        if "某" in s and m.start() > 0 and text[m.start() - 1] in ADMIN:
            return True
        if s[0] in ADMIN and "某" in s:
            return True
        # "于某派出所""申某麻将馆"：后面紧跟脱敏占位的场所、地名
        if s.endswith("某") and re.match(r"(派出所|[乡镇村屯组路街巷号室厂店幢栋]|大街|大道|街道|社区|小区|行政村|麻将|棋牌|茶|宾馆|酒店|旅馆|商|超市|饭店|网吧)",
                                       text[m.end():]):
            return True
        # "丁在**"：脱敏占位符（甲/乙丙丁…）后接介词再接遮蔽——"占位符+源遮蔽场所"的组合
        # （仙桃批实测 P-737；占位符本身无隐私，其后"**"是源遮蔽而非人名残留）
        if len(s) >= 2 and s[0] in ALIASES + ["甲", "某"] and \
                text[m.start() + 1] in "在于是与和及因被将对向为以从到至前内外的了等":
            return True
    if cat == "station_named":
        pre = m.group("pre")
        if pre.endswith("某") or pre[-1] in STATION_STOP + "了的" or pre.endswith(("辖区", "当地", "属地", "所在地", "我", "公安局", "分局")):
            return True
    if cat == "officer_named" and not looks_like_name(s[2:]):
        return True
    if cat == "house" and re.search(r"(第|令|公告|文件)\s*$", text[max(0, m.start() - 3): m.start()]):
        return True
    if cat == "long_number" and "h:" in text[max(0, m.start() - 3): m.start()]:
        return True
    return False


def scan_text(text: str, field: str = "text", whitelist: set[str] | None = None) -> list[Hit]:
    # 表格续行会把人名、日期切成两行，规则都匹配不上：先去掉续行再扫（位置相对去掉续行后的文本）
    text = apply(text or "", cell_wraps(text or ""))
    hits: list[Hit] = []
    for hard, rules in ((True, HARD), (False, SOFT)):
        for cat, rx in rules:
            for m in rx.finditer(text):
                if not _excluded(cat, text, m):
                    hits.append(Hit(cat, hard, field, m.start(), m.end(), text[max(0, m.start() - 12): m.end() + 12]))
    wl = whitelist or set()
    for m in ROLE_REAL.finditer(text):
        tok = m.group("name")
        if tok in wl or tok in STOP_WORDS or tok[:2] in STOP_WORDS or tok[0] in FUNC or not looks_like_name(tok):
            continue
        hits.append(Hit("person_role", True, field, m.start("name"), m.end("name"),
                        text[max(0, m.start() - 12): m.end() + 12]))
    for m in NAME_CTX.finditer(text):
        tok = m.group("name")
        if tok in wl or tok in STOP_WORDS or tok[:2] in STOP_WORDS or tok[0] in ALIASES + ["甲"] or not looks_like_name(tok):
            continue
        hits.append(Hit("name_candidate", False, field, m.start("name"), m.end("name"),
                        text[max(0, m.start() - 12): m.end() + 12]))
    return hits


def scan_record(rec: dict, whitelist: set[str] | None = None) -> list[Hit]:
    hits = []
    for f in TEXT_FIELDS:
        hits += scan_text(rec.get(f) or "", f, whitelist)
    return hits


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    wl = load_whitelist()
    paths = [Path(a) for a in argv]
    total, hard_recs, cats, soft_names, per_file = 0, [], Counter(), Counter(), {}
    for path in paths:
        n = n_hard = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            n += 1
            hits = scan_record(rec, wl)
            cats.update(f"{'硬' if h.hard else '软'}:{h.cat}" for h in hits)
            soft_names.update(h.snippet[12:-12] or h.snippet for h in hits if h.cat == "name_candidate")
            hard = [asdict(h) for h in hits if h.hard]
            if hard:
                n_hard += 1
                hard_recs.append({"file": path.name, "id": rec.get("id"), "hits": hard})
        per_file[path.name] = {"records": n, "hard_hit_records": n_hard}
        total += n
        print(f"R6 {path.name}: {n} 件，硬命中 {n_hard} 件")
    # I-07：一份报告覆盖本次扫描的全部文件，逐文件给出件数（旧版只写了最后一个文件名，件数却是合计）
    report = {"files": per_file, "records": total, "hard_hit_records": len(hard_recs), "categories": dict(cats),
              "name_candidates_top": soft_names.most_common(100), "hard_hits": hard_recs[:500],
              "date": date.today().isoformat()}
    out = paths[0].with_name("r6_report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"R6 合计 {total} 件，硬命中 {len(hard_recs)} 件；类别 {dict(cats)} → {out}")
    return 1 if hard_recs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
