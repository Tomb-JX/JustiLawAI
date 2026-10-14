"""渠道 D：从本地 CAIL2018 压缩包抽取赌博子集（门禁锚点 A2 / G1.1）。

协议（sota-baselines-and-gates.md §4-A2）：
  只用 exercise_contest 与 final_test 子集；
  去掉死刑、无期和零刑期；去掉多罪名、多法条案件；
  罪名只留 赌博 / 开设赌场（数据中罪名形如 "盗窃"，不带"罪"字）。

用法（任意目录）：
  python fetch_cail.py                     # 在 research/data/raw/ 下找 CAIL2018*.zip
  python fetch_cail.py --zip 其他路径.zip
产出：
  research/data/cail/extracted/            解压出的原始 JSON（不入库）
  research/data/cail/gambling/<split>.jsonl  过滤后的子集（不入库）
  research/data/cail/stats.md              数量统计
同时把压缩包登记进 manifest.csv。
"""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter
from pathlib import Path

from common import DATA_DIR, RAW_DIR, manifest_add, manifest_load, report, sha256_path

CAIL_DIR = DATA_DIR / "cail"
EXTRACT_DIR = CAIL_DIR / "extracted"
OUT_DIR = CAIL_DIR / "gambling"

# 只解压协议需要的成员（first_stage 与 restData 不在 A2 协议内）
MEMBERS = [
    "final_all_data/exercise_contest/data_train.json",
    "final_all_data/exercise_contest/data_valid.json",
    "final_all_data/exercise_contest/data_test.json",
    "final_all_data/final_test.json",
]

GAMBLING_CHARGES = {"赌博", "开设赌场"}  # 归一化后比较：strip 末尾"罪"


def norm_charge(name: str) -> str:
    return name.strip().removesuffix("罪")


def find_zip(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.exists():
            raise SystemExit(f"找不到压缩包：{p}")
        return p
    hits = sorted(RAW_DIR.glob("CAIL2018*.zip"))
    if not hits:
        raise SystemExit(f"research/data/raw/ 下没有 CAIL2018*.zip，请用 --zip 指定")
    return hits[0]


def extract(zip_path: Path) -> list[Path]:
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for m in MEMBERS:
            if m not in names:
                report(f"  警告：包内缺少 {m}，跳过")
                continue
            dest = EXTRACT_DIR / Path(m).name
            if not dest.exists():
                report(f"  解压 {m} ...")
                dest.write_bytes(z.read(m))
            out.append(dest)
    return out


def keep(doc: dict) -> bool:
    meta = doc["meta"]
    if len(meta["accusation"]) != 1 or len(meta["relevant_articles"]) != 1:
        return False
    if norm_charge(meta["accusation"][0]) not in GAMBLING_CHARGES:
        return False
    term = meta["term_of_imprisonment"]
    if term["death_penalty"] or term["life_imprisonment"] or term["imprisonment"] <= 0:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=None)
    args = ap.parse_args()

    zip_path = find_zip(args.zip)
    report(f"压缩包：{zip_path}")
    rows = manifest_load()
    if not any(r["source_url_or_ref"].endswith("china-ai-law-challenge/CAIL2018") for r in rows):
        manifest_add(
            {
                "channel": "D",
                "source_type": "数据集",
                "source_url_or_ref": "https://github.com/china-ai-law-challenge/CAIL2018",
                "title": f"CAIL2018 全量数据（本地压缩包 {zip_path.name}）",
                "sha256": sha256_path(zip_path),
                "status": "纳入",
                "notes": "A2 协议子集抽取见 research/data/cail/stats.md",
            }
        )

    paths = extract(zip_path)
    SPLIT_NAME = {
        "data_train.json": "train",
        "data_valid.json": "valid",
        "data_test.json": "test",
        "final_test.json": "final_test",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stats_lines = ["# CAIL2018 赌博子集抽取统计（A2 协议）", ""]
    total_kept = 0
    charge_counter: Counter[str] = Counter()
    term_counter: Counter[str] = Counter()

    for src in paths:
        split = SPLIT_NAME[src.name]
        n_all = n_kept = 0
        dest = OUT_DIR / f"{split}.jsonl"
        with open(src, encoding="utf-8") as fin, open(dest, "w", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                n_all += 1
                doc = json.loads(line)
                if not keep(doc):
                    continue
                n_kept += 1
                total_kept += 1
                charge_counter[doc["meta"]["accusation"][0]] += 1
                months = doc["meta"]["term_of_imprisonment"]["imprisonment"]
                term_counter["≤6月" if months <= 6 else "1-3年" if months <= 36 else "3-5年" if months <= 60 else ">5年"] += 1
                fout.write(line + "\n")  # strip 已去掉换行，不补则整文件挤成一行、非合法 JSONL
        stats_lines += [f"- **{split}**：全量 {n_all:,} → 赌博子集 {n_kept:,}"]
        report(f"  {split}: {n_all:,} -> {n_kept:,}")

    stats_lines += [
        "",
        f"- 合计保留 **{total_kept:,}** 件",
        "- 罪名分布：" + "，".join(f"{k} {v:,}" for k, v in charge_counter.most_common()),
        "- 刑期分布：" + "，".join(f"{k} {v:,}" for k, v in sorted(term_counter.items())),
        "",
        "> 抽取时间见 manifest.csv；10 个刑期区间的 PLJP meta 定义在 P3 前补充（门禁 A2 评测时使用）。",
    ]
    (CAIL_DIR / "stats.md").write_text("\n".join(stats_lines), encoding="utf-8")
    report(f"\n完成：保留 {total_kept:,} 件 → {OUT_DIR}（统计见 {CAIL_DIR / 'stats.md'}）")


if __name__ == "__main__":
    main()
