"""发现层覆盖统计：把每个县级站点归到省份，按省汇总可交付文书、精扫与可收割栏目（设计 §2.5）。

省份归属是按站点投票（站点 = 县级主域名，见 weekly.registrable_site）：
  定向查询命中（查询里写的地级市）   权重 3
  发布单位 / 标题里出现地级市或省名   权重 3
  摘录前 400 字里出现地级市或省名     权重 1（户籍地址等会带来别省地名，所以权重低）
地级市名只认 queries.yaml targets 里的目标省全称；其他省只能靠省名识别，识别不了的记"未识别"。

用法（仓库根目录）：python research/discretion/discover/coverage.py
产出：打印各省覆盖表；--save 时追加到本目录 coverage.csv（入库，只含计数）
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from plan import load_config
from search import data_root
from triage import clean, merge_hits
from weekly import read_csv, registrable_site

HERE = Path(__file__).resolve().parent
COVERAGE_CSV = HERE / "coverage.csv"
PROVINCES = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建",
             "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏",
             "陕西", "甘肃", "青海", "宁夏", "新疆"]
FIELDS = ["as_of", "province", "sites", "docs", "decisions", "reviews", "y2026", "law82", "sites_swept",
          "sites_saturated", "columns_ok", "columns_ok_items"]


def place_index(cfg: dict) -> list[tuple[str, str]]:
    """(地名, 省) 列表：目标省地级市全称 + 31 个省级简称（"内蒙古""黑龙江"在前，避免被短名截胡）。"""
    idx = [(c, p) for p, cs in cfg.get("targets", {}).items() for c in cs]
    idx += [(p, p) for p in sorted(PROVINCES, key=len, reverse=True)]
    return idx


def query_city(query_id: str) -> str:
    part = [x for x in query_id.split("|") if x.startswith("r=")]
    return part[0][2:] if part else ""


def attribute_sites(rows: list[dict], hits: dict[str, dict], cfg: dict) -> dict[str, str]:
    idx = place_index(cfg)
    city_prov = {c: p for p, cs in cfg.get("targets", {}).items() for c in cs}
    votes: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        site = registrable_site(r.get("host", "")) or r.get("host", "")
        head = (r.get("publisher") or "") + (r.get("title") or "")
        body = clean(hits.get(r["url"], {}).get("content", ""))[:400]
        city = query_city(r.get("query_id", ""))
        # 查询里写了地级市 ≠ 结果就在该市：搜索端会把别处文书也返回（M5 实测"宝山区"查询带回河北定兴、浙江武义）。
        # 只有文书本身也出现该地名时，查询地名才计票
        if city in city_prov and (city in head or city in body):
            votes[site][city_prov[city]] += 3
        for name, prov in idx:
            if name in head:
                votes[site][prov] += 3
            if name in body:
                votes[site][prov] += 1
    return {s: (v.most_common(1)[0][0] if v else "未识别") for s, v in votes.items()} | {
        (registrable_site(r.get("host", "")) or r.get("host", "")): "未识别"
        for r in rows if (registrable_site(r.get("host", "")) or r.get("host", "")) not in votes}


def summarize(rows: list[dict], site_prov: dict[str, str], sweep_state: dict, columns: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: Counter())
    sites: dict[str, set] = defaultdict(set)
    for r in rows:
        site = registrable_site(r.get("host", "")) or r.get("host", "")
        p = site_prov.get(site, "未识别")
        sites[p].add(site)
        c = out[p]
        c["docs"] += 1
        c["decisions"] += r.get("doc_type") in ("处罚决定", "处罚汇总", "执法结果表", "不予处罚")
        c["reviews"] += r.get("doc_type") == "复议"
        c["y2026"] += (r.get("year") or "") >= "2026"
        c["law82"] += "82" in (r.get("law_article") or "")
    for p, ss in sites.items():
        out[p]["sites"] = len(ss)
        out[p]["sites_swept"] = sum(s in sweep_state for s in ss)
        out[p]["sites_saturated"] = sum(bool(sweep_state.get(s, {}).get("saturated")) for s in ss)
    for col in columns:
        site = registrable_site(col.get("domain", "")) or col.get("domain", "")
        if col.get("status") == "ok":
            p = site_prov.get(site, "未识别")
            out[p]["columns_ok"] += 1
            out[p]["columns_ok_items"] += int(col.get("est_items") or 0)
    return {p: dict(c) for p, c in out.items()}


def snapshot(root: Path, cfg: dict) -> dict[str, dict]:
    outs = sorted(p for p in (root / "out").iterdir() if (p / "urls.tsv").exists())
    if not outs:
        return {}
    out_dir = outs[-1]
    rows = read_csv(out_dir / "urls.tsv", delimiter="\t")
    hits = {h["url"]: h for h in merge_hits(root / "runs")}
    site_prov = attribute_sites(rows, hits, cfg)
    sweep_state = json.loads((root / "state" / "sweep_state.json").read_text(encoding="utf-8")) \
        if (root / "state" / "sweep_state.json").exists() else {}
    master = root / "state" / "columns_master.csv"
    columns = read_csv(master) if master.exists() else read_csv(out_dir / "columns.csv")
    return summarize(rows, site_prov, sweep_state, columns)


def table(snap: dict[str, dict], provinces: list[str], before: dict[str, dict] | None = None) -> str:
    cols = [("sites", "站点"), ("docs", "文书"), ("decisions", "处罚类"), ("reviews", "复议"), ("y2026", "2026年"),
            ("law82", "第八十二条"), ("sites_swept", "已精扫"), ("columns_ok", "可收割栏目"), ("columns_ok_items", "栏目估算条目")]
    head = "| 省 | " + " | ".join(n for _, n in cols) + " |"
    lines = [head, "|---" * (len(cols) + 1) + "|"]
    for p in provinces:
        a = snap.get(p, {})
        if before is None:
            cells = [str(a.get(k, 0)) for k, _ in cols]
        else:
            b = before.get(p, {})
            cells = [f"{b.get(k, 0)} → **{a.get(k, 0)}**" if a.get(k, 0) != b.get(k, 0) else str(a.get(k, 0)) for k, _ in cols]
        lines.append(f"| {p} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def save(snap: dict[str, dict], as_of: str, path: Path = COVERAGE_CSV) -> None:
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        for p, c in sorted(snap.items(), key=lambda kv: -kv[1].get("docs", 0)):
            w.writerow({"as_of": as_of, "province": p, **{k: c.get(k, 0) for k in FIELDS[2:]}})


def main() -> None:
    ap = argparse.ArgumentParser(description="按省统计发现层覆盖")
    ap.add_argument("--save", action="store_true", help="追加到 coverage.csv")
    args = ap.parse_args()
    cfg = load_config()
    snap = snapshot(data_root(), cfg)
    order = list(cfg.get("targets", {})) + [p for p, _ in sorted(snap.items(), key=lambda kv: -kv[1].get("docs", 0))
                                            if p not in cfg.get("targets", {})]
    print(table(snap, order))
    if args.save:
        save(snap, date.today().isoformat())


if __name__ == "__main__":
    main()
