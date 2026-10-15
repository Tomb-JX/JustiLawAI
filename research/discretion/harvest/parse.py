"""收割正文 → 行政案例结构化记录（对齐 docs/05-research/data-spec.md v0.1 §1，脱敏前）。

四种页面形态：
  叙述式处罚决定书   现查明 → text_facts；以上事实有…证实 → text_evidence；本局认为… → text_reasoning；根据…现决定 → text_decision
  字段式公示         违法事实/处罚事由 → facts；处罚依据 + 处罚结果/内容 → decision；决定日期、实施机关
  汇总页             按"1、2、3、"拆成单案（红塔等），每条一案
  复议决定书         原处罚句 → outcome；经审理查明 → facts；本机关认为…决定如下 → text_review、review.result
每案用全文重判是否赌博（triage 同规则）；in_scope 只收公安机关依《治安管理处罚法》作出的处理（文化执法等排除）。
产物不含脱敏（deidentified=false），**不能直接交给引擎**，下一步是脱敏 + R6 扫描（设计 §4）。

用法（仓库根目录）：python research/discretion/harvest/parse.py
输入：$JUSTILAW_DATA_DIR/harvest/pages.jsonl + text/
产出：$JUSTILAW_DATA_DIR/admin/web_cases.pre_deid.jsonl（全量重建）与 web_cases.stats.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discover"))

from search import data_root  # noqa: E402
from triage import DOC_NO, classify, gambling_status  # noqa: E402

CN = {"〇": 0, "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
      "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
NUM = r"[\d,，.]+|[〇零一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万]+"
ART = r"第[一二三四五六七八九十百零\d]+条(?:第[一二三四五六七八九十\d]+款)?(?:第?[（(]?[一二三四五六七八九十\d]+[)）]?项)?"
LABELS = {
    "facts": r"违法事实|行政处罚事由|处罚事由|处罚事项|案件情况|简要案情|主要违法事实",
    "basis": r"做出处罚的法律依据条款|违反的法律条款|行政处罚依据|处罚依据|法律依据",
    "result": r"行政处罚内容|处罚结果|处罚内容|处罚决定",
    "date": r"决定\s*[（(]\s*通知\s*[)）]\s*日期|处罚决定日期|行政处罚时间|决定日期|作出决定日期|公示日期",
    "authority": r"执法主体名称|实施机关|行政处罚机关|处罚机关|作出处罚的机关|执法机关",
    "case_name": r"案件名称",        # 翁牛特旗等字段表：违法事实常为空，只有"××等人赌博案"
    "fine_amount": r"罚款金额",
    "category": r"处罚类别|处罚种类",
}


# ---------- 数字与日期 ----------

def cn2int(s: str) -> int | None:
    """中文/大写/阿拉伯数字 → 整数：十日、十三、一千五百、伍佰、壹仟陆佰、3,000、两千。无法解析返回 None。"""
    s = (s or "").replace(",", "").replace("，", "").replace("整", "")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    if not s or any(ch not in CN and ch not in UNIT and ch != "万" for ch in s):
        return None
    total, section, digit = 0, 0, 0
    for ch in s:
        if ch in CN:
            digit = CN[ch]
        elif ch in UNIT:
            section += (digit or 1) * UNIT[ch]
            digit = 0
        elif ch == "万":
            total += (section + digit) * 10000
            section, digit = 0, 0
    return total + section + digit


def parse_date(s: str) -> str:
    """'2024年04月29日' / '二〇二四年七月二日' / '2024-03-06' / '2024/3/6' → '2024-04-29'；只到月时 '2024-04'。"""
    s = s or ""
    m = re.search(r"(\d{4})\s*[年/.-]\s*(\d{1,2})(?:\s*[月/.-]\s*(\d{1,2}))?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        return f"{y}-{mo:02d}" + (f"-{int(d):02d}" if d else "")
    m = re.search(r"([〇零一二三四五六七八九]{4})年([一二三四五六七八九十]{1,2})月(?:([一二三四五六七八九十]{1,3})日)?", s)
    if m:
        y = "".join(str(CN[c]) for c in m.group(1))
        mo, d = cn2int(m.group(2)), cn2int(m.group(3)) if m.group(3) else None
        return f"{y}-{mo:02d}" + (f"-{d:02d}" if d else "")
    return ""


# ---------- 处罚结果 ----------

def outcome_from(decision: str, context: str = "") -> dict:
    d = decision or ""
    det = [cn2int(x) for x in re.findall(rf"(?:行政)?拘留({NUM})日", d)]
    det += [cn2int(x) for x in re.findall(rf"给予({NUM})日(?:行政)?拘留", d)]
    merged = [cn2int(x) for x in re.findall(rf"合并执行(?:行政)?拘留({NUM})日", d)]
    det = [x for x in det if x]
    fines = [cn2int(x) for x in re.findall(rf"罚款(?:人民币)?({NUM})元", d)] + \
            [cn2int(x) for x in re.findall(rf"({NUM})元(?:的)?罚款", d)]
    fines = [x for x in fines if x]
    if re.search(r"不予(?:行政)?处罚", d):
        typ = "不予处罚"
    elif re.search(r"移送.{0,6}(起诉|审查起诉|刑事|立案侦查)", d):
        typ = "移送刑事"
    elif det and fines:
        typ = "拘留并处罚款"
    elif det:
        typ = "拘留"
    elif fines:
        typ = "罚款"
    elif "警告" in d:
        typ = "警告"
    else:
        typ = ""
    articles, law = [], ""
    for m in re.finditer(rf"《([^》]+)》|({ART})", d):
        if m.group(1):
            law = re.sub(r"^中华人民共和国", "", m.group(1))
        elif law:
            articles.append(law + m.group(2))
    circ = re.findall(r"情节严重|情节较轻|从轻|减轻|从重|免予处罚|不予处罚", (context or "") + d)
    return {
        "type": typ,
        "detention_days": (merged[0] if merged else det[0]) if det or merged else 0,
        "detention_items": det,
        "fine": fines[0] if fines else 0,
        "detention_not_executed": "是" if re.search(r"不执行(?:行政)?拘留|不送(?:达)?拘留所|依法不执行", d) else "否",
        "confiscation": "；".join(dict.fromkeys(m.strip("，,") for m in re.findall(r"收缴[^。；]{0,40}", d))),
        "articles": list(dict.fromkeys(articles)),
        "stated_circumstances": list(dict.fromkeys(circ)),
        "law_version": "旧法" if ("修订前" in d or "第七十条" in d) else ("新法" if "第八十二条" in d else ""),
    }


# ---------- 切分 ----------

def field_values(text: str) -> dict[str, str]:
    """字段式公示：标签 → 值（到下一个标签为止）。"""
    pattern = "|".join(f"(?P<{k}>{v})" for k, v in LABELS.items())
    # 标签后必须跟冒号或空白（表格单元以空格分隔）；否则"行政处罚决定书"里的"处罚决定"也会被当成标签
    marks = [(m.start(), m.end(), m.lastgroup) for m in re.finditer(rf"(?:{pattern})(?:\s*[:：]|\s+)", text)]
    out: dict[str, str] = {}
    for i, (s, e, k) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        val = text[e:end].strip(" :：\n")
        if val and k not in out:
            out[k] = val[:1500]
    return out


def segment_decision(text: str) -> dict:
    """叙述式处罚决定书。"""
    t = text
    fs = re.search(r"(现查明|经查明|经查实|经查)[:：，,]?", t)
    ev = re.search(r"(以上|上述)(违法)?事实[^。]{0,8}有[^。]*?(证实|为证|证明|佐证|证据)[^。]*。", t)
    rs = re.search(r"(本局认为|本机关认为|我局认为|综上所述|综上)", t)
    ds = re.search(r"根据《[^》]+》[^。]{0,200}?(之规定|的规定)[，,]?\s*(现)?决定|现决定|决定(给予|对)", t)
    de = re.search(r"执行方式|被处罚人如不服|如不服本决定|逾期不(交|缴)纳|本决定书送达|申请行政复议", t[ds.end():]) if ds else None
    if not (fs and ds):
        return {"segmented": False}
    cut = [x.start() for x in (ev, rs, ds) if x and x.start() > fs.end()]
    if not cut:  # "现查明"出现在决定之后（如引用前案）：切不准就整篇保留，标未切分
        return {"segmented": False}
    facts = t[fs.end(): min(cut)].strip()
    reasoning = t[rs.start(): ds.start()].strip() if rs and fs.end() < rs.start() < ds.start() else ""
    decision = t[ds.start(): ds.end() + (de.start() if de else 400)].strip()
    return {"segmented": True, "text_facts": facts, "text_evidence": ev.group(0) if ev else "",
            "text_reasoning": reasoning, "text_decision": decision}


def segment_review(text: str) -> dict:
    t = text
    fs = re.search(r"(经审理查明|本机关查明|经审查查明|本府查明|经查明)[:：，,]?", t)
    rs = re.search(r"(本机关认为|本府认为|本机关经审查认为|复议机关认为)", t)
    dm = re.search(r"(决定如下|作出如下(行政复议)?决定|现决定)[:：]?", t)
    orig = next((s for s in re.split(r"[。；]", t) if "行罚决字" in s and re.search(r"拘留|罚款|警告|不予", s)), "")
    if not rs:
        return {"segmented": False, "orig": orig}
    res_text = t[dm.start(): dm.start() + 300] if dm else t[rs.start():]
    result = next((r for r, p in (("撤销", r"撤销"), ("确认违法", r"确认.{0,10}违法"), ("变更", r"变更"),
                                  ("维持", r"维持"), ("驳回", r"驳回")) if re.search(p, res_text)), "")
    return {"segmented": bool(fs), "text_facts": t[fs.end(): rs.start()].strip() if fs and fs.end() < rs.start() else "",
            "text_review": t[rs.start(): (dm.end() + 300) if dm else len(t)].strip(), "orig": orig, "review_result": result}


def split_items(text: str) -> list[str]:
    parts = re.split(r"(?:^|\n|[。；])\s*\d{1,3}[、.．]\s*(?=违法行为人|[一-龥*×xX]{1,8}[，,])", text)
    items = [p.strip() for p in parts if re.search(r"处罚|拘留|罚款", p)]
    return items if len(items) >= 2 else []


def table_rows(title: str, text: str) -> list[str]:
    """执法结果表（禹会区、海南定安等）：一行一案。只取同时含赌博与处罚结果的行。"""
    if not re.search(r"处罚结果|汇总表|执法结果|处罚信息公开表|处罚信息公示", title + text[:300]):
        return []
    rows = [ln for ln in text.splitlines() if re.search(r"赌", ln) and re.search(r"拘留|罚款|警告|不予", ln) and len(ln) < 600]
    return rows if len(rows) >= 1 else []


def authority_of(text: str) -> str:
    m = re.search(r"([一-龥]{2,20}?(?:公安局|公安分局|派出所|人民政府|司法局))", text)
    return m.group(1) if m else ""


def has_amount(facts: str) -> bool:
    return bool(re.search(rf"(赌资|赌注|输赢|抽头|抽水|筹码|充值|台费|彩金|获利|好处费|底注|封顶)[^。]{{0,25}}?({NUM})", facts or "")
                or re.search(rf"({NUM})元", facts or ""))


# ---------- 组装 ----------

def build_case(base: dict, *, facts: str, evidence: str = "", reasoning: str = "", decision: str = "", review: str = "",
               full: str, segmented: bool, review_result: str = "", decision_date: str = "", authority: str = "",
               doc_type: str, outcome_text: str = "") -> dict:
    oc = outcome_from(outcome_text or decision, reasoning)
    no = DOC_NO.findall(full)
    dates = re.findall(r"\d{4}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?", facts or "")
    title = base.get("title", "")
    judged = (facts or "") + (decision or "") + (review or "") or full
    gamb = gambling_status(title, judged, doc_type)
    if gamb == "待定" and len(judged) >= 150:
        gamb = "否"  # "待定"是给截断摘录用的；这里已有全文，全文里没有赌博特征就是"否"
    police = bool(re.search(r"公安", authority + decision + full[:400])) and "治安管理处罚法" in (decision + full)
    # 权责清单、事项清单、裁量基准等规范性页面不是案件（收割阶段蚌埠"权责清单"误入）
    is_norm = classify(title, full[:800]) == "法规清单" or bool(re.search(r"权责清单|事项清单|实施依据.{0,20}责任事项", full[:1500]))
    warns = []
    if re.search(r"决定给予|情节严重|从轻处罚|从重处罚", facts or ""):
        warns.append("facts_contains_conclusion")
    if not oc["type"]:
        warns.append("outcome_not_parsed")
    return {
        **base,
        "doc_no": no[0][0] if no else "",
        "authority": authority or authority_of(full),
        "behavior_date": parse_date(dates[0]) if dates else "",
        "decision_date": decision_date,
        "text_full": full, "text_facts": facts, "text_evidence": evidence, "text_reasoning": reasoning,
        "text_decision": decision, "text_review": review, "segmented": segmented,
        "outcome": oc,
        "review": {"result": review_result or ("无" if doc_type != "复议" else ""), "changed_outcome": ""},
        "gambling": gamb, "in_scope": gamb == "是" and police and not is_norm,
        "completeness": {"has_amount": has_amount(facts), "has_outcome": bool(oc["type"])},
        "deidentified": False, "parse_warnings": warns,
    }


def last_date(text: str) -> str:
    tail = text[-200:]
    ds = re.findall(r"[〇零一二三四五六七八九]{4}年[一二三四五六七八九十]{1,2}月[一二三四五六七八九十]{1,3}日|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", tail)
    return parse_date(ds[-1]) if ds else ""


def parse_page(page: dict, text: str) -> list[dict]:
    base = {"page_id": page["page_id"], "id": page.get("manifest_id", ""), "source_ref": page["url"],
            "harvest_date": page["fetched_at"][:10], "site": page["site"], "title": page.get("title", ""),
            "publisher": page.get("publisher", "")}
    body_len = len(re.sub(r"\s", "", re.sub(r"附件[:：].*", "", text)))
    if body_len < 200 and page.get("attachment_files"):
        # 正文只有扫描件或 PDF（定兴 2025 年起即如此）：先建占位案例，OCR 后再解析
        return [{**base, "source_type": "处罚决定书", "segmented": False, "needs_ocr": True,
                 "attachment_files": page["attachment_files"], "text_full": text, "gambling": "待定", "in_scope": False,
                 "outcome": {"type": ""}, "completeness": {"has_amount": False, "has_outcome": False},
                 "deidentified": False, "parse_warnings": ["attachment_only"]}]
    # 复议：标题或全文出现复议文书特征且有被申请人（慈溪等页面的复议字样不在开头 300 字内）
    is_review = bool(re.search(r"复议决定书|复决|政复|府复|行复|行政复议决定", page.get("title", "") + text))         and "被申请人" in text and "申请人" in text[:2000]
    if is_review:
        sg = segment_review(text)
        return [build_case({**base, "source_type": "行政复议决定书"}, facts=sg.get("text_facts", ""),
                           review=sg.get("text_review", ""), decision=sg.get("orig", ""), full=text,
                           segmented=sg.get("segmented", False), review_result=sg.get("review_result", ""),
                           decision_date=last_date(text), authority=authority_of(re.split(r"被申请人", text, maxsplit=1)[-1][:60]),
                           doc_type="复议")]
    items = split_items(text)
    if items:
        out = []
        for k, it in enumerate(items, 1):
            cause = re.search(r"因[^，,。]{1,40}?(违法行为|行为)", it)
            dec = it[it.find("根据"):] if "根据" in it else it
            out.append(build_case({**base, "id": f"{base['id']}-{k}", "source_type": "执法公示", "item_index": k},
                                  facts=it[: it.find("被") if "被" in it else len(it)], decision=dec, full=it,
                                  segmented=bool(cause and "根据" in it), authority=authority_of(it), doc_type="处罚决定"))
        return out
    rows = table_rows(page.get("title", ""), text)
    if rows:
        return [build_case({**base, "id": f"{base['id']}-r{k}", "source_type": "执法公示", "item_index": k},
                           facts=r, decision=r, full=r, segmented=False, authority=authority_of(text),
                           doc_type="处罚决定") for k, r in enumerate(rows, 1)]
    fv = field_values(text)
    if ("facts" in fv or "case_name" in fv) and ("result" in fv or "basis" in fv or "fine_amount" in fv):
        amount = fv.get("fine_amount", "").splitlines()[0].strip() if fv.get("fine_amount") else ""
        fine = f"罚款{amount}元" if re.fullmatch(r"\d+(\.\d+)?", amount) else ""
        category = fv.get("category", "").splitlines()[0] if fv.get("category") else ""
        decision = "；".join(x for x in (fv.get("basis", ""), fv.get("result", ""), category, fine) if x)
        fv.setdefault("facts", fv.get("case_name", ""))
        return [build_case({**base, "source_type": "执法公示"}, facts=fv["facts"], decision=decision, full=text,
                           segmented=True, decision_date=parse_date(fv.get("date", "")),
                           authority=fv.get("authority", "")[:30], doc_type="处罚决定")]
    sg = segment_decision(text)
    return [build_case({**base, "source_type": "处罚决定书"}, facts=sg.get("text_facts", ""),
                       evidence=sg.get("text_evidence", ""), reasoning=sg.get("text_reasoning", ""),
                       decision=sg.get("text_decision", ""), full=text, segmented=sg.get("segmented", False),
                       decision_date=last_date(text), doc_type="处罚决定")]


def main() -> None:
    root = data_root().parent
    hdir = root / "harvest"
    pages = {}
    for line in (hdir / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        pages[rec["url"]] = rec  # 同一 URL 以最后一次为准
    cases = []
    for p in pages.values():
        if p["status"] != "ok":
            continue
        cases += parse_page(p, (hdir / p["text_path"]).read_text(encoding="utf-8"))
    out_dir = root / "admin"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "web_cases.pre_deid.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
    scope = [c for c in cases if c["in_scope"]]
    stats = {
        "pages": sum(p["status"] == "ok" for p in pages.values()), "cases": len(cases), "in_scope": len(scope),
        "gambling": dict(Counter(c["gambling"] for c in cases)),
        "source_type_in_scope": dict(Counter(c["source_type"] for c in scope)),
        "segmented_in_scope": sum(c["segmented"] for c in scope),
        "outcome_type_in_scope": dict(Counter(c["outcome"]["type"] or "未解析" for c in scope)),
        "complete_in_scope": sum(c["completeness"]["has_amount"] and c["completeness"]["has_outcome"] for c in scope),
        "law_version_in_scope": dict(Counter(c["outcome"]["law_version"] or "未知" for c in scope)),
        "warnings_in_scope": dict(Counter(w for c in scope for w in c["parse_warnings"])),
        "needs_ocr": sum(bool(c.get("needs_ocr")) for c in cases),
    }
    (out_dir / "web_cases.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
