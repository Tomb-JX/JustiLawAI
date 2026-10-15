"""目标省定向扩面（设计 §2.5）：用地级市名替代省名分片搜索，补进域名库，只精扫归属目标省的县，输出各省覆盖前后对比。

流程（复用 weekly.weekly 的整条流水线，批次前缀 targeted）：
  扩面前快照 → 地级市 × {处罚决定书, 复议决定书} 搜索（顶格按特征词拆一层）→ 分诊 → 精扫目标省的县
  → 再分诊 → 新富矿主机栏目扩展 → 增量交付（urls_new / columns_new 当天累加）→ 扩面后快照与对比表
省份归属见 coverage.py（地级市全称 + 省名投票）。

用法（仓库根目录；需 QIANFAN_API_KEY）：
  python research/discretion/discover/targeted.py                       # 全部目标省
  python research/discretion/discover/targeted.py --provinces 山西,上海  # 指定省
产出：交付目录 targeted_coverage.md（对比表）、targeted_report.md；本目录 coverage.csv 追加扩面前后两组计数。
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from coverage import attribute_sites, save, snapshot, table
from plan import load_config, seeds_targeted
from search import Client, api_key, data_root
from triage import merge_hits
from weekly import read_csv, weekly


class TargetSiteFilter:
    """精扫选站：只要归属目标省的县。第一次被调用时（流水线已完成第一轮分诊）按最新交付计算归属。"""

    def __init__(self, root: Path, cfg: dict, provinces: list[str]):
        self.root, self.cfg, self.provinces = root, cfg, set(provinces)
        self._prov: dict[str, str] | None = None

    def __call__(self, site: str) -> bool:
        if self._prov is None:
            out = sorted(p for p in (self.root / "out").iterdir() if (p / "urls.tsv").exists())[-1]
            rows = read_csv(out / "urls.tsv", delimiter="\t")
            hits = {h["url"]: h for h in merge_hits(self.root / "runs")}
            self._prov = attribute_sites(rows, hits, self.cfg)
        return self._prov.get(site) in self.provinces


def main() -> None:
    ap = argparse.ArgumentParser(description="目标省定向扩面")
    ap.add_argument("--provinces", default="", help="逗号分隔；默认 queries.yaml targets 里的全部省")
    ap.add_argument("--search-budget", type=int, default=240, help="定向搜索最多调用次数（168 条种子 + 顶格拆分）")
    ap.add_argument("--sweep-budget", type=int, default=150, help="目标省逐站精扫最多调用次数")
    ap.add_argument("--max-sites", type=int, default=150)
    ap.add_argument("--daily-cap", type=int, default=700, help="当日累计调用上限（本次扩面专门放宽）")
    ap.add_argument("--expand-min-target", type=int, default=3)
    args = ap.parse_args()

    cfg = load_config()
    provinces = [p for p in args.provinces.split(",") if p] or list(cfg["targets"])
    key = api_key()
    if not key:
        raise SystemExit("缺少 QIANFAN_API_KEY")
    root = data_root()
    before = snapshot(root, cfg)
    result = weekly(root=root, client=Client(key), search_budget=args.search_budget, sweep_budget=args.sweep_budget,
                    max_sites=args.max_sites, daily_cap=args.daily_cap, expand_min_target=args.expand_min_target,
                    resweep_days=28, today=date.today(), weekly_log=None,
                    search_queries=seeds_targeted(cfg, provinces),
                    site_filter=TargetSiteFilter(root, cfg, provinces), prefix="targeted")
    after = snapshot(root, cfg)
    others = sorted((p for p in after if p not in provinces), key=lambda p: -after[p].get("docs", 0))
    md = [f"# 目标省定向扩面 {date.today().isoformat()}", "",
          f"搜索 {result['inc_calls']} 次、精扫 {result['sweep_calls']} 次（约 ¥{result['est_cost_cny']}），"
          f"精扫 {result['sites_swept']} 个县、顶格 {result['sites_saturated']} 个，新扩展主机 {result['hosts_expanded']} 个。", "",
          "## 目标省（扩面前 → 扩面后）", "", table(after, provinces, before), "",
          "## 其他省（扩面后）", "", table(after, others)]
    Path(result["out_dir"], "targeted_coverage.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    today = date.today().isoformat()
    save(before, f"{today} 扩面前")
    save(after, f"{today} 扩面后")
    print("\n".join(md))


if __name__ == "__main__":
    main()
