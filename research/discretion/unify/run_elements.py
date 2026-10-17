"""I-20 要素教师标注管线（网页侧接管线，契约=引擎 element_labels element-v1）。

流程：seg-v2 批次（final300）句表 → 每记录取 facts 句 + facts 前 meta 句（**原文切片**，
经 edits 日志映射回 text_full——引文天然在原文空间，S2 定位=find+唯一性校验）；
A/B 双盲（A=deepseek-flash，B=xiaomi/mimo-v2.6-flash，D-002：A/B 至多一个与教师同厂）；
字段级分歧 → C 仲裁（mimo-v2.6-pro，非 deepseek）；
labels.jsonl 证据 {quote,start,end} 满足 text_full[start:end]==quote；
验收交引擎 accept_element_labels.py（门槛：结构/哈希 100%、坐标逐字 ≥95%、A/B 配对、分歧 ≤20%）。

用法（仓库根目录）：
  python research/discretion/unify/run_elements.py --run <s1_runs/final300> \
      [--limit N] [--smoke]
产物（s1_runs/<run>/elements/）：A.jsonl、B.jsonl、diffs.jsonl、adjudications.jsonl、
labels.jsonl、queue_manual.csv、progress.json（心跳）、receipts.jsonl、summary.json。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "discover"))

from s1 import Provider, load_config, extract_json, data_root  # noqa: E402
from locate import OffsetIndex  # noqa: E402
from progress import ProgressTracker, load_prices, classify_error  # noqa: E402

ENGINE_API = Path(os.environ.get("JUSTILAW_ENGINE_API")
                  or r"D:\02_Dev\Projects\大创\.claude\worktrees\discretion-engine\justilaw-api")
if not (ENGINE_API / "app" / "discretion" / "element_labels.py").exists():
    sys.exit(f"[停止] 引擎契约不可达：{ENGINE_API}（设 JUSTILAW_ENGINE_API 环境变量）")
sys.path.insert(0, str(ENGINE_API))
from app.discretion.element_labels import (  # noqa: E402
    PROMPT_VERSION, FIELD_INFO, teacher_messages, validate_teacher_output)

LABEL_PROV = "model-adjudicated"
GROUPS_ORDER = ["conduct", "amounts", "persons", "venue", "intent", "circumstances", "person"]


# ---------- 输入构造（原文空间句表） ----------

def build_inputs(rec: dict, seg_out: dict, index: OffsetIndex) -> dict | None:
    """facts_text=facts 区间句原文拼接；meta_text=facts 前 meta 句；两者空返回 None（人工分流）。
    target 缺失也返回 None（教师拒绝匿名标注）。"""
    sm = (rec.get("subject_mention") or "").strip()
    zones = (seg_out.get("zones") if seg_out else None) or rec.get("zones_det") or []
    if not zones:
        return None
    sents = rec.get("sentences") or []
    if not sm or not zones or not sents:
        return None
    facts_ids, meta_ids, first_f = [], [], None
    for z in zones:
        for s in range(z["from"], z["to"] + 1):
            if z["type"] == "facts":
                facts_ids.append(s)
                if first_f is None:
                    first_f = s
            elif z["type"] == "meta":
                meta_ids.append(s)
    meta_pre = [s for s in meta_ids if first_f is None or s < first_f]
    parts = {1: [], 2: []}
    for group, ids in ((1, facts_ids), (2, meta_pre)):
        for s in ids:
            cs, ce = sents[s - 1]
            try:
                os_, oe = index.span(cs, ce - 1) if ce - 1 >= cs else (cs, cs + 1)
            except IndexError:
                continue
            parts[group].append((cs, oe if ce - 1 >= cs else cs + 1))
    text_full = rec.get("_text_full") or ""

    def join_orig(items):
        out = []
        for cs, oe in items:
            a = index.origs[cs] if cs < len(index.origs) else None
            b = index.origs[oe - 1] if oe - 1 < len(index.origs) else None
            if a is None or b is None:
                continue
            out.append(text_full[a:b + 1])
        return "\n".join(out)

    def orig_regions(items):
        out = []
        for cs, oe in items:
            if cs >= len(index.origs) or oe - 1 >= len(index.origs):
                continue
            out.append((index.origs[cs], index.origs[oe - 1] + 1))
        return out
    regions = orig_regions(parts[1]) + orig_regions(parts[2])
    facts_text = join_orig(parts[1])
    meta_text = join_orig(parts[2])
    if not (facts_text.strip() or meta_text.strip()):
        return None
    aliases = tuple((seg_out or {}).get("subject", {}).get("aliases") or [])
    return {"target": sm, "facts_text": facts_text, "meta_text": meta_text,
            "aliases": aliases, "regions": regions}


# ---------- 定位与合并 ----------

_WS = re.compile(r"\s+")


def locate_evidence(quote: str, text_full: str, regions=()):
    """原文定位：① 逐字命中——多处时用**教师输入句区间消歧**（取首个完整落在
    facts/meta 区间内的出现；区间外仍多义 → 复核）；② 空白归一唯一命中→切片回填。"""
    if not quote:
        return None
    hits = []
    start = text_full.find(quote)
    while start >= 0:
        hits.append((start, start + len(quote)))
        start = text_full.find(quote, start + 1)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1 and regions:
        inside = [h for h in hits if any(a <= h[0] and h[1] <= b + 1 for a, b in regions)]
        if len(inside) == 1:
            return inside[0]
    if hits:
        return None  # 歧义且区间无法消歧 → 复核
    tn = _WS.sub("", text_full)
    qn = _WS.sub("", quote)
    if not qn:
        return None
    n0 = tn.find(qn)
    if n0 < 0 or tn.find(qn, n0 + 1) >= 0:
        return None
    # 归一位置 → 原文位置
    idx, skipped = [], 0
    for i, ch in enumerate(text_full):
        if ch.isspace():
            skipped += 1
            continue
        idx.append(i)
    # 只映射前 len(tn) 个非空白字符；重建原文区间含尾部空白
    a = idx[n0]
    b_last = idx[min(n0 + len(qn), len(tn)) - 1]
    b = b_last + 1
    while b < len(text_full) and text_full[b].isspace():
        b += 1
    return a, b


def merge_labels(a_payload: dict, b_payload: dict, adjud: dict) -> tuple[dict, list[dict]]:
    """字段级合并：A==B（status+value）直采；分歧查 adjudication（C 裁决 A|B|新值|未提及）。
    返回 (merged elements, 未决分歧列表)。"""
    merged, unresolved = {}, []
    diffs = []
    for path in FIELD_INFO:
        g, name = path.split(".")
        va = ((a_payload or {}).get(g) or {}).get(name) or {"status": "未提及", "value": None, "evidence": []}
        vb = ((b_payload or {}).get(g) or {}).get(name) or {"status": "未提及", "value": None, "evidence": []}
        def norm(x):
            y = json.loads(json.dumps(x, ensure_ascii=False))
            for e in (y.get("evidence") or []):
                e.pop("variant", None)
            return json.dumps(y, sort_keys=True, ensure_ascii=False)
        same = (va.get("status") == vb.get("status")
                and norm({"value": va.get("value")}) == norm({"value": vb.get("value")})
                and {frozenset((e.get("start"), e.get("end")) for e in (va.get("evidence") or []) if not e.get("review"))}
                == {frozenset((e.get("start"), e.get("end")) for e in (vb.get("evidence") or []) if not e.get("review"))})
        chosen = None
        if same:
            chosen = json.loads(json.dumps(va, ensure_ascii=False))
            merged.setdefault(g, {})[name] = chosen
            continue
        d = {"path": path, "a": va, "b": vb}
        diffs.append(d)
        adj = adjud.get(path)
        if adj is None:
            unresolved.append(d)
            continue
        pick = adj.get("adopt")
        src = {"A": va, "B": vb}.get(pick)
        if pick == "未提及":
            merged.setdefault(g, {})[name] = {"status": "未提及", "value": None, "evidence": []}
        elif pick == "新值":
            merged.setdefault(g, {})[name] = {"status": adj.get("status") or "推断", "value": adj.get("value"),
                                              "evidence": adj.get("evidence") or (va.get("evidence") or [])[:1]}
        elif src is not None:
            merged.setdefault(g, {})[name] = json.loads(json.dumps(src, ensure_ascii=False))
    return merged, unresolved, diffs


def _candidates(payload: dict, text_full: str, tag: str, regions=()) -> dict:
    """S2 定位在 payload 上：每字段 evidence 逐字/归一定位并回填原文切片；
    定位失败打 review。合并比较与采纳都基于坐标（A/B 同 span 视为一致）。"""
    out = json.loads(json.dumps(payload or {}, ensure_ascii=False))
    for gname, g in (out or {}).items():
        if not isinstance(g, dict):
            continue
        for name, fld in g.items():
            if not isinstance(fld, dict):
                continue
            raw = fld.get("evidence") or []
            if raw and isinstance(raw[0], str):
                raw = [{"quote": q} for q in raw if isinstance(q, str)]
            ev = []
            for e in raw:
                q = e.get("quote", "") if isinstance(e, dict) else str(e)
                got = locate_evidence(q, text_full, regions)
                if got is not None and q in text_full and text_full.find(q) == text_full.rfind(q):
                    ev.append({"quote": q, "start": text_full.find(q), "end": text_full.find(q) + len(q)})
                    continue
                if got is None:
                    ev.append({"quote": q, "review": True})
                else:
                    ev.append({"quote": text_full[got[0]:got[1]], "start": got[0], "end": got[1]})
            fld["evidence"] = ev
    return out


ADJ_PROMPT = """同一案件同一字段两位标注教师给出不同结果，请依原文裁决。
字段：{path}
原文（当事人句+事实句）：
{text}
候选 A：{a}
候选 B：{b}
规则：以原文逐字证据为准；两候选都无据则给新值（附证据）或判"未提及"。
只输出 JSON：{{"adopt":"A|B|未提及|新值","value":<裁决值或null>,"status":"明确|推断",
"evidence":[{{"quote":"逐字引文"}}],"reason":"一句话"}}"""


# ---------- 主流程 ----------

class ElementsRunner:
    def __init__(self, providers: dict, out_dir: Path, total: int):
        self.providers = providers
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        prices = load_prices(data_root() / "config" / "s1_prices.json")
        self.tracker = ProgressTracker(out_dir, total=total, prices=prices,
                                       meta={"prompt_version": PROMPT_VERSION, "stage": "elements"})
        self._rf = open(out_dir / "receipts.jsonl", "a", encoding="utf-8", newline="\n")

    def receipt(self, **kw):
        kw["ts"] = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self._rf.write(json.dumps(kw, ensure_ascii=False) + "\n")
            self._rf.flush()

    def call(self, pname: str, msgs: list[dict], rid: str, tag: str) -> dict | None:
        prov = self.providers[pname]
        try:
            content, meta = prov.chat(msgs[0]["content"], msgs[1]["content"])
            self.tracker.cost.add(prov.model, meta.get("usage") or {})
            self.receipt(event="call", provider=pname, model=prov.model, id=rid, tag=tag,
                         status="ok", **meta)
            # 原始响应即时落盘：任何崩溃后重跑可从 raws.jsonl 恢复该调用结果，付费成果不再消失
            with self.lock:
                with open(self.out_dir / "raws.jsonl", "a", encoding="utf-8", newline="\n") as rf:
                    rf.write(json.dumps({"id": rid, "tag": tag, "provider": pname, "content": content},
                                         ensure_ascii=False) + "\n")
            return extract_json(content)
        except Exception as e:
            self.receipt(event="call", provider=pname, model=prov.model, id=rid, tag=tag,
                         status="fail", error=str(e)[:200], category=classify_error(str(e)))
            return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="seg-v2 正式试点 s1_runs/<id>（提供 zones/target 上下文）")
    ap.add_argument("--unified", default=str(data_root() / "unified_raw/web/20261017-web-r3/records.jsonl"))
    ap.add_argument("--parsed", default=str(data_root() / "parsed/web/20261017-web-r3/records.jsonl"))
    ap.add_argument("--a-provider", default="deepseek")
    ap.add_argument("--b-provider", default="xiaomi")
    ap.add_argument("--c-provider", default="xiaomi-pro")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    providers, _, _ = load_config()
    for p in (a.a_provider, a.b_provider, a.c_provider):
        if p not in providers:
            sys.exit(f"未知提供商 {p}（config 键：{list(providers)}）")
    if a.c_provider == "deepseek" or (a.a_provider == "deepseek" and a.b_provider == "deepseek"):
        sys.exit("D-002 隔离：裁判须非 deepseek 且 A/B 至多一个 deepseek")

    unified = {r["id"]: r for r in (json.loads(l) for l in open(a.unified, encoding="utf-8"))}
    parsed = {r["id"]: r.get("text_full") or "" for r in
              (json.loads(l) for l in open(a.parsed, encoding="utf-8"))}
    edits = {}
    for l in open(Path(a.unified).parent / "edits.rle.jsonl", encoding="utf-8"):
        e = json.loads(l)
        edits[e["id"]] = e
    seg = {}
    for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8"):
        o = json.loads(l)
        if o.get("ok"):
            seg[o["id"]] = o

    ids = [i for i in seg if i in unified and i in edits]
    if a.limit:
        ids = ids[:a.limit]
    ed = Path(a.run) / "elements"
    runner = ElementsRunner(providers, ed, total=len(ids))

    manual, work = [], []
    for rid in ids:
        rec = dict(unified[rid])
        rec["_text_full"] = parsed[rid]
        inp = build_inputs(rec, (seg.get(rid) or {}).get("output"), OffsetIndex(edits[rid]))
        if inp is None:
            manual.append(rid)
        else:
            work.append((rid, rec, inp))
    print(f"教师可标 {len(work)} 件；人工分流（facts/meta 全空或无 target）{len(manual)} 件 → queue_manual.csv")
    with open(ed / "queue_manual.csv", "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("id\n")
        for rid in manual:
            f.write(rid + "\n")

    def _do_record(rid: str, rec: dict, inp: dict) -> dict:
        msgs = teacher_messages(target=inp["target"], facts_text=inp["facts_text"],
                                meta_text=inp["meta_text"], aliases=inp["aliases"])
        text_full = rec["_text_full"]
        ev_text = inp["meta_text"] + "\n" + inp["facts_text"]
        pa = runner.call(a.a_provider, msgs, rid, "A")
        pb = runner.call(a.b_provider, msgs, rid, "B")
        if pa is None or pb is None:
            # 双盲缺一（提供商判死等）→ 不产空标签；引擎验收要求 A/B 配对，本件进重试队列
            runner.tracker.finish_record(False, 1, "single-blind",
                                         error="missing_" + ("A" if pa is None else "B"))
            return None, None, None, None
        ia = validate_teacher_output(pa, evidence_text=ev_text)
        ib = validate_teacher_output(pb, evidence_text=ev_text)
        merged = unresolved = diffs = None
        adjud = {}
        if pa and pb:
            regions = inp.get("regions") or ()
            ca = _candidates(pa, text_full, "A", regions)
            cb = _candidates(pb, text_full, "B", regions)
            merged, unresolved, diffs = merge_labels(ca, cb, {})

            if unresolved:
                for d in unresolved:
                    try:
                        content, meta = providers[a.c_provider].chat(
                            "只输出一个 JSON 对象。",
                            ADJ_PROMPT.format(path=d["path"], text=ev_text[:4000],
                                              a=json.dumps(d["a"], ensure_ascii=False),
                                              b=json.dumps(d["b"], ensure_ascii=False)))
                        adjud[d["path"]] = extract_json(content)
                        runner.tracker.cost.add(providers[a.c_provider].model, meta.get("usage") or {})
                        runner.receipt(event="call", provider=a.c_provider,
                                       model=providers[a.c_provider].model, id=rid, tag="C",
                                       status="ok", **meta)
                    except Exception as e:
                        runner.receipt(event="call", provider=a.c_provider, id=rid, tag="C",
                                       status="fail", error=str(e)[:200],
                                       category=classify_error(str(e)))
                        continue   # 仲裁失败→字段保持 unresolved，进复核不炸批
                merged, unresolved2, diffs = merge_labels(ca, cb, adjud)
                unresolved = unresolved2
        # S2 定位：candidates 已带坐标；merged 若含新值/未提及分支再补定位
        loc_fail = sum(1 for g in (merged or {}).values() for fld in g.values()
                       for e in (fld.get("evidence") or []) if e.get("review"))
        line = {"id": rid,
                "input": {"target": inp["target"], "facts_text": inp["facts_text"],
                          "meta_text": inp["meta_text"], "text_full": text_full,
                          "text_orig_sha256": rec["text_orig_sha256"]},
                "elements": merged, "element_schema_version": "1.1.0",
                "element_prompt_version": PROMPT_VERSION, "label_provenance": LABEL_PROV,
                "human_review": False,
                "_diag": {"a_issues": [str(i) for i in (ia or [])], "b_issues": [str(i) for i in (ib or [])],
                          "n_diffs": len(diffs or []), "n_unresolved": len(unresolved or []),
                          "loc_fail": loc_fail,
                          "n_evidence": sum(len(f.get("evidence") or []) for g in (merged or {}).values() for f in g.values())}}
        runner.tracker.finish_record(bool(merged), 1, "ab")
        return line, pa, pb, diffs

    def do_record(rid, rec, inp):
        try:
            return _do_record(rid, rec, inp)
        except Exception as e:
            runner.tracker.finish_record(False, 0, "crash", error=str(e)[:150])
            return {"id": rid, "_crash": str(e)[:150]}, None, None, None

    # 断点缓存：labels 已有有效行的 id 跳过（停止/崩溃后重跑不重复付费）
    for name in ("labels.jsonl", "A.jsonl", "B.jsonl", "diffs.jsonl"):
        if not (ed / name).exists():
            (ed / name).write_text("", encoding="utf-8", newline="\n")
    done_ids = set()
    for l in open(ed / "labels.jsonl", encoding="utf-8"):
        try:
            done_ids.add(json.loads(l)["id"])
        except Exception:
            pass
    work = [w for w in work if w[0] not in done_ids]
    print(f"断点缓存命中 {len(done_ids)} 件，本次待标 {len(work)} 件")

    results = []
    files = {n: open(ed / n, "a", encoding="utf-8", newline="\n")
             for n in ("labels.jsonl", "A.jsonl", "B.jsonl", "diffs.jsonl")}

    def _w(name, row):
        with runner.lock:
            files[name].write(json.dumps(row, ensure_ascii=False) + "\n")
            files[name].flush()

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(do_record, *w) for w in work]
        for i, fut in enumerate(as_completed(futs), 1):
            line, pa, pb, diffs = fut.result()
            if line is None:
                continue
            if line.get("_crash"):
                print(f"  [崩] {line['id']}: {line['_crash'][:70]}")
                continue
            results.append(line)
            _w("labels.jsonl", {k: v for k, v in line.items() if k != "_diag"})
            _w("A.jsonl", {"id": line["id"], "elements": pa})
            _w("B.jsonl", {"id": line["id"], "elements": pb})
            for d in (diffs or []):
                _w("diffs.jsonl", {"id": line["id"], **d})
            if i % 20 == 0 or i == len(work):
                print(f"  {i}/{len(work)}")
    for fh in files.values():
        fh.close()
    retry_ids = sorted({w[0] for w in work} - {r["id"] for r in results})
    with open(ed / "queue_retry.csv", "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("id\n")
        for rid in retry_ids:
            f.write(rid + "\n")
    n = len(results)
    summary = {
        "stage": PROMPT_VERSION, "n": n, "manual": len(manual),
        "records_with_ab": sum(1 for r in results if r.get("elements")),
        "fields_diff": sum(r["_diag"]["n_diffs"] for r in results),
        "unresolved": sum(r["_diag"]["n_unresolved"] for r in results),
        "evidence_total": sum(r["_diag"].get("n_evidence", 0) for r in results),
        "evidence_loc_fail": sum(r["_diag"]["loc_fail"] for r in results),
        "single_blind_or_crash_skipped": len(retry_ids),
        "cost": runner.tracker.cost.total(),
    }
    (ed / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                     encoding="utf-8", newline="\n")
    runner.tracker.set_phase("done")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
