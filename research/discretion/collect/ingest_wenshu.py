"""裁判文书第三方采购到货入库（channel=C，需求见 docs/05-research/wenshu-retrieval-plan.md v0.3）。

卖家默认 xlsx 每份一行，无文书 ID。本脚本做的事（全在需求文档 §2/§4 约定内）：
  1. 读 $JUSTILAW_DATA_DIR/inbox/wenshu/ 下的 xlsx / csv / jsonl；
  2. **丢弃"当事人"列**（含真实姓名，绝不落盘）；
  3. 算替代主键 = 案号 + 文书类型 + 裁判日期 + 正文 SHA-1（同一案号两份不同正文的样例已出现）；
  4. 省份从案号代字推导（不买卖家省字段），旧式案号退回"法院名称含省名"，再不行留空进人工清单；
  5. 按主键去重（批内 + 对历史台账）；
  6. 产出清洗后 JSONL（外置目录 wenshu/imported/<批次>/）+ SHA256SUMS + manifest 台账行（channel=C）。

用法：
  python ingest_wenshu.py            # 处理 inbox/wenshu/ 全部新文件
  python ingest_wenshu.py --dry-run  # 只统计不写盘

合规：原始到货文件只在外置数据目录，不入库、不二次分发（需求 §5）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from common import DATA_DIR, manifest_add, report

INBOX = DATA_DIR / "inbox" / "wenshu"
OUT_ROOT = DATA_DIR / "wenshu" / "imported"

# 案号代字 → 省级行政区（2016 年起新式案号首字；蒙/藏/新等为简称）
ABBR2PROV = {
    "京": "北京市", "津": "天津市", "沪": "上海市", "渝": "重庆市",
    "冀": "河北省", "晋": "山西省", "蒙": "内蒙古自治区", "辽": "辽宁省", "吉": "吉林省",
    "黑": "黑龙江省", "苏": "江苏省", "浙": "浙江省", "皖": "安徽省", "闽": "福建省",
    "赣": "江西省", "鲁": "山东省", "豫": "河南省", "鄂": "湖北省", "湘": "湖南省",
    "粤": "广东省", "桂": "广西壮族自治区", "琼": "海南省", "川": "四川省", "贵": "贵州省",
    "云": "云南省", "藏": "西藏自治区", "陕": "陕西省", "甘": "甘肃省", "青": "青海省",
    "宁": "宁夏回族自治区", "新": "新疆维吾尔自治区",
}
PROV_NAMES = sorted(ABBR2PROV.values(), key=len, reverse=True)
# （2023）鲁1322民初… / (2023)鲁1322…，括号全半角都收
CASE_NO_RE = re.compile(r"[（(](\d{4})[）)]([京津沪渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新])")

COLUMN_ALIASES = {
    "case_name": ["案件名称", "标题"],
    "court": ["法院名称", "法院"],
    "cause": ["案由"],
    "procedure": ["审判程序"],
    "case_no": ["案号"],
    "case_type": ["案件类型"],
    "publish_date": ["发布日期"],
    "judgment_date": ["裁判日期", "判决日期"],
    "text": ["正文", "全文"],
    # "当事人"列刻意不在映射里：入库即丢弃
}


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def norm_col(name: str) -> str | None:
    for key, aliases in COLUMN_ALIASES.items():
        if name.strip() in aliases:
            return key
    return None


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            report(f"[跳过] {path.name}: xlsx 需要 openpyxl（pip install openpyxl）")
            return []
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(c or "") for c in next(it)]
        rows = []
        for vals in it:
            rows.append({norm_col(h) or h: ("" if v is None else str(v)) for h, v in zip(header, vals) if norm_col(h)})
        wb.close()
        return rows
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = [norm_col(h) or "" for h in (reader.fieldnames or [])]
            return [{k: v for k, v in zip(header, row.values()) if k in COLUMN_ALIASES}
                    for row in reader]
    if path.suffix.lower() == ".jsonl":
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                rows.append({norm_col(k) or k: str(v) for k, v in raw.items() if norm_col(k)})
        return rows
    report(f"[跳过] 不认识的格式：{path.name}")
    return []


def derive_province(case_no: str, court: str) -> str:
    m = CASE_NO_RE.search(case_no or "")
    if m:
        return ABBR2PROV[m.group(2)]
    for prov in PROV_NAMES:
        if prov.rstrip("省市自治区特别行政区") in (court or "") and len(prov.rstrip("省市自治区")) >= 2:
            if prov[:2] in court or prov in court:
                return prov
    return ""


def doc_type(row: dict) -> str:
    name = row.get("case_name", "")
    t = row.get("case_type", "")
    kind = "判决书" if "判决" in name else "裁定书" if "裁定" in name else "其他文书"
    return f"{t}{kind}" if t else kind


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not INBOX.exists():
        report(f"到货目录不存在：{INBOX}")
        return
    files = [p for p in sorted(INBOX.iterdir()) if p.suffix.lower() in (".xlsx", ".csv", ".jsonl")]
    if not files:
        report(f"inbox 无待处理文件：{INBOX}")
        return

    batch = time.strftime("%Y%m%d-%H%M%S")
    n_in = n_ok = n_dup = n_nokey = n_noprov = 0
    records: list[dict] = []
    seen_keys: set[str] = set()

    for path in files:
        for row in read_rows(path):
            n_in += 1
            case_no = (row.get("case_no") or "").strip()
            text = (row.get("text") or "").strip()
            if not case_no or not text:
                n_nokey += 1
                continue
            jdate = (row.get("judgment_date") or "").strip()[:10]
            dtype = doc_type(row)
            pk_hash = sha1(f"{case_no}|{dtype}|{jdate}|{text}")
            key = f"{case_no}#{pk_hash[:12]}"
            if key in seen_keys:
                n_dup += 1
                continue
            seen_keys.add(key)
            prov = derive_province(case_no, row.get("court", ""))
            n_noprov += 0 if prov else 1
            records.append({
                "primary_key": pk_hash,
                "case_no": case_no,
                "case_name": row.get("case_name", ""),
                "court": row.get("court", ""),
                "cause": row.get("cause", ""),
                "procedure": row.get("procedure", ""),
                "case_type": row.get("case_type", ""),
                "publish_date": (row.get("publish_date") or "").strip()[:10],
                "judgment_date": jdate,
                "province": prov,
                "doc_type": dtype,
                "text_full": text,
                "segmented": False,
                "channel": "C",
                "source_ref": key,
                "batch": batch,
            })
            n_ok += 1

    report(f"输入 {n_in} 行：有效 {n_ok}、缺案号或正文 {n_nokey}、批内重复 {n_dup}；省份推导失败 {n_noprov}（人工清单）")
    if dry or not records:
        return

    out_dir = OUT_ROOT / batch
    out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = out_dir / "wenshu.jsonl"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sums = "\n".join(f"{hashlib.sha256(l.encode('utf-8')).hexdigest()}  {r['primary_key'][:16]}"
                     for l, r in zip(out_jsonl.read_text(encoding="utf-8").splitlines(), records))
    (out_dir / "SHA256SUMS").write_text(sums + "\n", encoding="utf-8")
    (out_dir / "manual_province.txt").write_text(
        "\n".join(f"{r['case_no']}\t{r['court']}" for r in records if not r["province"]) or "", encoding="utf-8")

    for r in records:
        manifest_add({
            "channel": "C",
            "source_type": r["doc_type"],
            "source_url_or_ref": r["source_ref"],
            "region": r["province"],
            "behavior_date": "",
            "decision_date": r["judgment_date"],
            "law_version": "",
            "title": r["case_name"],
            "sha256": hashlib.sha256(r["text_full"].encode("utf-8")).hexdigest(),
            "harvest_by": "ingest_wenshu",
            "status": "待筛选",
            "notes": f"第三方采购批次 {batch}；来源：中国裁判文书网（第三方转售，合规确认见 wenshu-retrieval-plan §5）",
        })
    report(f"已入库 {len(records)} 件 → {out_jsonl}（manifest channel=C，主键去重）")


if __name__ == "__main__":
    main()
