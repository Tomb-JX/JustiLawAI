"""北大法宝（渠道 C）导出文件 → 结构化数据（对齐 docs/05-research/data-spec.md v0.1）。

实测的两种导出形态（2026-10-16，沪公长(长新)行罚决字〔2025〕00289/00290 两份实样）：

  目录列表 .xls（"北大法宝V6-行政执法-行政执法字段表单"）
    第 1 行：子库与表单名；第 2 行：搜索条件 + 下载时间（进数据卡，必须留住）；
    第 3 行：字段名（序号/标题/执法机关/发文案号/公布日期/行政相对人/执法依据/处罚种类/执法地域/原文链接/罚没总金额（万元））；
    其后为数据行；末尾是版权与二维码页脚（**不是数据**，解析时必须按标记截断）。
    .xls 是 BIFF8 二进制，先用 pkulaw_xls2csv.ps1（Excel COM）转 UTF-8 CSV 再交给本脚本。

  文书 .doc / .docx（处罚决定书公示；司法案例库判决书形态待取得样本后另加解析器）
    元数据块 10 项：主题分类/处罚种类/行政相对人/执法级别/执法机关/执法地域/公布日期/发文案号/罚没情况/执法依据
    决定表 7 行：文号/被处罚对象/处罚事由/处罚依据/处罚结果/处罚决定日期/处罚机关
    页脚：法宝版权 + 原文链接（含 32 位哈希）。法宝引证码（FBM-CLI.…）在**文件名**里。
    .doc 用 antiword 取文本（本机已有），失败退回 Word COM；.docx 用 python-docx。

**这类执法公示摘要没有违法事实、没有行为日期**（决定处罚结果的信息不在文本里）——按 D6 只能进
`admin_outcomes_only.jsonl`（结果-only 层，用于分布校准与 T-time 计数，不进金标、不作模型输入）。
脚本据事实段是否为空自动分级：有事实 → `admin_cases.jsonl`（金标候选），无事实 → 结果-only 层。

用法（仓库根目录）：
  # 1) 目录表 → 工作清单（哪些还没下全文；按法条/省/案由/年份统计，用来决定下一批下什么）
  python research/discretion/collect/pkulaw_ingest.py catalog --xls inbox/pkulaw/R1/【北大法宝】目录列表.xls \\
      --out $JUSTILAW_DATA_DIR/pkulaw/R1
  # 2) 已下全文 → 结构化记录（与工作清单按文号 join）
  python research/discretion/collect/pkulaw_ingest.py docs --docs inbox/pkulaw/R1-docs \\
      --worklist $JUSTILAW_DATA_DIR/pkulaw/R1/worklist.csv --out $JUSTILAW_DATA_DIR/admin
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import DATA_DIR, report, sha256_path  # noqa: E402

SCHEMA_VERSION = "0.1"  # data-spec v0.1
DOC_EXTS = {".doc", ".docx", ".txt", ".md"}

# ---------- 中文数字与金额 ----------

CN = {"〇": 0, "零": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
      "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
NUM = r"[\d,，.]+|[〇零一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万]+"


def cn2int(s: str) -> int | None:
    """中文/大写/阿拉伯数字 → 整数（三百→300、1382→1382、两千→2000）；无法解析返回 None。"""
    s = (s or "").replace(",", "").replace("，", "").replace("整", "").strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    if re.fullmatch(r"\d+\.0*", s):
        return int(float(s))
    if not s or any(ch not in CN and ch not in UNIT and ch != "万" for ch in s):
        return None
    total = section = digit = 0
    for ch in s:
        if ch in CN:
            digit = CN[ch]
        elif ch in UNIT:
            section += (digit or 1) * UNIT[ch]
            digit = 0
        elif ch == "万":
            total += (section + digit) * 10000
            section = digit = 0
    return total + section + digit


def cn_num_to_arabic_article(s: str) -> str:
    """条号统一成中文数字写法（data-spec §1.4 的 '治安管理处罚法第七十条'）：第82条 → 第八十二条。"""
    m = re.fullmatch(r"第?(\d{1,4})条", s.strip())
    if not m:
        return s
    n = int(m.group(1))
    if n == 0:
        return s
    cn = "零一二三四五六七八九"
    out = ""
    if n >= 1000:
        out += cn[n // 1000] + "千"
        n %= 1000
    if n >= 100:
        out += cn[n // 100] + "百"
        n %= 100
    if n >= 10:
        if n // 10 > 1:
            out += cn[n // 10]
        out += "十"
        n %= 10
    if n:
        out += cn[n]
    return "第" + out + "条"


# ---------- 日期 ----------

def parse_date(s: str) -> str:
    """'2025.12.29' / '2025-12-29' / '2025年12月29日' / '二〇二五年十二月二十九日' → '2025-12-29'。"""
    s = (s or "").strip()
    m = re.search(r"(\d{4})[.\-/年](\d{1,2})[.\-/月]?(\d{1,2})?", s)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        return f"{y}-{mo:02d}-{int(d):02d}" if d else f"{y}-{mo:02d}"
    m = re.search(r"([〇零一二三四五六七八九]{4})年([〇零一二三四五六七八九十]{1,3})月([〇零一二三四五六七八九十]{1,3})日", s)
    if m:
        y = m.group(1).translate(str.maketrans("〇零一二三四五六七八九", "00123456789"))
        mo = cn2int(m.group(2)) or 0
        d = cn2int(m.group(3)) or 0
        return f"{y}-{mo:02d}-{d:02d}"
    return ""


# ---------- 目录列表 ----------

CATALOG_FIELDS = ["序号", "标题", "执法机关", "发文案号", "公布日期", "行政相对人",
                  "执法依据", "处罚种类", "执法地域", "原文链接", "罚没总金额（万元）"]
# 司法案例库的目录表是完全另一套列（实测 2026-10-16）——两套合起来当"已知列名"用来自动找表头行
CASE_FIELDS = ["序号", "标题", "审理程序", "案由", "文书类型", "审理法院", "案件字号", "审结日期", "省份"]
KNOWN_COLUMNS = set(CATALOG_FIELDS) | set(CASE_FIELDS)
FOOTER_MARKS = ("©", "北大法宝", "扫码", "法宝快讯")
DATE_FIELDS = ("公布日期", "审结日期")
PROVINCES = ("北京市 天津市 上海市 重庆市 河北省 山西省 辽宁省 吉林省 黑龙江省 江苏省 浙江省 安徽省 福建省 "
             "江西省 山东省 河南省 湖北省 湖南省 广东省 海南省 四川省 贵州省 云南省 陕西省 甘肃省 青海省 "
             "台湾省 内蒙古自治区 广西壮族自治区 西藏自治区 宁夏回族自治区 新疆维吾尔自治区").split()


def read_table(path: Path) -> list[list[str]]:
    """读目录表：.xls 用 xlrd（BIFF8，纯 Python，无需装 Excel）；.csv 直接读（utf-8-sig）。

    .xls 优先用 xlrd 而不是 Excel COM：COM 在批量/无人值守时会因受保护视图或残留进程卡死（实测踩过）。
    `pkulaw_xls2csv.ps1` 只在没有 xlrd 的机器上用。
    """
    if path.suffix.lower() in {".xls", ".xlsx"}:
        import xlrd  # pip install xlrd（只支持 .xls；.xlsx 请先另存为 CSV）

        wb = xlrd.open_workbook(str(path))
        out: list[list[str]] = []
        for sh in wb.sheets():
            for i in range(sh.nrows):
                out.append([str(sh.cell_value(i, j)).strip() for j in range(sh.ncols)])
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [list(r) for r in csv.reader(f)]


def province_of(text: str) -> str:
    """从法院全名/地域里取省级名：'湖南省溆浦县人民法院' → '湖南省'。"""
    for p in PROVINCES:
        if p in (text or ""):
            return p
    return ""


def parse_catalog(path: Path) -> tuple[dict, list[dict]]:
    """目录列表（行政执法库 / 司法案例库两种形态）→ (表头元信息, 数据行)。

    表头行按"已知列名出现 ≥3 个"识别，列名原样保留——子库新增列不需要改代码；
    页脚（版权、二维码）按标记截断，不混进数据。
    """
    grid = read_table(path)
    meta = {"catalog_file": path.name, "library": "", "search": "", "download_time": ""}
    header_at: int | None = None
    fields: list[str] = []
    for i, row in enumerate(grid):
        joined = ",".join(row)
        if not meta["library"] and "北大法宝" in joined:
            meta["library"] = (row[0] if row else "").strip()
        if "搜索条件" in joined:
            m = re.search(r"搜索条件[:：](.*?)(?:；|;|,|，|$)", joined)
            meta["search"] = (m.group(1) if m else joined).strip()
            mt = re.search(r"下载时间[:：]([\d\-/.]+)", joined)
            if mt:
                meta["download_time"] = parse_date(mt.group(1))
        if sum(1 for c in row if c.strip() in KNOWN_COLUMNS) >= 3:
            header_at, fields = i, [c.strip() for c in row]
            break
    if header_at is None:
        raise SystemExit(f"{path}: 找不到字段名行（已知列名 ≥3 个），不是法宝目录列表导出？")

    data: list[dict] = []
    for row in grid[header_at + 1:]:
        cells = [c.strip() for c in row]
        joined = "".join(cells)
        if not joined or any(joined.startswith(mk) for mk in FOOTER_MARKS):
            continue
        rec = {f: (cells[j] if j < len(cells) else "") for j, f in enumerate(fields) if f}
        if not (rec.get("标题") or rec.get("发文案号") or rec.get("案件字号")):
            continue
        for df in DATE_FIELDS:
            if rec.get(df):
                rec[df] = parse_date(rec[df])
        amount = rec.get("罚没总金额（万元）", "")
        if "罚没总金额（万元）" in rec:
            rec["罚没总金额_元"] = int(round(float(amount) * 10000)) if re.fullmatch(r"\d+(\.\d+)?", amount or "") else None
        # 省份规范化：行政执法库给"执法地域"；司法案例库给法院全名（"湖南省溆浦县人民法院"）
        rec["省份规范"] = province_of(rec.get("执法地域", "")) or province_of(rec.get("省份", ""))
        data.append(rec)
    return meta, data


def catalog_stats(rows: list[dict]) -> dict:
    """按子库自适应统计——用来决定下一批下什么（省域普查、法条版本分片、案由分片）。"""
    stats: dict = {"件数": len(rows)}
    if any(r.get("执法依据") for r in rows):
        law = Counter()
        for r in rows:
            basis = r.get("执法依据", "")
            ver = "新法" if ("2025" in basis and "修订" in basis) else ("旧法" if "2012" in basis else "未知")
            art_m = re.search(r"第\s*(\d+)\s*条", basis)
            label = cn_num_to_arabic_article("第" + art_m.group(1) + "条") if art_m else "未识别"
            law[f"{ver} {label}"] += 1
        stats["按法律版本与法条"] = dict(law.most_common())
    if any(r.get("案由") for r in rows):
        stats["按案由（一级）"] = dict(Counter(
            (r.get("案由", "").split("/")[0].split(">")[0] or "未知") for r in rows).most_common())
        stats["按案由（末级）"] = dict(Counter(
            (r.get("案由", "").rstrip(";；").split(">")[-1] or "未知") for r in rows).most_common())
        stats["按文书类型"] = dict(Counter(r.get("文书类型", "") or "未知" for r in rows).most_common())
    if any(r.get("处罚种类") for r in rows):
        stats["按处罚种类"] = dict(Counter(r.get("处罚种类", "") or "未知" for r in rows).most_common())
    stats["按省份"] = dict(Counter(r.get("省份规范") or "未知" for r in rows).most_common(15))
    years = Counter((r.get("公布日期") or r.get("审结日期") or "未知")[:4] for r in rows)
    stats["按年份"] = dict(sorted(years.items()))
    return stats


# ---------- 文书文本获取 ----------

def doc_to_text(path: Path) -> tuple[str, str]:
    """'.doc/.docx/.txt' → (文本, 取文本方式)。.doc 优先 antiword，退回 Word COM。"""
    suf = path.suffix.lower()
    if suf in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace"), "plain"
    if suf == ".docx":
        import docx  # python-docx：按段落 + 表格单元格拼接

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append("\t".join(c.text.replace("\n", " ").strip() for c in row.cells))
        return "\n".join(parts), "python-docx"
    if suf == ".doc":
        if shutil.which("antiword"):
            out = subprocess.run(["antiword", str(path)], capture_output=True)
            if out.returncode == 0 and out.stdout.decode("utf-8", "replace").strip():
                return out.stdout.decode("utf-8", "replace"), "antiword"
        text = _doc_via_word_com(path)
        if text:
            return text, "word-com"
        raise RuntimeError(f"{path}: .doc 取文本失败（antiword 与本机 Word 都不可用）")
    raise ValueError(f"不支持的扩展名：{path.suffix}")


def _doc_via_word_com(path: Path) -> str:
    """Word COM 兜底（本机装了 Office）。导出为 UTF-8 文本再读回。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "out.txt"
        ps = (
            "$ErrorActionPreference='Stop';"
            "$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
            f"$d=$w.Documents.Open('{path}', $false, $true);"
            f"$d.SaveAs('{dst}', 2);"  # wdFormatText
            "$d.Close($false);$w.Quit()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, timeout=120)
        if dst.exists():
            raw = dst.read_bytes()
            for enc in ("utf-8", "gbk", "utf-16"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
    return ""


# ---------- 处罚决定书公示（行政执法库）解析 ----------

META_LABELS = ["主题分类", "处罚种类", "行政相对人", "执法级别", "执法机关", "执法地域",
               "公布日期", "发文案号", "罚没情况", "执法依据"]
TABLE_ROWS = ["行政处罚决定书文号", "被处罚对象", "处罚事由", "处罚依据", "处罚结果",
              "处罚决定日期", "处罚机关"]
LAW_ALIAS = {"中华人民共和国治安管理处罚法": "治安管理处罚法", "治安管理处罚法": "治安管理处罚法"}


def _meta_value(body: str, label: str) -> str:
    """元数据块取值：从标签后取到"下一个字段名"或行尾（两种排版都容错：每字段一行 / 同一行内多字段）。"""
    m = re.search(rf"{label}\s*[:：]\s*", body)
    if not m:
        return ""
    rest = body[m.end():]
    nxt = re.search(rf"(?:{'|'.join(META_LABELS)}|{TABLE_ROWS[0]})\s*[:：]", rest)
    candidate = rest[: nxt.start()] if nxt else rest
    return re.sub(r"\s+", " ", candidate.split("\n")[0]).strip()


def pkulaw_id_from_name(name: str) -> str:
    """文件名里的法宝引证码：'…(FBM-CLI.ALE.47644244).doc' → 'FBM-CLI.ALE.47644244'。"""
    m = re.search(r"\(([A-Z]{3}-[A-Z]+(?:\.[A-Z]+)*\.\d+)\)", name)
    return m.group(1) if m else ""


def parse_enforcement_doc(text: str, *, filename: str = "") -> dict:
    """行政执法库处罚决定书公示 → 元数据块 + 决定表 + 页脚链接。无事实、无行为日期。"""
    # 去掉版权页脚（原文链接要单独留）
    src_url = ""
    m = re.search(r"原文链接[:：]\s*(https?://\S+)", text)
    if m:
        src_url = m.group(1).strip()
    body = re.split(r"©\s*北大法宝", text)[0]

    meta = {label: _meta_value(body, label) for label in META_LABELS}

    table: dict[str, str] = {}
    for label in TABLE_ROWS:
        mm = re.search(rf"\|\s*{label}\s*\|\s*([^|]*)\|", body)
        if not mm:
            mm = re.search(rf"{label}\s*[:：]?\s*\|?\s*([^|\n]*)\|?", body)
        table[label] = (mm.group(1).strip() if mm else "")

    return {
        "pkulaw_id": pkulaw_id_from_name(filename),
        "doc_no": table.get("行政处罚决定书文号") or meta.get("发文案号", ""),
        "subject": table.get("被处罚对象") or meta.get("行政相对人", ""),
        "authority": table.get("处罚机关") or meta.get("执法机关", ""),
        "region_text": meta.get("执法地域", ""),
        "publish_date": parse_date(meta.get("公布日期", "")),
        "decision_date": parse_date(table.get("处罚决定日期", "") or meta.get("公布日期", "")),
        "penalty_kinds": meta.get("处罚种类", ""),
        "fine_note": meta.get("罚没情况", ""),
        "basis_text": table.get("处罚依据", ""),
        "basis_meta": meta.get("执法依据", ""),      # 法宝结构化字段：带 2012修正/2025修订 版本字样
        "result_text": table.get("处罚结果", ""),
        "subject_matter": table.get("处罚事由", ""),
        "source_url": src_url,
        "body": body.strip(),
    }


def law_version_raw(*texts: str) -> str:
    """法宝"执法依据"里的版本字样：'…(2012修正) 第70条' / '…(2025修订) 第82条' → '2012修正' / '2025修订'。"""
    joined = "\n".join(t for t in texts if t)
    if "2025" in joined and "修订" in joined:
        return "2025修订"
    if "2012" in joined:
        return "2012修正"
    return ""


def parse_articles(basis_text: str, version_text: str = "") -> tuple[list[str], str]:
    """→ (法条列表, 法律版本)。'《中华人民共和国治安管理处罚法》第七十条' → (['治安管理处罚法第七十条'], '旧法')。

    版本字样只在法宝结构化字段"执法依据"里（决定表的"处罚依据"没有），所以要单独传 version_text。
    法律版本统一成引擎在用的枚举（旧法 / 新法 / 未知；见 text-processing-spec §2），
    法宝原文写法（2012修正 / 2025修订）由 law_version_raw 另存 quality.law_version_raw 备查。
    """
    raw = law_version_raw(version_text, basis_text)
    law_version = {"2012修正": "旧法", "2025修订": "新法"}.get(raw, "")
    arts: list[str] = []
    for name, short in LAW_ALIAS.items():
        for m in re.finditer(rf"{name}[^第\n]*?(第\s*[\d一二三四五六七八九十百零]+\s*条)", basis_text):
            arts.append(short + cn_num_to_arabic_article(m.group(1)))
    if not arts:  # 《中华人民共和国治安管理处罚法》第七十条 这种书名号写法
        for m in re.finditer(r"《([^》]+)》\s*(第\s*[\d一二三四五六七八九十百零]+\s*条)", basis_text):
            short = LAW_ALIAS.get(m.group(1), m.group(1))
            arts.append(short + cn_num_to_arabic_article(m.group(2)))
    if not arts and version_text:
        for m in re.finditer(r"第\s*([\d一二三四五六七八九十百零]+)\s*条", version_text):
            arts.append("治安管理处罚法" + cn_num_to_arabic_article("第" + m.group(1) + "条"))
    return list(dict.fromkeys(arts)), law_version


def outcome_from(result_text: str, penalty_kinds: str, fine_note: str = "") -> dict:
    """处罚结果/处罚种类 → outcome（data-spec §1.4）。拘留天数、罚款额可能两者都写在一句里。"""
    r = result_text or ""
    det = [cn2int(x) for x in re.findall(rf"(?:行政拘留|拘留)\s*({NUM})\s*[日天]", r)]
    det = [d for d in det if d]
    merged = re.search(rf"合并执行[^，。；;]*?({NUM})\s*[日天]", r)
    fines = [cn2int(x) for x in re.findall(rf"罚款\s*(?:人民币)?\s*({NUM})\s*元", r) + re.findall(rf"罚款\s*({NUM})\s*元", fine_note)]
    fines = [x for x in fines if x]
    days = (cn2int(merged.group(1)) if merged else None) or (det[0] if det else 0)
    fine = fines[0] if fines else 0

    if re.search(r"不予处罚|不予行政处罚", r):
        ptype = "不予处罚"
    elif re.search(r"不构成违法", r):
        ptype = "不构成违法"
    elif re.search(r"移送|涉嫌犯罪", r):
        ptype = "移送刑事"
    elif days and fine:
        ptype = "拘留并处罚款"
    elif days:
        ptype = "拘留"
    elif fine:
        ptype = "罚款"
    elif "警告" in r or "警告" in penalty_kinds:
        ptype = "警告"
    else:
        ptype = ""

    confiscation = ""
    if "没收" in penalty_kinds:
        confiscation = "、".join(p for p in re.split(r"[、,，]", penalty_kinds) if "没收" in p)
    return {
        "type": ptype,
        "detention_days": days,
        "detention_items": det,
        "fine": fine,
        "detention_not_executed": "是" if re.search(r"不执行(?:行政)?拘留|不送(?:达)?拘留所|依法不执行", r) else "否",
        "confiscation": confiscation,
        "articles": [],
        "law_version": "",
        "stated_circumstances": [c for c in ("情节严重", "情节较轻", "从轻", "减轻", "从重", "认错认罚") if c in r],
    }


def build_record(parsed: dict, *, manifest_id: str = "", harvest_date: str = "",
                 catalog_row: dict | None = None) -> dict:
    """解析结果 → data-spec v0.1 §1 的交付记录（脱敏前，deidentified=false）。"""
    articles, law_version = parse_articles(parsed["basis_text"], parsed["basis_meta"])
    oc = outcome_from(parsed["result_text"], parsed["penalty_kinds"], parsed["fine_note"])
    oc["articles"] = articles
    oc["law_version"] = law_version
    lv_raw = law_version_raw(parsed["basis_meta"], parsed["basis_text"])

    facts = ""  # 执法公示摘要没有违法事实；判决书解析器落地后此字段才有值
    warns = []
    if not facts:
        warns.append("facts_missing")
    if not oc["type"]:
        warns.append("outcome_not_parsed")
    if not articles:
        warns.append("articles_not_parsed")
    cat_fine = (catalog_row or {}).get("罚没总金额_元")
    try:
        cat_fine = int(float(cat_fine))
    except (TypeError, ValueError):
        cat_fine = None
    if cat_fine is not None and cat_fine > 0 and oc["fine"] != cat_fine:
        warns.append(f"fine_mismatch:doc={oc['fine']},catalog={cat_fine}")

    return {
        "id": manifest_id,                       # 台账 id（由 import_manual/manifest 分配）
        "pkulaw_id": parsed["pkulaw_id"],        # 法宝引证码：稳定主键，去重与复下都靠它
        "source_type": "执法公示",
        "source_ref": f"文号哈希待生成（D3）｜原文链接见台账",  # D3 建议 B：交付不直接写 URL
        "doc_no": parsed["doc_no"],
        "harvest_date": harvest_date or datetime.now().strftime("%Y-%m-%d"),
        "deidentified": False,                   # 法宝已遮挡人名，但仍须 R6 扫描 + 人工确认
        "behavior_date": None,                   # 硬缺口：执法公示不发行为日期
        "decision_date": parsed["decision_date"],
        "authority": parsed["authority"],
        "region": parsed["region_text"],
        "text_full": parsed["body"],
        "segmented": False,
        "text_facts": facts,
        "text_evidence": "",
        "text_reasoning": "",
        "text_decision": parsed["result_text"],
        "text_review": "",
        "outcome": oc,
        "review": {"result": "无", "changed_outcome": ""},
        "quality": {
            "has_amount": bool(facts),           # 事实段里的金额才算（CAIL 教训：这是信息完整度）
            "has_outcome": bool(oc["type"]),
            "outcome_only": not facts,           # True → 只能进结果-only 层（D6）
            "law_version_raw": lv_raw,           # 法宝原文写法（2012修正 / 2025修订），备查
            "parse_warnings": warns,
        },
        # 事件分组提示（门禁 §7 防泄漏）：同机关 + 同决定日 + 文号连号多为同一次查处
        "event_hint": {"authority": parsed["authority"], "decision_date": parsed["decision_date"],
                       "doc_seq": _doc_seq(parsed["doc_no"])},
    }


def _doc_seq(doc_no: str) -> str:
    m = re.findall(r"(\d{3,})", doc_no or "")
    return m[-1] if m else ""


# ---------- 子命令 ----------

def cmd_catalog(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta, rows = parse_catalog(Path(args.xls))
    worklist = out / "worklist.csv"
    fields = list(rows[0].keys()) if rows else []
    for ff in ("法宝引证码", "已下全文"):
        if ff not in fields:
            fields.append(ff)
    with open(worklist, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r.setdefault("已下全文", "")
            w.writerow(r)
    stats = catalog_stats(rows)
    stats["表头元信息"] = meta
    (out / "catalog.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    report(f"目录解析：{len(rows)} 条 → {worklist}")
    report(f"  {meta['library']}｜搜索条件：{meta['search']}（下载时间 {meta['download_time']}）")
    for k, v in catalog_stats(rows).items():
        report(f"  {k}：{v}")


def cmd_docs(args) -> None:
    docs_dir = Path(args.docs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in docs_dir.rglob("*") if p.suffix.lower() in DOC_EXTS and p.is_file())
    if not files:
        raise SystemExit(f"{docs_dir} 下没有可解析的文书（{sorted(DOC_EXTS)}）")

    by_no: dict[str, dict] = {}
    if args.worklist and Path(args.worklist).exists():
        with open(args.worklist, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                by_no[r.get("发文案号", "")] = r

    # 台账 id：按文件 SHA-256 与 manifest 对齐（原始文件先经 import_manual.py 入库）
    id_by_sha: dict[str, str] = {}
    if args.manifest and Path(args.manifest).exists():
        with open(args.manifest, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("sha256"):
                    id_by_sha[r["sha256"]] = r.get("id", "")

    records, counters, sha_lines = [], Counter(), []
    for p in files:
        text, how = doc_to_text(p)
        parsed = parse_enforcement_doc(text, filename=p.name)
        cat = by_no.get(parsed["doc_no"])
        sha = sha256_path(p)
        rec = build_record(parsed, manifest_id=id_by_sha.get(sha, ""), harvest_date=args.harvest_date,
                           catalog_row=cat)
        rec["quality"]["text_source"] = how
        if args.manifest and not rec["id"]:
            rec["quality"]["parse_warnings"].append("not_in_manifest")  # 先跑 import_manual.py 入库
        records.append(rec)
        counters["total"] += 1
        counters["in_worklist" if cat else "not_in_worklist"] += 1
        for w in rec["quality"]["parse_warnings"]:
            counters[f"warn:{w.split(':')[0]}"] += 1
        sha_lines.append(f"{sha}  {p.name}")

    cases = [r for r in records if not r["quality"]["outcome_only"]]
    only = [r for r in records if r["quality"]["outcome_only"]]
    written = []
    for name, subset in (("admin_cases.jsonl", cases), ("admin_outcomes_only.jsonl", only)):
        if not subset:
            continue
        target = out / name
        with open(target, "w", encoding="utf-8") as f:
            for r in subset:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        written.append(target)
    (out / "SHA256SUMS").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")

    # 回写工作清单：标记哪些已下全文（三天窗口里靠这张表决定"还差哪些"）
    if by_no and args.worklist and Path(args.worklist).exists():
        got = {r["doc_no"]: r["pkulaw_id"] for r in records if r["doc_no"]}
        with open(args.worklist, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        for ff in ("法宝引证码", "已下全文"):
            if ff not in fields:
                fields.append(ff)
        for row in rows:
            if row.get("发文案号") in got:
                row["法宝引证码"] = got[row["发文案号"]]
                row["已下全文"] = "是"
        with open(args.worklist, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        done = sum(1 for r in rows if r.get("已下全文") == "是")
        report(f"  工作清单已回写：{done}/{len(rows)} 条已下全文 ← {args.worklist}")

    stats = {
        "schema_version": SCHEMA_VERSION,
        "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "counts": dict(counters),
        "outcome_only": len(only),
        "with_facts": len(cases),
        "outcome_types": dict(Counter(r["outcome"]["type"] or "未解析" for r in records)),
        "law_versions": dict(Counter(r["outcome"]["law_version"] or "未知" for r in records)),
        "files": [t.name for t in written],
    }
    (out / "pkulaw_ingest.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    report(f"解析 {len(records)} 份文书（文本来源 {dict(Counter(r['quality']['text_source'] for r in records))}）")
    report(f"  结果-only（无事实，D6）：{len(only)} → admin_outcomes_only.jsonl")
    report(f"  有事实（金标候选）：{len(cases)} → admin_cases.jsonl")
    report(f"  处罚类型分布：{stats['outcome_types']}")
    report(f"  法律版本分布：{stats['law_versions']}")
    report(f"  质量提示：{ {k: v for k, v in counters.items() if k.startswith('warn:')} }")
    report(f"  产出目录：{out}（含 SHA256SUMS）")


def main() -> None:
    ap = argparse.ArgumentParser(description="北大法宝导出 → 结构化数据（data-spec v0.1）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog", help="目录列表（.xls / CSV）→ 工作清单与统计")
    c.add_argument("--xls", "--catalog", dest="xls", required=True, help="法宝导出的目录列表 .xls（或已转好的 CSV）")
    c.add_argument("--out", default=str(DATA_DIR / "pkulaw"))
    c.set_defaults(func=cmd_catalog)
    d = sub.add_parser("docs", help="已下全文（.doc/.docx/.txt）→ 结构化 JSONL")
    d.add_argument("--docs", required=True, help="放导出文书的目录（递归）")
    d.add_argument("--worklist", default="", help="catalog 产出的 worklist.csv（按文号 join）")
    d.add_argument("--manifest", default=str(HERE / "manifest.csv"),
                   help="台账 manifest.csv：按文件 SHA-256 回填 id（默认本目录下的台账）")
    d.add_argument("--harvest-date", default="")
    d.add_argument("--out", default=str(DATA_DIR / "admin"))
    d.set_defaults(func=cmd_docs)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
