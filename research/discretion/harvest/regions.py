"""站点 → 行政区划代码（文本处理规范 docs/04-plan/text-processing-spec.md §2 `region`，规格要求至少到省）。

代码表：data/xzqh_2023.csv，取自民政部《2023 年中华人民共和国县以上行政区划代码》
（https://www.mca.gov.cn/mzsj/xzqh/2023/202301xzqh.html，2026-10-16 抓取解析，3,209 条）。
做法：对每个站点收集发布单位、作出机关、标题（权重 3）与正文前 300 字（权重 1，户籍地址等会带来外地地名，所以权重低），
数县级名称出现次数，上级地级市名出现加 3、省名出现加 2，取最高分。
区县重名（如"新华区"）只有在上级地名能区分时才判到县级；否则退到能确定的最低一级（市或省），method 标 ambiguous。
结果写本目录 regions.csv（入库：只有站点与公开区划信息），人工可在 regions_manual.csv 里覆盖。

用法（仓库根目录）：python research/discretion/harvest/regions.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "discover"))

from search import data_root  # noqa: E402
from weekly import registrable_site  # noqa: E402

TABLE = HERE / "data" / "xzqh_2023.csv"
OUT = HERE / "regions.csv"
MANUAL = HERE / "regions_manual.csv"
FIELDS = ["site", "region_code", "region_name", "level", "province_code", "province", "city_code", "city",
          "score", "method", "cases"]
PROVINCE_SHORT = re.compile(r"(省|市|自治区|壮族自治区|回族自治区|维吾尔自治区|特别行政区)$")


def load_table(path: Path = TABLE) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class Resolver:
    def __init__(self, rows: list[dict]):
        self.by_code = {r["code"]: r for r in rows}
        self.counties = [r for r in rows if r["level"] == "县" and len(r["name"]) >= 2]
        self.cities = [r for r in rows if r["level"] == "市"]
        self.provinces = [r for r in rows if r["level"] == "省"]
        self.short = {r["code"]: PROVINCE_SHORT.sub("", r["name"]) for r in self.provinces}
        name_count = Counter(r["name"] for r in self.counties)
        self.dup = {n for n, c in name_count.items() if c > 1}

    def _occ(self, name: str, texts: list[tuple[str, int]]) -> int:
        return sum(t.count(name) * w for t, w in texts)

    def _parent_bonus(self, r: dict, texts: list[tuple[str, int]]) -> int:
        bonus = 0
        city = self.by_code.get(r["city_code"])
        if city and city["code"] != r["code"] and self._occ(city["name"], texts):
            bonus += 3
        prov = r["province_code"]
        if self._occ(self.by_code[prov]["name"], texts) or self._occ(self.short[prov], texts):
            bonus += 2
        return bonus

    def row(self, r: dict, score: int, method: str) -> dict:
        prov = self.by_code[r["province_code"]]
        city = self.by_code.get(r["city_code"])
        return {"region_code": r["code"], "region_name": r["name"], "level": r["level"],
                "province_code": prov["code"], "province": prov["name"],
                "city_code": city["code"] if city else "", "city": city["name"] if city else "",
                "score": score, "method": method}

    @staticmethod
    def names_of(r: dict) -> list[str]:
        """县名及简称：自治县/自治旗常写作"××县/××旗"（新平彝族傣族自治县 → 新平县）。"""
        names = [r["name"]]
        m = re.fullmatch(r"(.{2}).*自治(县|旗)", r["name"])
        if m:
            names.append(m.group(1) + m.group(2))
        return names

    def resolve(self, texts: list[tuple[str, int]]) -> dict | None:
        found = []
        for r in self.counties:
            occ = max(self._occ(n, texts) for n in self.names_of(r))
            if occ:
                found.append((occ, r))
        # 短名是更长县名的一部分时丢弃短名（"武义县"里含辽宁"义县"、"太康县"里含甘肃"康县"）
        matched = {n for _, r in found for n in self.names_of(r)}
        found = [(o, r) for o, r in found
                 if not any(n != m and n in m for n in self.names_of(r) for m in matched)]
        scored = [(o + self._parent_bonus(r, texts), r) for o, r in found]
        scored.sort(key=lambda x: -x[0])
        if scored:
            best, r = scored[0]
            ties = [x for x in scored if x[0] == best and x[1]["code"] != r["code"]]
            if not ties:
                return self.row(r, best, "county" if r["name"] not in self.dup or best > 3 else "county_dup_name")
            # 同分：若都在同一地级市或同一省，退到该级
            same_city = {x[1]["city_code"] for x in ties} | {r["city_code"]}
            same_prov = {x[1]["province_code"] for x in ties} | {r["province_code"]}
            if len(same_city) == 1 and same_city.pop() in self.by_code:
                return self.row(self.by_code[r["city_code"]], best, "ambiguous_city")
            if len(same_prov) == 1:
                return self.row(self.by_code[r["province_code"]], best, "ambiguous_province")
        for r in self.cities:
            occ = self._occ(r["name"], texts)
            if occ:
                return self.row(r, occ, "city")
        for r in self.provinces:
            if self._occ(r["name"], texts) or self._occ(self.short[r["code"]], texts):
                return self.row(r, 1, "province")
        return None


def site_texts(root: Path) -> dict[str, list[tuple[str, int]]]:
    """每个站点的证据文本：解析结果（发布单位、机关、标题、正文开头）+ 发现层候选（发布单位、标题）。"""
    texts: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for line in (root / "admin" / "web_cases.pre_deid.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        s = c["site"]
        texts[s] += [(c.get("publisher") or "", 3), (c.get("authority") or "", 3), (c.get("title") or "", 3),
                     ((c.get("text_full") or "")[:300], 1)]
    outs = sorted(p for p in (root / "discover" / "out").iterdir() if (p / "candidates.jsonl").exists())
    if outs:
        for line in (outs[-1] / "candidates.jsonl").read_text(encoding="utf-8").splitlines():
            c = json.loads(line)
            s = registrable_site(c.get("host", "")) or c.get("host", "")
            if s in texts:
                texts[s] += [(c.get("publisher") or "", 3), (c.get("title") or "", 3)]
    return texts


def load_regions(path: Path = OUT) -> dict[str, dict]:
    """站点 → 区划行；人工覆盖表优先。"""
    out = {}
    for p in (path, MANUAL):
        if p.exists():
            with open(p, encoding="utf-8", newline="") as f:
                out.update({r["site"]: r for r in csv.DictReader(f)})
    return out


def main() -> None:
    root = data_root().parent
    res = Resolver(load_table())
    texts = site_texts(root)
    cases = Counter(json.loads(l)["site"] for l in (root / "admin" / "web_cases.pre_deid.jsonl").read_text(encoding="utf-8").splitlines())
    rows = []
    for site, tx in sorted(texts.items()):
        r = res.resolve([(t, w) for t, w in tx if t])
        rows.append({"site": site, **(r or {"method": "unresolved", "score": 0}), "cases": cases[site]})
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    m = Counter(r["method"] for r in rows)
    print(f"站点 {len(rows)}：{dict(m)} → {OUT}")


if __name__ == "__main__":
    main()
