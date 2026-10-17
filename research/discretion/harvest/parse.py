"""收割正文 → 行政案例结构化记录（对齐 docs/05-research/data-spec.md v0.1 §1，脱敏前）。

四种页面形态：
  叙述式处罚决定书   现查明 → text_facts；以上事实有…证实 → text_evidence；本局认为… → text_reasoning；根据…现决定 → text_decision
  字段式公示         违法事实/处罚事由 → facts；处罚依据 + 处罚结果/内容 → decision；决定日期、实施机关
  汇总页             按"1、2、3、"拆成单案（红塔等），每条一案
  复议决定书         原处罚句 → outcome；经审理查明 → facts；本机关认为…决定如下 → text_review、review.result
  按列公开表         含山：文号 / 案件名 / 姓名 / 事实 / 依据与结果 一列一行
解析前先取正本（去网页导航与页脚，canonical）；一页多份决定书按独占一行的文号拆开（id 加 -dk）。
每案用全文重判是否赌博（triage 同规则）；in_scope 只收公安机关依《治安管理处罚法》作出的处理（文化执法等排除）。
产物不含脱敏（deidentified=false），**不能直接交给引擎**；脱敏、R6、去重与交付由 build.py 完成（文本处理规范 §8）。

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

# 含繁体大写"貳""參""陸"（定兴"罚款貳仟元整"，2026-10-16 r2 抽检漏抽）
CN = {"〇": 0, "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "貳": 2, "两": 2, "兩": 2, "三": 3, "叁": 3, "參": 3, "叄": 3,
      "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
NUM = r"[\d,，.]+|[〇零一壹二贰貳两兩三叁參叄四肆五伍六陆陸七柒八捌九玖十拾百佰千仟万萬]+"
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
    s = (s or "").replace(",", "").replace("，", "").replace("整", "").replace("萬", "万")
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
    m = re.search(r"(\d{4})\s*[年/.．。-]\s*(\d{1,2})(?:\s*[月/.．。-]\s*(\d{1,2}?)(?=日|\D|20\d{2}|$))?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        return _valid_date(f"{y}-{mo:02d}" + (f"-{int(d):02d}" if d else ""))
    m = re.search(r"([〇○零0OＯ一二三四五六七八九]{4})年([一二三四五六七八九十]{1,2})月(?:([一二三四五六七八九十]{1,3})日)?", s)
    if m:
        y = "".join(str(CN.get(c, 0)) for c in m.group(1))
        mo, d = cn2int(m.group(2)), cn2int(m.group(3)) if m.group(3) else None
        return _valid_date(f"{y}-{mo:02d}" + (f"-{d:02d}" if d else ""))
    return ""


def _valid_date(s: str) -> str:
    """不合法的日期（"2023-03-92"：落款"2023.3.92023.3.9"粘连）一律返回空，免得交付校验退回。"""
    from datetime import date as _d
    try:
        y, mo, *d = (int(x) for x in s.split("-"))
        _d(y, mo, d[0] if d else 1)
        return s if 1990 <= y <= 2030 else ""
    except (ValueError, TypeError):
        return ""


# "2026年02底至5月"（红塔，漏"月"字）也认，否则行为日期为空、2026 年案例漏计
DATE_CN = r"\d{4}\s*年\s*\d{1,2}\s*(?:月|(?=[底初]))(?:\s*\d{1,2}\s*日)?"


def behavior_and_punish(facts: str, full: str = "") -> tuple[str, str]:
    """(违法行为日期, 处罚日期)。规格 §1.2：持续行为取结束日（"2025年10月至2026年1月"取 2026-01）；
    紧跟"被……"的日期是处罚日期而不是行为日期（红塔汇总"于2026年2月1日因赌博，被……处罚"）。"""
    f = facts or ""
    base = full.find(f) if full and f else -1
    ctx = full if base >= 0 else f
    off = base if base >= 0 else 0
    punish = ""
    for dm in re.finditer(DATE_CN, f):
        tail = ctx[off + dm.end(): off + dm.end() + 70]
        if re.match(r"\s*[，,]?\s*(?:因[^，,。]{0,60}?[，,]?\s*)?被(?!申请人|告)", tail):
            punish = punish or parse_date(dm.group(0))
            continue
        rng = re.match(r"(?:[初中下上旬末底份]{0,2})\s*(?:至|到|—|－|~|-)\s*(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?", f[dm.end():])
        start = parse_date(dm.group(0))
        if rng and start:
            y = rng.group(1) or start[:4]
            end = _valid_date(f"{y}-{int(rng.group(2)):02d}" + (f"-{int(rng.group(3)):02d}" if rng.group(3) else ""))
            if end and end >= start[:len(end)]:
                return end, punish
        if start:
            return start, punish
    return "", punish


# ---------- 处罚结果 ----------

# "行政拘留不执行"（含山公示把它写在决定句之后的执行一栏，r2 抽检漏标）
NOT_EXECUTED = r"不执行(?:行政)?拘留|(?:行政)?拘留(?:处罚)?不(?:予)?执行|不送(?:达)?拘留所|依法不执行"

def outcome_from(decision: str, context: str = "") -> dict:
    d = decision or ""
    det = [cn2int(x) for x in re.findall(rf"(?:行政)?拘留({NUM})日", d)]
    det += [cn2int(x) for x in re.findall(rf"给予({NUM})日(?:行政)?拘留", d)]
    merged = [cn2int(x) for x in re.findall(rf"合并执行(?:行政)?拘留({NUM})日", d)]
    det = [x for x in det if x]
    fines = [cn2int(x) for x in re.findall(rf"罚(?:款|金)(?:人民币)?({NUM})元", d)] + \
            [cn2int(x) for x in re.findall(rf"({NUM})元(?:的)?罚(?:款|金)", d)] + \
            [cn2int(x) for x in re.findall(rf"并处罚(?!款)({NUM})元", d)] + \
            [cn2int(x) for x in re.findall(rf"并处(?:人民币)?({NUM})元(?!以)", d)]   # 漏"款"字："并处罚壹仟元""并处1000元的处罚"
    fines = [x for x in fines if x]
    # 合并执行时罚款也取合并句里的数（"合并执行行政拘留二十日，并处罚款壹仟元整"；旧版取第一项 500）
    mfine = [cn2int(x) for x in re.findall(rf"合并执行(?:行政)?拘留(?:{NUM})日[，,]?\s*并处(?:罚款)?(?:人民币)?({NUM})元", d)]
    mfine = [x for x in mfine if x]
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
    for m in re.finditer(rf"《+([^《》]+)》|({ART})", d):   # 原文"根据《《中华人民共和国……》"
        if m.group(1):
            law = re.sub(r"^中华人民共和国", "", m.group(1))
        elif law:
            articles.append(law + m.group(2))
    circ = re.findall(r"情节严重|情节较轻|从轻|减轻|从重|免予处罚|不予处罚", (context or "") + d)
    return {
        "type": typ,
        "detention_days": (merged[0] if merged else det[0]) if det or merged else 0,
        "detention_items": det,
        "fine": mfine[0] if mfine else (fines[0] if fines else 0),
        "detention_not_executed": "是" if re.search(NOT_EXECUTED, d) else "否",
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
    # "以上事实由……证实"、"以上事实有询问笔录等。等证据证实。"（r2 抽检：证据句留在事实段 95 件）
    ev = re.search(r"(以上|上述)(违法)?事实[^。]{0,8}[有由][^。]*?(证实|为证|证明|佐证|证据)[^。]*。", t) \
        or re.search(r"(以上|上述)(违法)?事实[^。]{0,8}[有由][^。]*。[^。\n]{0,4}等?证据(证实|为证)[^。\n]*。", t)
    # 环江 2021 年表格排版：证据句被拆成"⏎等证据证实。 以上事实有……"挤在事实后面（76 件），事实段到错位句前为止
    ev2 = re.search(r"\n\s*等?证据(?:证实|为证)。\s*(?:以上|上述)(?:违法)?事实[^\n]*", t)
    if ev2 and (not ev or ev2.start() < ev.start()):
        ev = ev2
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
    return {"segmented": True, "text_facts": facts, "text_evidence": ev.group(0).strip() if ev else "",
            "text_reasoning": reasoning, "text_decision": decision}


REVIEW_OUTCOME = re.compile(r"(?:决定|给予|处以|对)[^。；;]{0,40}?(?:拘留|罚款|警告|不予)")


def reviewed_outcome(t: str) -> str:
    """复议文书里被复议那份处罚的结果句。旧版取第一句含"行罚决字"的处罚句，会拿到"另查明"里同案人的处罚
    （W-000546 取成同案人拘留十日、漏了申请人的罚款）或申请人此前的另一次处罚（W-000547 取成前次罚款 300）。
    1. "决定给予/对申请人（或申请人姓名）……拘留/罚款"的句子，取"本机关认为"之前的最后一句（前次处罚、被撤销的
       原处罚在叙述里排在前面）；2. 没有就在"不服……作出的××号"文号之后、到下一个文号之间找决定句。"""
    def ok(s: str) -> bool:
        # 申请人的陈述、异议、告知（"拟作出"）、"另查明"与执行情况不算；同一文书里的殴打等别的违法行为不算
        if "不服" in s or re.search(r"申请人称|异议|请求|拟[^。；;]{0,30}?(?:拘留|罚款)|另查明|缴(?:交|纳)罚款|执行完毕", s):
            return False
        if re.search(r"殴打|伤害|寻衅|强拿|盗窃|诈骗|卖淫|嫖娼|吸毒", s) and "赌" not in s:
            return False
        if re.search(r"第[一二三四五六七八九十百]+条", s) and not re.search(r"第七十条|第八十二条|第十六条|赌", s):
            return False   # 依第二十六条（寻衅滋事）、第四十三条（殴打）等作出的处罚
        oc = outcome_from(s)
        if oc["type"] == "不予处罚" and (oc["detention_days"] or oc["fine"]):   # 引用法条里的"减轻处罚或者不予处罚"
            return False
        return bool(oc["type"]) and bool(oc["detention_days"] or oc["fine"] or oc["type"] in ("不予处罚", "警告"))

    if not re.search(r"第七十条|第八十二条", t):   # 处罚依据不是赌博条款（寻衅滋事等复议里顺带提到赌博）：不取
        return ""
    sents, pos = [], 0
    for s in re.split(r"([。；;])", t)[::2]:
        sents.append((pos, s))
        pos += len(s) + 1
    m = re.search(r"申请人[:：]\s*([^\s，,。;；:：（(]{2,4})", t[:400])
    who = "申请人|其" + (f"|{re.escape(m.group(1))}" if m and not m.group(1).startswith("申请") else "")
    strong = re.compile(rf"(?:决定|给予|对)(?:对)?(?:{who})[^。；;]{{0,12}}?(?:拘留|罚款|罚金|警告|不予)")
    cut = re.search(r"本机关认为|本府认为|复议机关认为|本机关经审查认为", t)
    cut = cut.start() if cut else len(t)
    hits = [(p, s) for p, s in sents if strong.search(s) and ok(s)]
    if hits:
        before = [s for p, s in hits if p < cut]
        return (before[-1] if before else hits[0][1]).strip()
    head = re.search(r"不服[^。]{0,160}", t)
    no = DOC_NO.search(head.group(0)) if head else None
    if no:
        marks = [k.start() for k in DOC_NO.finditer(t)]
        for k in re.finditer(re.escape(no.group(1)), t):
            if k.start() < head.end():
                continue
            nxt = next((x for x in marks if x > k.end()), len(t))
            seg = re.split(r"另查明|本机关认为|本府认为|复议机关认为", t[k.end(): nxt])[0]
            for s in re.split(r"[。；;]", seg):
                if REVIEW_OUTCOME.search(s) and "决定" in s and ok(s):
                    return s.strip()
    return ""


def segment_review(text: str) -> dict:
    t = text
    fs = re.search(r"(经审理查明|本机关查明|经审查查明|本府查明|经查明)[:：，,]?", t)
    rs = re.search(r"(本机关认为|本府认为|本机关经审查认为|复议机关认为)", t)
    dm = re.search(r"(决定如下|作出如下(行政复议)?决定|现决定)[:：]?", t)
    orig = reviewed_outcome(t) or next((s for s in re.split(r"[。；]", t) if "行罚决字" in s and re.search(r"拘留|罚款|警告|不予", s)), "")
    # 结论（D4，规格 §1.4）：复议"驳回行政复议申请"、诉讼"裁定驳回起诉"记"程序驳回"；诉讼"驳回诉讼请求""驳回上诉"是实体认可，记"维持"。
    # 没有"本机关认为"段时也从"决定如下"之后或全文末尾找结论（I-13：复议结论为空 127 条）
    res_text = t[dm.start(): dm.start() + 300] if dm else (t[rs.start():] if rs else t[-600:])
    result = next((r for r, p in (("撤销", r"撤销"), ("确认违法", r"确认.{0,10}违法"), ("变更", r"变更"),
                                  ("维持", r"维持|驳回[^。；]{0,8}诉讼请求|驳回上诉"),
                                  ("程序驳回", r"驳回[^。；]{0,10}(?:复议)?申请|驳回起诉|不予受理|驳回"))
                   if re.search(p, res_text)), "")
    if not rs:
        return {"segmented": False, "orig": orig, "review_result": result}
    return {"segmented": bool(fs), "text_facts": t[fs.end(): rs.start()].strip() if fs and fs.end() < rs.start() else "",
            "text_review": t[rs.start(): (dm.end() + 300) if dm else len(t)].strip(), "orig": orig, "review_result": result}


# ---------- 正本与拆分 ----------

ROLE = r"违法行为人|被处罚人|违法嫌疑人|行政处罚对象|行政相对人名称|行政相对人|当事人|申请人"
SUBJECT_LINE = re.compile(rf"\s*(?:\d{{1,3}}[、.．]\s*)?(?:{ROLE})\s*[:：]?\s*(?P<n>[一-龥])"
                          rf"|\s*(?P<p>[一-龥])[一-龥xX×＊*某]{{1,4}}\s*[,，]\s*[男女]\s*[,，]")
FIELD_LINE = re.compile(r"\s*(?:案件名称|行政处罚决定书文号|处罚决定书文号|决定书文号|违法事实|主要违法事实|处罚事由|行政处罚事由"
                        r"|行政相对人名称)\s*[:：\s]")
HEAD_LINE = re.compile(r"[一-龥（）()·]{0,30}(?:公安局|公安分局|公安厅|派出所|人民政府|决定书)|[^\s，,。]{2,30}案")
CHROME_END = re.compile(r"(文件下载|我要提建议|扫一扫|【?打印(本页)?】?|【?关闭(窗口|本页)?】?|网站地图|版权所有|主办单位|承办单位"
                        r"|首页\s*[|｜]|上一篇|下一篇|相关链接|相关文章|友情链接|分享到|责任编辑|【?字体|您是第|技术支持|联系我们|.*ICP备)")


def _is_subject_line(ln: str) -> bool:
    from deid import SURNAMES, MASK
    m = SUBJECT_LINE.match(ln)
    if not m:
        return False
    rest = ln[m.end() - 1:]
    return (m.group("n") or m.group("p")) in SURNAMES or bool(re.match(rf"[一-龥]{MASK}", rest))


def _role_inside(ln: str) -> bool:
    from deid import SURNAMES
    return any(m.group(1) in SURNAMES for m in re.finditer(rf"(?:{ROLE})\s*[:：]?\s*([一-龥])", ln))


def canonical(text: str) -> str:
    """正本：去掉网页导航、页头与页脚（规范 §4.1）。正文从第一个当事人行（或字段式公示的第一个字段行）开始，
    往前带上紧邻的机关名、文书名、文号行（至多 3 行）；到正文后第一条页脚标记为止。找不到正文起点就原样保留。"""
    lines = text.split("\n")
    first = next((i for i, ln in enumerate(lines) if _is_subject_line(ln) or FIELD_LINE.match(ln)), None)
    if first is None:
        # 兜底：从"当前位置"面包屑之后开始（汇总表、新闻式案例页）
        crumb = next((i for i, ln in enumerate(lines[: len(lines) // 2])
                      if re.match(r"\s*(当前位置|您当前所在位置|您的位置|您现在的位置|首页\s*[>＞])", ln)), None)
        if crumb is None or re.search(r"现查明|经查明|拘留|罚款", "\n".join(lines[:crumb + 1])):
            return text
        first = crumb + 1
        while first < len(lines) - 1 and len(lines[first].strip()) <= 2:  # 面包屑被拆成多行时跳过">"等碎片
            first += 1
    j = first
    while j > 0 and first - j < 3:
        prev = lines[j - 1].strip()
        if not (HEAD_LINE.fullmatch(prev) or re.fullmatch(r"(?:行政处罚决定书文号[:：]\s*)?" + DOC_NO.pattern, prev)):
            break
        j -= 1
    if re.search(r"现查明|经查明|经审理查明|违法事实[:：]|拘留|罚款", "\n".join(lines[:j])):
        j = 0  # 被裁掉的部分里有正文：起点判错了，页头原样保留
    # 页脚：正文后第一条页脚标记，且它后面不再有正文（"打印""字号"等也会出现在页头元数据与正文之间）
    body_after = [False] * (len(lines) + 1)
    for k in range(len(lines) - 1, -1, -1):
        body_after[k] = body_after[k + 1] or bool(re.search(r"拘留|罚款|赌|现查明|决定", lines[k]))
    end = next((k for k in range(first + 1, len(lines)) if CHROME_END.match(lines[k].strip()) and not body_after[k + 1]),
               len(lines))
    return "\n".join(lines[j:end]).strip()


def _column_row(nxt: list[str]) -> bool:
    """按列公开表的一行：文号后是案件名（不一定以"案"结尾，如"李某某非法储存危险物质"），再下一行是姓名。"""
    if len(nxt) < 2:
        return False
    case, name = nxt[0].strip(), nxt[1].strip()
    return 2 <= len(case) <= 40 and not re.search(r"[，,。：:]", case) and 1 <= len(name) <= 8 \
        and not re.search(r"[\d，,。：:]", name)


def split_documents(text: str) -> list[str]:
    """一页多份决定书（环江、东兰、路桥等）：按独占一行、且下几行有当事人的文号切开，往前带上机关名与文书名行。
    少于两份不同文号就不拆。"""
    lines = text.split("\n")
    starts, seen = [], set()
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"\s*(?:行政处罚决定书文号[:：]\s*)?" + DOC_NO.pattern + r"\s*", ln)
        if not m:
            continue
        no = re.sub(r"\s", "", m.group(1))
        # 文号后几行要有当事人行；按列排版的公开表（含山）文号后紧跟"××等人赌博案"
        # 表格排版乱序时（环江 2021 年合页）当事人称谓不在行首：下几行里出现"违法行为人+姓"或"现查明"也算
        if no in seen or not (any(_is_subject_line(x) or "现查明" in x or _role_inside(x) for x in lines[i + 1: i + 6])
                              or any(re.fullmatch(r"[^，,。]{2,40}案", x.strip()) for x in lines[i + 1: i + 3])
                              or _column_row(lines[i + 1: i + 3])):
            continue
        j = i
        while j > 0 and i - j < 3 and HEAD_LINE.fullmatch(lines[j - 1].strip()) and (not starts or j - 1 >= starts[-1] + 1):
            j -= 1
        starts.append(j)
        seen.add(no)
    if len(starts) < 2:
        return []
    bounds = starts + [len(lines)]
    return ["\n".join(lines[a:b]).strip() for a, b in zip(bounds, bounds[1:])]


def column_case(text: str) -> tuple[str, str] | None:
    lines = [ln.strip() for ln in text.splitlines()]
    if len(lines) < 5 or not re.fullmatch(DOC_NO.pattern, lines[0]) or not (re.fullmatch(r"[^，。]{2,40}案", lines[1]) or _column_row(lines[1:3])):
        return None
    rest = lines[3:]
    dec_i = next((i for i, ln in enumerate(rest) if re.match(r"根?据《|依据《|依照《", ln) or "之规定" in ln), None)
    if dec_i is None:
        return None
    facts = next((ln for ln in rest[:dec_i] if ln not in ("/", "") and len(ln) >= 15), "")
    return (facts, rest[dec_i]) if facts else None


def split_items(text: str) -> list[str]:
    parts = re.split(r"(?:^|\n|[。；])\s*\d{1,3}[、.．]\s*(?=违法行为人|[一-龥*×xX]{1,8}[，,])", text)
    items = [p.strip() for p in parts if re.search(r"处罚|拘留|罚款", p)]
    if len(items) >= 2:
        return items
    # 不编号、一行一人的汇总页（红塔部分页面）："违法行为人××，因实施赌博的违法行为，于……给予……的处罚。"
    rows = [ln.strip() for ln in text.split("\n")
            if re.match(r"\s*(违法行为人|被处罚人)", ln) and "不服" not in ln and len(ln) < 600
            and re.search(r"(给予|处以|决定对|决定给予)[^。]{0,40}?(拘留|罚款|警告)", ln)]
    names = {re.sub(r"[，,].*", "", re.sub(r"^\s*(违法行为人|被处罚人)\s*[:：]?", "", r))[:6] for r in rows}
    return rows if len(rows) >= 2 and len(names) >= 2 else []


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


# ---------- B 类：事实段尾部定性句裁剪（协同指令 2026-10-17 §2.3，旧 parse 范畴） ----------

CONCLUSION_MARK = re.compile(
    r"决定给予|现决定|决定不予|行为已构成|已构成|情节严重|情节较轻|从轻处罚|减轻处罚|从重处罚"
    r"|不予行政处罚|不予处罚|予以行政处罚")


def trim_facts_conclusions(facts: str) -> tuple[str, bool]:
    """事实段尾部的定性/结论句逐句裁剪。只裁尾部——保住 facts 是原文连续子串的性质
    （build 的 place_segment 依赖它）；内部混入的结论句不动（facts_contains_conclusion
    旗标继续承担豁免）。全句皆结论时不动（返回原文, False），避免把事实裁空。"""
    parts = [p for p in re.split(r"(?<=[。；;])", (facts or "").strip()) if p]
    dropped = 0
    while parts and CONCLUSION_MARK.search(parts[-1]):
        parts.pop()
        dropped += 1
    if not dropped:
        return facts, False
    new = "".join(parts).strip()
    return (new, True) if new else (facts, False)


# ---------- 组装 ----------

def build_case(base: dict, *, facts: str, evidence: str = "", reasoning: str = "", decision: str = "", review: str = "",
               full: str, segmented: bool, review_result: str = "", decision_date: str = "", authority: str = "",
               doc_type: str, outcome_text: str = "") -> dict:
    oc = outcome_from(outcome_text or decision, reasoning)
    if not oc["type"]:
        # 兜底：决定段抽不出结果时，用"执行方式和期限"一句（OCR 常漏掉"留三日。"这类短行，但执行句里会重复拘留天数和罚款）
        m = re.search(r"执行方式[^。]*。", full)
        if m:
            fb = outcome_from(m.group(0))
            if fb["type"]:
                fb["articles"], fb["law_version"] = oc["articles"], oc["law_version"]
                oc = {**fb, "from_execution_clause": True}
    # "行政拘留不执行"写在决定句后的执行一栏（含山公示）：只看紧跟决定段的一小段，免得拿到同页别人的
    if oc["detention_days"] and oc["detention_not_executed"] == "否" and decision and decision in full:
        after = full[full.find(decision) + len(decision):][:80]
        if re.search(NOT_EXECUTED, after):
            oc["detention_not_executed"] = "是"
    no = DOC_NO.findall(full)
    behavior, punish = behavior_and_punish(facts, full)
    title = base.get("title", "")
    # 没有事实段的（字段表只有案件名）用全文判，免得因为事实段留空而被判成非赌博
    judged = ((facts or "") + (decision or "") + (review or "")) if facts else full
    gamb = gambling_status(title, judged, doc_type)
    if gamb == "待定" and len(judged) >= 150:
        gamb = "否"  # "待定"是给截断摘录用的；这里已有全文，全文里没有赌博特征就是"否"
    # 机关名可能只在被去掉的页头、标题或发布单位里（正本从当事人行开始）
    ctx = base.get("_context", "") + base.get("title", "") + base.get("publisher", "")
    police = bool(re.search(r"公安", authority + decision + full[:400] + ctx)) and "治安管理处罚法" in (decision + full)
    # 权责清单、事项清单、裁量基准等规范性页面不是案件（收割阶段蚌埠"权责清单"误入）
    is_norm = classify(title, full[:800]) == "法规清单" or bool(re.search(r"权责清单|事项清单|实施依据.{0,20}责任事项", full[:1500]))
    warns = []
    # 结论词与引擎契约 records.CONCLUSION_WORDS 一致（I-06：漏了"减轻处罚""现决定"）
    if re.search(r"决定给予|现决定|情节严重|从轻处罚|减轻处罚|从重处罚", facts or ""):
        warns.append("facts_contains_conclusion")
    if not oc["type"]:
        warns.append("outcome_not_parsed")
    return {
        **{k: v for k, v in base.items() if k != "_context"},
        "doc_no": no[0][0] if no else "",
        "authority": authority or authority_of(full),
        "behavior_date": behavior,
        "decision_date": _valid_date(decision_date) if decision_date else punish,
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
    # 落款年份可能写成"二0二四年"（塔城，2026-10-16 r2 抽检：决定日期 8 件为空）
    ds = re.findall(r"[〇○零0OＯ一二三四五六七八九]{4}年[一二三四五六七八九十]{1,2}月[一二三四五六七八九十]{1,3}日|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", tail)
    return parse_date(ds[-1]) if ds else ""


def parse_page(page: dict, text: str) -> list[dict]:
    base = {"page_id": page["page_id"], "id": page.get("manifest_id", ""), "source_ref": page["url"],
            "harvest_date": page["fetched_at"][:10], "site": page["site"], "title": page.get("title", ""),
            "publisher": page.get("publisher", ""), "ocr": bool(page.get("ocr"))}
    body_len = len(re.sub(r"\s", "", re.sub(r"附件[:：].*", "", text)))
    if body_len >= 200 or not page.get("attachment_files"):
        docs = split_documents(text)
        if docs:  # 一页多份决定书：逐份当独立页面解析，id 加 -dk
            return [c for k, d in enumerate(docs, 1)
                    for c in parse_page({**page, "manifest_id": f"{base['id']}-d{k}", "attachment_files": []}, d)]
        if not page.get("ocr"):  # OCR 文本没有网页导航
            base["_context"] = text[:1500]
            text = canonical(text)
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
    col = column_case(text)
    if col:  # 按列排版的公开表（含山）：拆出来的每份是"文号、案件名、姓名、……、事实、依据与结果"一列一行
        facts, decision = col
        # 落款日期取决定句之后的第一个日期（I-05：落款"2023.3.92023.3.9"粘连，parse_date 按"9 后接年份"切开）
        tail = text[text.find(decision) + len(decision):]
        tail = re.sub(r"(?:执行期限|期限)[^\n]*", "", tail)
        dm = re.search(r"20\d{2}\s*[.．。/年-]\s*\d{1,2}\s*[.．。/月-]\s*\d{1,2}", tail)
        ddate = parse_date(tail[dm.start():dm.start() + 12]) if dm else ""
        ddate = ddate if len(ddate) == 10 else ""
        return [build_case({**base, "source_type": "执法公示"}, facts=facts, decision=decision, full=text, segmented=True,
                           decision_date=ddate, authority=authority_of(text), doc_type="处罚决定")]
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
        # I-12：没有"违法事实"栏时（翁牛特旗等字段表只有"××等人赌博案"），事实段留空——案件名不是事实，
        # 拿它当事实段会让下游以为有案情；这类记录进"只有结果"文件
        fv.setdefault("facts", "")
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
        ocr_path = hdir / "ocr" / f"{p['page_id']}.txt"
        if ocr_path.exists():  # 扫描件页面：用 OCR 文本解析（ocr.py 产出）
            cases += parse_page({**p, "ocr": True}, ocr_path.read_text(encoding="utf-8"))
        else:
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
        "ocr_cases": sum(bool(c.get("ocr")) for c in cases), "ocr_in_scope": sum(bool(c.get("ocr")) for c in scope),
    }
    (out_dir / "web_cases.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
