"""P9 候选池汇总：扫执法检索缓存 → 去已入库 → 元数据质量打分 → 机关簇上限 → 下载清单。

打分（全部来自召回元数据，零下载成本）：
  +3 治安法第70条/第82条 引证（本案定赌）
  +2 处罚种类含"没收违法所得/非法财物"（onsite/收缴信号）
  +2 处罚种类同时含拘留+罚款（拘留并罚——裁量最硬结果）
  +1 有发文案号（非汇总页）
  -3 执法机关为空或"省级"汇总厅（福建 2013 类旧厅件）
机关簇上限：同一 punishOrgan 最多 8 件进清单（防单局批次吞并事件数）。

用法：python -m pkulaw_agent.p9_select [--top 200] [--out inbox/pkulaw/20261026-P9]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from pkulaw_agent.session import data_dir  # noqa: E402


def ingested_urls(data: Path) -> set[str]:
    have = set()
    for f in data.rglob("results.jsonl"):
        if "cache" in str(f):
            continue
        for l in f.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                u = json.loads(l).get("url") or ""
            except Exception:  # noqa: BLE001
                continue
            if u:
                have.add(u.split("#")[0].split("?")[0].rstrip("/"))
    for f in data.rglob("download_list.jsonl"):
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(l).get("url", "")
            except Exception:  # noqa: BLE001
                continue
            if u:
                have.add(u.split("#")[0].split("?")[0].rstrip("/"))
    return have


def norm_url(u: str) -> str:
    return (u or "").split("#")[0].split("?")[0].rstrip("/")


def score(it: dict) -> tuple[int, str]:
    law = " ".join(it.get("accordingLaw") or [])
    ptype = " ".join(it.get("punishmentType") or [])
    organ = it.get("punishOrgan") or ""
    s, why = 0, []
    if re.search(r"第[70]+条|第八十二条|第70条|第八十[一二]条|第82条", law) or "70条" in law or "82条" in law:
        s += 3; why.append("定赌70/82")
    if "没收" in ptype:
        s += 2; why.append("没收")
    if "行政拘留" in ptype and "罚款" in ptype:
        s += 2; why.append("并罚")
    if it.get("documentNo"):
        s += 1; why.append("文号")
    if not organ or it.get("enforcementLevel") == "省级":
        s -= 3; why.append("省级/无机关")
    return s, "+".join(why)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--per-prov", type=int, default=25, help="每省配额上限（分省均衡，防拼音序截断新省）")
    ap.add_argument("--out", default="inbox/pkulaw/20261026-P9")
    ap.add_argument("--cap-per-organ", type=int, default=8)
    args = ap.parse_args()
    data = data_dir()
    have = ingested_urls(data)
    cache = data / "engine" / "pkulaw_mcp" / "cache" / "pkulaw-enforcement-doc_mcp"
    pool: dict[str, dict] = {}
    prov_of_url: dict[str, str] = {}
    for f in cache.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        a = d.get("arguments") or {}
        prov = (a.get("lawRegional") or ["?"])[0]
        for it in (d.get("structured") or {}).get("data") or []:
            u = norm_url(it.get("url", ""))
            if not u or u in have:
                continue
            if u not in pool or (score(it)[0] > score(pool[u])[0]):
                pool[u] = it
                prov_of_url[u] = prov
    scored = []
    for u, it in pool.items():
        s, why = score(it)
        scored.append((s, u, it, prov_of_url[u], why))
    # 分省桶内按分数降序，再跨省轮转取，保证每省都被覆盖（修拼音序截断）
    by_prov: dict[str, list] = defaultdict(list)
    for row in scored:
        by_prov[row[3]].append(row)
    for lst in by_prov.values():
        lst.sort(key=lambda x: -x[0])
    provs = sorted(by_prov, key=lambda p: -by_prov[p][0][0])  # 按各省最高分排序轮转序
    by_organ: dict[str, int] = defaultdict(int)
    per_prov_cnt: dict[str, int] = defaultdict(int)
    ptr = defaultdict(int)
    sel = []
    while len(sel) < args.top and any(ptr[p] < len(by_prov[p]) for p in provs):
        progressed = False
        for p in provs:
            if per_prov_cnt[p] >= args.per_prov:
                continue
            while ptr[p] < len(by_prov[p]):
                s, u, it, prov, why = by_prov[p][ptr[p]]
                ptr[p] += 1
                organ = it.get("punishOrgan") or "?"
                if by_organ[organ] >= args.cap_per_organ:
                    continue
                by_organ[organ] += 1
                per_prov_cnt[p] += 1
                sel.append((s, u, it, prov, why))
                progressed = True
                break
        if not progressed:
            break
    out = data / args.out
    (out / "runs" / "20261026-P9").mkdir(parents=True, exist_ok=True)
    rows = []
    for s, u, it, prov, why in sel:
        rows.append({"gid": f"P9|{norm_url(u).rsplit('/',1)[-1]}", "url": u,
                     "doc_no": it.get("documentNo") or "", "title": it.get("title") or "",
                     "cell_prov": prov, "score": s, "signals": why})
    (out / "download_list.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (out / "runs" / "20261026-P9" / "results.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    provn = defaultdict(int)
    for r in rows:
        provn[r["cell_prov"]] += 1
    print(f"净新增池 {len(pool)} → 入选 {len(sel)}（每省≤{args.per_prov}、机关簇≤{args.cap_per_organ}）")
    print("分省：", dict(sorted(provn.items(), key=lambda x:-x[1])))
    sc = defaultdict(int)
    for r in rows: sc[r["score"]] += 1
    print("分数分布：", dict(sorted(sc.items(), reverse=True)))
    print(f"→ {out/'download_list.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
