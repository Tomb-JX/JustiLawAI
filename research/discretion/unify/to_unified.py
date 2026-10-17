"""unified_raw 落盘转换器（parse-format-chain-design-2026-10-17 v1.2 §5/§8，Q8 决策）。

parsed-1 批次 → unified_raw/<channel>/<batch_id>/：
- records.jsonl   统一原料契约（cleaned_text + form + 元数据信封；只读）
- edits.rle.jsonl 批级区间变换日志（逐记录 deletes/subs，供脱离 S0 环境独立回放）
- stats.json      规则命中/放行分布/form 分布/长度统计

用法（仓库根目录）：
  python research/discretion/unify/to_unified.py <records.jsonl> --channel web --out <dir>
channel 缺省按记录 source 推导（公开网页/复议专栏→web；法宝执法库/法宝案例库→pkulaw）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cleanse import CLEAN_VERSION, CleanResult, cleanse, replay_edits, sentence_table  # noqa: E402
from form import detect_form  # noqa: E402
from prefilter import SAMPLE_TARGET, eval_prefilter, sample_pool  # noqa: E402
from zoning import deterministic_zones, is_public_form  # noqa: E402


def _o2c(res: CleanResult):
    """CleanResult.kept_intervals → orig_span → clean_span 映射函数。"""
    ivs = res.kept_intervals()

    def o2c(span: tuple[int, int]) -> tuple[int, int] | None:
        a, b = span
        cs = ce = None
        for os_, ol, cls_, cl in ivs:
            if os_ <= a < os_ + ol:
                cs = cls_ + (a - os_)
            if os_ <= b - 1 < os_ + ol:
                ce = cls_ + (b - 1 - os_) + 1
        if cs is None or ce is None or ce <= cs:
            return None
        return cs, ce
    return o2c

CHANNEL_BY_SOURCE = {
    "公开网页": "web", "复议专栏": "web",
    "法宝执法库": "pkulaw", "法宝案例库": "pkulaw",
    "裁判文书采购": "wenshu", "合作案卷": "partner",
}

WEB_EXTRA_KEYS = ["page_id", "site", "publisher", "title", "item_index",
                  "needs_ocr", "attachment_files", "province_code", "region_level"]


def extract_extra(rec: dict, channel: str) -> dict:
    """源标记信封（design §3）；extra.outcome（detention_items 辅助）提升为 extra.detention_items，
    与旧 extra.outcome/extra.quality 命名混淆一并消除。"""
    ex = rec.get("extra") or {}
    out: dict = {}
    if channel == "web":
        out = {k: ex[k] for k in WEB_EXTRA_KEYS if k in ex}
    legacy = ex.get("legacy")
    if isinstance(legacy, dict):
        if legacy.get("pkulaw_id"):
            out["pkulaw_id"] = legacy["pkulaw_id"]
        if legacy.get("event_hint") is not None:
            out["event_hint"] = legacy["event_hint"]
    old_outcome = ex.get("outcome")
    if isinstance(old_outcome, dict) and old_outcome.get("detention_items"):
        out["detention_items"] = old_outcome["detention_items"]
    return out


def _readonly(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD)
    except OSError:
        pass  # Windows/网络盘可能不支持，尽力而为


def _writable(path: Path) -> None:
    """重写前解除上一批的只读位（否则 open('w') 静默 PermissionError，旧文件残留）。"""
    if path.exists():
        try:
            os.chmod(path, stat.S_IWRITE)
        except OSError:
            pass


def convert(in_path: str, channel: str | None, out_dir: str,
            sample_target: int = SAMPLE_TARGET) -> dict:
    recs = [json.loads(line) for line in open(in_path, encoding="utf-8")]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    unified: list[dict] = []
    edits_rows: list[dict] = []
    rule_fired: Counter = Counter()
    form_dist: Counter = Counter()
    release_dist: Counter = Counter()
    strata: Counter = Counter()
    len_sum = [0, 0]
    replay_fail = 0

    for rec in recs:
        ch = channel or CHANNEL_BY_SOURCE.get(rec.get("source") or "", "web")
        orig = rec.get("text_full") or ""
        res: CleanResult = cleanse(orig, ch)
        if res.replay(orig) != res.cleaned:
            replay_fail += 1
        form = detect_form(rec.get("source_type") or "", res.cleaned,
                           pku_form=(rec.get("quality") or {}).get("form", "") if ch == "pkulaw" else "")
        sents = sentence_table(res.cleaned)
        # 公示族确定性分区（zoning.py）：正则分段（原文坐标）→ 句号区间；非公示族为 None
        zones_det = None
        if is_public_form(form):
            zones_det = deterministic_zones(rec.get("segments") or {}, sents, _o2c(res),
                                            cleaned=res.cleaned)
        # 正则 facts 的 clean 坐标（全形态存，供 s1 的 facts 兜底合并）
        regex_facts_clean = None
        fpos = (rec.get("segments") or {}).get("text_facts")
        if isinstance(fpos, list) and len(fpos) == 2:
            regex_facts_clean = _o2c(res)((fpos[0], fpos[1])) or None
        pref = eval_prefilter(rec, res.cleaned)
        for rule, n in res_decount(res):
            rule_fired[rule] += n
        form_dist[form] += 1
        if pref["stratum"]:
            strata[pref["stratum"]] += 1
        len_sum[0] += len(orig)
        len_sum[1] += len(res.cleaned)
        unified.append({
            "id": rec["id"], "source": rec.get("source") or "", "channel": ch,
            "source_type": rec.get("source_type") or "", "form": form,
            "clean_version": CLEAN_VERSION,
            "text_orig_sha256": hashlib.sha256(orig.encode("utf-8")).hexdigest(),
            "orig_len": len(orig), "cleaned_len": len(res.cleaned),
            "doc_no_hash": rec.get("doc_no_hash") or "",
            "authority": rec.get("authority") or "",
            "subject_mention": rec.get("subject_mention") or "",
            "behavior_date": rec.get("behavior_date") or "",
            "decision_date": rec.get("decision_date") or "",
            "harvest_date": rec.get("harvest_date") or "",
            "prefilter": pref,
            "cleaned_text": res.cleaned,
            "sentences": sents,
            "zones_det": zones_det,
            "regex_facts_clean": regex_facts_clean,
            "extra": extract_extra(rec, ch),
        })
        edits_rows.append({"id": rec["id"], **res.to_edits()})

    # 批级"否"池分层抽样（Q9）：固定种子可复现
    pool = [r for r in zip(recs, unified) if (r[1]["prefilter"]["gambling"] == "否")]
    pool_wrapped = [{"id": u["id"], "_unified": u} for _rec, u in pool]
    sampled = sample_pool(pool_wrapped, target=sample_target)
    for u in unified:
        if u["prefilter"]["gambling"] == "否" and u["id"] in sampled:
            u["prefilter"]["release"] = True
            u["prefilter"]["release_reason"] = "sampled"
    release_dist = Counter(u["prefilter"]["release_reason"].split(":")[0] or "unreleased" for u in unified)

    for path, rows in ((out / "records.jsonl", unified), (out / "edits.rle.jsonl", edits_rows)):
        _writable(path)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _readonly(path)

    n = len(unified)
    stats = {
        "batch": str(in_path), "channel": channel or "(按记录推导)",
        "clean_version": CLEAN_VERSION, "n": n,
        "released": sum(1 for u in unified if u["prefilter"]["release"]),
        "release_reasons": dict(release_dist),
        "borderline": sum(1 for u in unified if u["prefilter"]["borderline"]),
        "strata_pool": dict(strata), "sampled": len(sampled),
        "forms": dict(form_dist),
        "rule_fired": {k: v for k, v in rule_fired.most_common()},
        "avg_orig_len": round(len_sum[0] / n, 1) if n else 0,
        "avg_clean_len": round(len_sum[1] / n, 1) if n else 0,
        "replay_failures": replay_fail,
    }
    stats_path = out / "stats.json"
    _writable(stats_path)
    with open(stats_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    _readonly(stats_path)
    return stats


def res_decount(res: CleanResult):
    """规则命中次数：删除按区间数、替换按条数（统计口径）。"""
    for rule, ranges in res.deletes.items():
        yield rule, len(ranges)
    for rule, rows in res.subs.items():
        yield rule, len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("records")
    ap.add_argument("--channel", default=None, choices=["web", "pkulaw"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample-target", type=int, default=SAMPLE_TARGET)
    a = ap.parse_args()
    stats = convert(a.records, a.channel, a.out, a.sample_target)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
