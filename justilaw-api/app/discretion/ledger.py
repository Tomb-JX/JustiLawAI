"""规范逐条台账（ADR-010 决定 4；流程见 docs/06-algorithm/ledger-process.md）。

台账把一部规范的完整原文切成条目，每条写明处置：
  encoded        已编成规则：refs 指向规则（省级 YAML 路径 rules.… / 代码 code:模块.函数）
  element        交给要素定义：refs 指向要素字段（field:组.字段），由标注指南与抽取提示承接
  gap            已识别、尚未处理：note 写缺口与跟进编号（如 Q-21）
  manual         需人工判断，引擎只提示：note 写原因（如"其他情节严重的情形"）
  not_applicable 与裁量结论无关（程序、收缴、执行等）：note 写理由
  context        非规范性文字（标题、发文语、日期、章节名）
切分是确定性的（segment）：台账条目的 path 与 text 必须与对原文重新切分的结果逐条一致，
拼起来与原文（去空白后）完全相同——原文改了、条目漏了、文字被改写，测试都会失败。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .norm_store import NORMS_DIR

LEDGER_DIR = NORMS_DIR / "ledgers"
SEGMENTER_VERSION = "ledger-seg-v1"
DISPOSITIONS = {"encoded", "element", "gap", "manual", "not_applicable", "context"}
NEEDS_REFS = {"encoded", "element"}
NEEDS_NOTE = {"gap", "manual", "not_applicable"}

CN = "一二三四五六七八九十"
_TOP = re.compile(rf"(?m)^([{CN}]+)、")                         # 一、二、……（行首）
_MID = re.compile(rf"(?<!第)（([{CN}]+)）")                       # （一）……；"第（二）项"中的不是条目
_LOW = re.compile(r"(?<![\d０-９])(\d{1,2})．")                   # 1．2．（全角点）


@dataclass
class Segment:
    path: str
    text: str


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def segment(text: str) -> list[Segment]:
    """按 一、/（一）/1． 三级标记切分；第一个"一、"之前按行切（标题、发文语、日期、立法目的）。"""
    marks = []
    for rx, level in ((_TOP, 1), (_MID, 2), (_LOW, 3)):
        marks += [(m.start(), level, m.group(1)) for m in rx.finditer(text)]
    marks.sort()
    first = marks[0][0] if marks else len(text)
    out, n = [], 0
    for line in text[:first].split("\n"):
        if line.strip():
            n += 1
            out.append(Segment(f"前言.{n}", line.strip()))
    top = mid = None
    for i, (pos, level, num) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if level == 1:
            top, mid = num, None
            path = top
        elif level == 2:
            mid = num
            path = f"{top}.（{mid}）"
        else:
            path = f"{top}.（{mid}）.{num}" if mid else f"{top}.{num}"
        body = text[pos:end].strip()
        # 同一级下无标记的续段（如"二、"下的第二段）按行再切，保证一条一事
        parts = [p.strip() for p in body.split("\n") if p.strip()]
        out.append(Segment(path, parts[0]))
        for k, p in enumerate(parts[1:], 2):
            out.append(Segment(f"{path}.段{k}", p))
    return out


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(name: str) -> dict:
    return yaml.safe_load((LEDGER_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def all_ledgers() -> dict[str, dict]:
    return {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(LEDGER_DIR.glob("*.yaml"))}


def _resolve_yaml(doc: dict, dotted: str) -> bool:
    node = doc
    for seg in dotted.split("."):
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        elif isinstance(node, list):
            hit = [x for x in node if isinstance(x, dict) and seg in (x.get("field"), x.get("when"), x.get("id"))]
            if not hit:
                return False
            node = hit[0]
        else:
            return False
    return True


def check(ledger: dict, source_text: str, province_doc: dict | None, fields: set[str]) -> list[str]:
    """返回全部问题；空列表 = 台账完整、与原文一致、引用都能解析。"""
    errs = []
    if ledger.get("source_sha256") != text_sha(source_text):
        errs.append("原文哈希与台账不一致：原文变了，须重新切分并复核")
    if ledger.get("segmenter") != SEGMENTER_VERSION:
        errs.append(f"切分器版本应为 {SEGMENTER_VERSION}")
    expect = segment(source_text)
    items = ledger.get("items") or []
    if [(s.path, s.text) for s in expect] != [(i.get("path"), i.get("text")) for i in items]:
        exp, got = {s.path: s.text for s in expect}, {i.get("path"): i.get("text") for i in items}
        errs += [f"缺少条目 {p}" for p in exp if p not in got]
        errs += [f"多出条目 {p}" for p in got if p not in exp]
        errs += [f"条目文字与原文不一致 {p}" for p in exp if p in got and exp[p] != got[p]]
        if not any(e.startswith(("缺少", "多出", "条目文字")) for e in errs):
            errs.append("条目顺序与原文不一致")
    if _squash("".join(s.text for s in expect)) != _squash(source_text):
        errs.append("切分结果拼接后与原文不一致（切分器缺陷）")
    for it in items:
        p, d = it.get("path"), it.get("disposition")
        if d not in DISPOSITIONS:
            errs.append(f"{p}：处置缺失或非法（{d}）")
            continue
        refs = it.get("refs") or []
        if d in NEEDS_REFS and not refs:
            errs.append(f"{p}：{d} 必须给 refs")
        if d in NEEDS_NOTE and not (it.get("note") or "").strip():
            errs.append(f"{p}：{d} 必须写 note")
        for r in refs:
            if r.startswith("field:"):
                if r[6:] not in fields:
                    errs.append(f"{p}：要素字段不存在 {r}")
            elif r.startswith("code:"):
                mod, _, attr = r[5:].partition(".")
                import importlib
                try:
                    if not hasattr(importlib.import_module(f"app.discretion.{mod}"), attr.split(".")[0]):
                        errs.append(f"{p}：代码引用不存在 {r}")
                except ImportError:
                    errs.append(f"{p}：代码模块不存在 {r}")
            elif province_doc is None or not _resolve_yaml(province_doc, r):
                errs.append(f"{p}：规则引用无法解析 {r}")
    return errs


def summary(ledger: dict) -> dict:
    out = {d: 0 for d in sorted(DISPOSITIONS)}
    for it in ledger.get("items") or []:
        out[it.get("disposition")] = out.get(it.get("disposition"), 0) + 1
    return {"items": len(ledger.get("items") or []), **out}


LABEL = {"encoded": "已编码", "element": "交要素定义", "gap": "缺口", "manual": "需人工", "not_applicable": "不适用",
         "context": "非规范文字"}


def to_markdown(ledger: dict) -> str:
    """复核用的可读版本（由 scripts/ledger_report.py 生成，勿手改；以 YAML 为准）。"""
    s = summary(ledger)
    lines = [f"# 逐条台账：{ledger['document']}", "",
             f"> 由 `justilaw-api/scripts/ledger_report.py` 从 `norms/ledgers/{ledger['province']}.yaml` 生成，勿手改。"
             f"状态：{ledger.get('status')}；复核人：{'、'.join(ledger.get('reviewed_by') or []) or '（未复核）'}", "",
             "| " + " | ".join(f"{LABEL[k]} {s[k]}" for k in ("encoded", "element", "gap", "manual", "not_applicable", "context"))
             + f" | 合计 {s['items']} |", "|" + "---|" * 7, "",
             "## 缺口（gap）", "", "| 条目 | 原文 | 缺口与跟进 |", "|---|---|---|"]
    lines += [f"| {i['path']} | {i['text']} | {i.get('note', '')} |" for i in ledger["items"] if i["disposition"] == "gap"]
    lines += ["", "## 全部条目", "", "| 条目 | 处置 | 原文 | 指向 | 说明 |", "|---|---|---|---|---|"]
    lines += [f"| {i['path']} | {LABEL[i['disposition']]} | {i['text']} | {'<br>'.join(i.get('refs') or [])} | {i.get('note', '')} |"
              for i in ledger["items"]]
    return "\n".join(lines) + "\n"
