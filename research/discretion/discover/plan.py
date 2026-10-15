"""发现层 L1 查询规划器：模板 → 种子查询 → 饱和拆分（设计 §3.1–3.2）。

一个查询由「模板 + 三个拆分维度（区域 / 时间窗 / 特征词）」唯一确定。种子查询只固定模板
（可选固定区域）；执行器发现结果顶到 top_k 时调用 split()，按 queries.yaml 的 split.order
（默认 特征词 → 时间窗 → 省名）固定下一个尚未固定的维度。带 recency 的模板（如新法近一年）不做时间拆分。
M1 实测：省名写进检索式会漏掉正文不写省名的县级文书，所以省名放在最后。

用法（查看将要发出的种子查询，不调用 API）：
  python research/discretion/discover/plan.py --templates fy70,cf82 --regions 浙江,河北
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
QUERIES_YAML = HERE / "queries.yaml"


def load_config(path: Path = QUERIES_YAML) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["_templates"] = {t["id"]: t for t in cfg["templates"]}
    return cfg


@dataclass(frozen=True)
class Query:
    template: str
    region: str | None = None
    window: str | None = None
    feature: str | None = None
    depth: int = 0
    site: str | None = None      # 逐站精扫：行内 site:<县级主域名>（M0 T9：含子域），替代 site:gov.cn
    recency: str | None = None   # 覆盖模板的 recency（每周增量用 week）

    @property
    def qid(self) -> str:
        base = f"{self.template}|r={self.region or '*'}|t={self.window or '*'}|f={self.feature or '*'}"
        return base + (f"|s={self.site}" if self.site else "") + (f"|rc={self.recency}" if self.recency else "")

    def effective_recency(self, cfg: dict) -> str | None:
        return self.recency or cfg["_templates"][self.template].get("recency")

    def text(self, cfg: dict) -> str:
        t = cfg["_templates"][self.template]
        words = [*t["terms"], self.feature, self.region]
        return " ".join(w for w in words if w) + f" site:{self.site or cfg['api']['site_suffix']}"

    def body(self, cfg: dict) -> dict:
        body: dict = {
            "messages": [{"role": "user", "content": self.text(cfg)}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": cfg["api"]["top_k"]}],
        }
        if self.effective_recency(cfg):
            body["search_recency_filter"] = self.effective_recency(cfg)
        if self.window:
            body["search_filter"] = {"range": {"page_time": dict(cfg["split"]["windows"][self.window])}}
        return body


def body_key(body: dict) -> str:
    """缓存键：请求体规范化（键排序、紧凑分隔）后的 SHA-256。"""
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def seeds(cfg: dict, templates: list[str] | None = None, regions: list[str] | None = None) -> list[Query]:
    ids = templates or [i for i, t in cfg["_templates"].items() if not t.get("sweep")]
    unknown = [i for i in ids if i not in cfg["_templates"]]
    if unknown:
        raise ValueError(f"未知模板：{unknown}（见 queries.yaml）")
    bad = [r for r in regions or [] if r not in cfg["split"]["regions"]]
    if bad:
        raise ValueError(f"未知区域：{bad}（只接受 queries.yaml split.regions 中的省级名称）")
    return [Query(t, region=r) for t in ids for r in (regions or [None])]


DIM_FIELD = {"regions": "region", "windows": "window", "features": "feature"}


def split(q: Query, cfg: dict) -> list[Query]:
    """按 queries.yaml split.order 固定下一个未固定的维度；全部固定后返回空（叶子，再满也不拆）。
    带 recency 的模板跳过时间窗（recency 与 page_time 不叠加）。"""
    if q.site:
        return []  # 逐站查询顶到 50 条不再拆分，交给 L4 整栏收割（设计 §3.2 第 5 步）
    sp = cfg["split"]
    child = replace(q, depth=q.depth + 1)
    for dim in sp.get("order", ["features", "windows", "regions"]):
        field = DIM_FIELD[dim]
        if dim == "windows" and q.effective_recency(cfg):
            continue
        if getattr(q, field) is None:
            return [replace(child, **{field: v}) for v in sp[dim]]
    return []


def seeds_incremental(cfg: dict, recency: str = "week") -> list[Query]:
    """每周增量：所有常规模板改用 recency=week（设计 §3.3 增量模式）。"""
    return [Query(t, recency=recency) for t, tpl in cfg["_templates"].items() if not tpl.get("sweep")]


def seeds_sweep(cfg: dict, sites: list[str]) -> list[Query]:
    """逐站精扫：每个县级主域名配每个 sweep 模板各一条（设计 §3.2 第二段）。"""
    sw = [t for t, tpl in cfg["_templates"].items() if tpl.get("sweep")]
    return [Query(t, site=s) for s in sites for t in sw]


def main() -> None:
    ap = argparse.ArgumentParser(description="列出种子查询（不调用 API）")
    ap.add_argument("--templates", default="", help="逗号分隔的模板 id，默认全部")
    ap.add_argument("--regions", default="", help="逗号分隔的省级名称，默认不限区域（全国）")
    args = ap.parse_args()
    cfg = load_config()
    qs = seeds(cfg, [t for t in args.templates.split(",") if t] or None, [r for r in args.regions.split(",") if r] or None)
    for q in qs:
        print(f"{q.qid}\t{q.text(cfg)}\t{body_key(q.body(cfg))[:12]}")
    print(f"共 {len(qs)} 条种子查询")


if __name__ == "__main__":
    main()
