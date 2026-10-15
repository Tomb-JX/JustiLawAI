"""发现层 L3 分诊：把各批次搜索命中合并、分类、去重，产出交付文件与域名库（设计 §3.4–3.5、§6）。

分类以 API 返回的约 1,000 字摘录为主、标题为辅（M0：有标题只写"政府信息公开"、正文却是完整处罚决定的页面）。
赌博判定先剔除法条引用片段（如第十一条"赌具、赌资……应当收缴"、第七十条/第八十二条条文原文），避免
数据链路初筛那种"引用法条即命中"的误报。

用法（仓库根目录）：python research/discretion/discover/triage.py
输入：$JUSTILAW_DATA_DIR/discover/runs/*/hits.jsonl
产出：$JUSTILAW_DATA_DIR/discover/out/<日期>/{candidates.jsonl, urls.tsv, norms_candidates.tsv, SHA256SUMS}
      本目录 domains.csv（入库：主机名、发布单位与计数，不含正文）
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from search import data_root

HERE = Path(__file__).resolve().parent
DOMAINS_CSV = HERE / "domains.csv"

TARGET_TYPES = ("处罚决定", "处罚汇总", "不予处罚", "复议", "执法结果表")
TYPE_PRIORITY = {"处罚决定": 3, "处罚汇总": 3, "不予处罚": 3, "复议": 2, "执法结果表": 1}

# 法条引用：书名号法名 + 条号 + 引号内条文；以及常被整段引用的赌博条款与收缴条款
CITATION_PATTERNS = [
    re.compile(r"第[一二三四五六七八九十百零\d]+条[^“”\"]{0,20}?[“\"][^”\"]{0,400}[”\"]"),
    re.compile(r"以营利为目的[，,]?为赌博提供条件的[，,]?或者参与赌博赌资较大的[^。]*。?"),
    re.compile(r"[^。]{0,40}赌具、赌资[^。]{0,60}收缴[^。]*。?"),
]
GAMBLING = re.compile(r"赌博|赌资|参赌|聚赌|开设赌场|抽头|炸金花|推饼|六合彩|牛牛|押宝|赌具|涉赌|麻将|斗地主.{0,10}输赢")
PERSON = re.compile(r"违法行为人|被处罚人|行政相对人|现查明|违法事实|处罚事由")
CASE_FORMAT = re.compile(r"案件名称|简要案情|处罚事由|违法事实|处罚内容|处罚结果")
POLICE = re.compile(r"公安局|公安分局|派出所")
DOC_NO = re.compile(
    r"([一-龥（）()]{1,16}(?:行罚决字|政复决字|复决字|政复决|府复决|行复|政复|府复|复字|罚决字|决字)"
    r"\s*[〔\[［【(（]\s*(20\d{2})\s*[〕\]］】)）]\s*第?\s*[\d*]{1,6}\s*号)"
)
LAW_TITLE = re.compile(r"法(?:\(|（|$)|条例|规定|办法|意见|通知|通告|公告|清单|目录|制度|裁量基准|基准|标准|指引|细则"
                       r"|解读|解释|答复|报告|部令|事项")


def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", "", text)


def strip_citations(text: str) -> str:
    for p in CITATION_PATTERNS:
        text = p.sub("", text)
    return text


def classify(title: str, content: str) -> str:
    """类型判定的先后顺序就是优先级：
    诉讼/刑事文书 → 复议 → 法规清单 → 不予处罚 → 结果表 → 汇总 → 新闻 → 单篇处罚 → 其他。"""
    t, c = clean(title), clean(content)
    both = t + c
    # 具体案件的硬特征（"违法行为人"不算：法规条文里也常出现，如公安部令"违法行为人居住地"）
    case_marks = "行罚决字" in both or bool(re.search(r"现查明|案件名称|简要案情|处罚事由|被处罚人|行政相对人名称", c))
    if re.search(r"起诉书|判决书|裁定书|不起诉决定", t):
        return "诉讼刑事文书"
    if re.search(r"复议决定|复决|政复|府复|行复", t) or (re.search(r"复议决定书|复决字|政复|府复", c[:200]) and "被申请人" in c):
        return "复议"
    if LAW_TITLE.search(t) and not case_marks:
        return "法规清单"  # 裁量基准、实施办法、法律解读、部令等：标题像规范文件且正文没有具体案件
    if re.search(r"不予(?:行政)?处罚决定", t) or (re.search(r"不予(?:行政)?处罚决定书", c) and case_marks):
        return "不予处罚"
    if re.search(r"行政处罚结果|执法结果信息|处罚结果公示|处罚信息公示|汇总表|月份.{0,6}处罚", t):
        return "执法结果表"
    # 文号按（年份, 序号数值）归一：同一文书标题写 00305、正文写 0305 的情况很常见
    decisions = {(y, int(n)) for y, n in re.findall(r"行罚决字\s*[〔\[［【(（]\s*(20\d{2})\s*[〕\]］】)）]\s*(\d+)", both)}
    enumerated = bool(re.search(r"[2２]、\s*违法行为人", c))
    if enumerated or len(decisions) >= 3 or (len(decisions) == 2 and re.search(r"汇总|月份|季度|信息公开|案例", t)):
        return "处罚汇总"  # 单篇决定常引用前案文号，两个文号不足以判为汇总
    if not case_marks and re.search(r"严打|专项|警方|通报|捣毁|打掉|以案释法|普法|典型案例|行动|守护|平安|查处|拘留|抓获|破获|逢赌必抓", t):
        return "新闻案例"
    if case_marks or PERSON.search(c) or "处罚决定书" in t or re.search(r"赌博案|处罚案例", t):
        return "处罚决定"
    return "其他"


def gambling_status(title: str, content: str, doc_type: str) -> str:
    """是 / 否 / 待定。摘录只有约 1,000 字，公安处罚与复议的赌博事实可能在截断之后——这类标"待定"交给全文判定。"""
    text = strip_citations(clean(title) + clean(content))
    if GAMBLING.search(text):
        return "是"
    if doc_type in ("复议", "处罚决定", "不予处罚") and POLICE.search(text):
        return "待定"
    return "否"


def doc_no(title: str, content: str, doc_type: str) -> tuple[str, str]:
    """返回 (文号, 年份)。复议优先取复议文号，其余优先取处罚文号；标题优先于正文。"""
    found = DOC_NO.findall(clean(title)) + DOC_NO.findall(clean(content))
    if not found:
        return "", ""
    want = ("复", "行复") if doc_type == "复议" else ("行罚决字", "罚决字")
    for no, year in found:
        if any(w in no for w in want):
            return no, year
    return found[0]


def law_article(content: str) -> str:
    c = clean(content)
    arts = [a for a, pat in (("70", "第七十条"), ("82", "第八十二条")) if pat in c]
    return "/".join(arts)


def triage_hit(h: dict) -> dict:
    title, content = h.get("title", ""), h.get("content", "")
    dt = classify(title, content)
    gamb = gambling_status(title, content, dt)
    no, year = doc_no(title, content, dt)
    year = year or (h.get("date") or "")[:4]
    law = law_article(content)
    pri = {"是": TYPE_PRIORITY.get(dt, 0), "待定": 1 if dt in TYPE_PRIORITY else 0}.get(gamb, 0)
    if gamb == "是" and pri and (year >= "2026" or "82" in law):
        pri += 1
    host = (urlparse(h["url"]).hostname or "").lower()
    publisher = h.get("website") if h.get("website") not in ("", "无", None) else ""
    return {
        "url": h["url"], "host": host, "publisher": publisher, "title": clean(title)[:80],
        "doc_type": dt, "gambling": gamb, "doc_no": no, "year": year, "law_article": law,
        "priority": pri, "query_id": h.get("query_id", ""), "found_at": h.get("found_at", ""),
    }


def merge_hits(runs_dir: Path) -> list[dict]:
    seen: dict[str, dict] = {}
    for p in sorted(runs_dir.glob("*/hits.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            h = json.loads(line)
            seen.setdefault(h["url"], h)
    return list(seen.values())


def dedupe_by_doc_no(cands: list[dict]) -> list[dict]:
    """同一文号出现在多个页面（www./zwfw. 镜像、转载）时只留一条，其余记入 alt_urls。汇总页不按文号去重。"""
    keep, by_no = [], {}
    for c in sorted(cands, key=lambda x: (not x["host"].startswith("www."), x["url"])):
        no = c["doc_no"]
        if no and c["doc_type"] not in ("处罚汇总", "执法结果表"):
            if no in by_no:
                by_no[no].setdefault("alt_urls", []).append(c["url"])
                continue
            by_no[no] = c
        keep.append(c)
    return keep


URL_FIELDS = ["url", "title", "doc_type", "doc_no", "publisher", "host", "year", "law_article", "gambling",
              "priority", "query_id", "found_at"]


def write_outputs(cands: list[dict], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    deliver = sorted((c for c in cands if c["gambling"] in ("是", "待定") and c["doc_type"] in TARGET_TYPES),
                     key=lambda c: (-c["priority"], c["host"], c["doc_no"]))
    norms = [c for c in cands if c["doc_type"] == "法规清单" and re.search(r"裁量|赌", c["title"])]
    with open(out_dir / "candidates.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in cands)
    for name, rows in (("urls.tsv", deliver), ("norms_candidates.tsv", norms)):
        with open(out_dir / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=URL_FIELDS, delimiter="\t", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    sums = [f"{hashlib.sha256((out_dir / n).read_bytes()).hexdigest()}  {n}"
            for n in ("candidates.jsonl", "urls.tsv", "norms_candidates.tsv")]
    (out_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return {"deliver": len(deliver), "norms": len(norms)}


def write_domains(cands: list[dict], path: Path) -> int:
    agg: dict[str, dict] = defaultdict(lambda: {"n_hits": 0, "n_target": 0, "types": Counter(), "publisher": "",
                                                "first_seen": "9999"})
    for c in cands:
        d = agg[c["host"]]
        d["n_hits"] += 1
        d["n_target"] += int(c["gambling"] == "是" and c["doc_type"] in TARGET_TYPES)
        d["types"][c["doc_type"]] += 1
        d["publisher"] = d["publisher"] or c["publisher"]
        d["first_seen"] = min(d["first_seen"], c["found_at"] or "9999")
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["n_target"], kv[0]))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["host", "publisher", "n_target", "n_hits", "types", "first_seen"])
        for host, d in rows:
            types = ";".join(f"{k}:{v}" for k, v in d["types"].most_common())
            w.writerow([host, d["publisher"], d["n_target"], d["n_hits"], types, d["first_seen"]])
    return len(rows)


def main() -> None:
    root = data_root()
    hits = merge_hits(root / "runs")
    cands = dedupe_by_doc_no([triage_hit(h) for h in hits])
    out_dir = root / "out" / datetime.now().strftime("%Y%m%d")
    stats = write_outputs(cands, out_dir)
    n_domains = write_domains(cands, DOMAINS_CSV)
    table = Counter((c["doc_type"], c["gambling"]) for c in cands)
    print(f"合并命中 {len(hits)} 条 → 去重后 {len(cands)} 条；域名 {n_domains} 个")
    for (dt, g), n in sorted(table.items(), key=lambda kv: (-kv[1])):
        print(f"  {dt:<6} 赌博={g}  {n}")
    print(f"交付 urls.tsv {stats['deliver']} 条，规范候选 {stats['norms']} 条 → {out_dir}")


if __name__ == "__main__":
    main()
