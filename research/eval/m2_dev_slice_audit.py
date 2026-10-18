"""E-01：只核历史观察处罚与国层规范库的关系，不改来源观察值。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "justilaw-api"))
from app.discretion.norm_layer import _statutory  # noqa: E402
from app.discretion.norm_store import load  # noqa: E402
from dev_slice_first_run import DEFAULT_SLICE, load_slice  # noqa: E402

DEFAULT_CAPS = Path(r"D:\02_Dev\Data\justilaw-research\config\legal_caps.json")
LAW_IDS = {"旧法": "psal-2012", "新法": "psal-2025"}
ARTICLE_MARKERS = {"psal-2012": ("第七十条", "第70条"),
                   "psal-2025": ("第八十二条", "第82条")}


def verify_caps(caps: dict, lib) -> None:
    for law in lib.laws:
        path = Path(__file__).resolve().parents[2] / "justilaw-api" / "app" / "discretion" / "norms" / "national" / f"{law.law_id}.yaml"
        expected_hash = caps["source_files"][law.law_id]["sha256_16"]
        if hashlib.sha256(path.read_bytes()).hexdigest()[:16] != expected_hash:
            raise ValueError(f"legal_caps 与规范库源哈希不一致: {law.law_id}")
        cap = caps["laws"][law.law_id]
        penalty = cap["gambling_articles"][law.penalty_article]
        for name, tier in law.tiers.items():
            stated = penalty["tiers"][name]
            if (stated["combination"] != tier.combination or stated["detention"] != list(tier.detention)
                    or stated["fine"] != list(tier.fine)):
                raise ValueError(f"legal_caps 罚幅与 norm_layer 不一致: {law.law_id}/{name}")
        if cap["effective"] != [law.effective_from.isoformat(),
                                law.effective_to.isoformat() if law.effective_to else None]:
            raise ValueError(f"legal_caps 效力区间与规范库不一致: {law.law_id}")


def _known_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None
    except ValueError:
        return None


def inspect_row(row: dict, caps: dict, lib) -> dict:
    rid, meta, oc = row["id"], row["metadata"], row["observed_outcome"]
    version = meta.get("law_version")
    observed_version = oc.get("law_version") or None
    days, fine = oc["detention_days"], oc["fine"]
    citations = "|".join(oc.get("articles") or [])
    cited = [law_id for law_id, markers in ARTICLE_MARKERS.items()
             if any(marker in citations for marker in markers)]
    reasons: list[str] = []
    law_id = LAW_IDS.get(version)
    if not law_id:
        reasons.append("law_version_unknown")
    if observed_version and observed_version != version:
        reasons.append("outcome_law_version_mismatch")
    if not cited:
        reasons.append("gambling_penalty_article_not_cited")
    elif law_id and law_id not in cited:
        reasons.append("penalty_article_version_conflict")
    if len(cited) > 1:
        reasons.append("mixed_penalty_articles")
    behavior = _known_date(meta.get("behavior_date"))
    decision = _known_date(meta.get("decision_date"))
    if law_id and behavior:
        law = lib.law(law_id)
        if behavior >= date(2026, 1, 1) and law_id == "psal-2012":
            reasons.append("old_law_for_new_behavior")
        elif not law.in_force(behavior):
            # 新法从旧兼从轻可能成立，须保留为待核而非违法结论。
            reasons.append("new_law_for_old_behavior_needs_temporal_review")
    elif not behavior:
        reasons.append("behavior_date_not_day_precision")
    if behavior and decision and decision < behavior:
        reasons.append("decision_before_behavior")
    if days > 20:
        reasons.append("detention_over_merge_cap")
    elif days > 15:
        reasons.append("detention_over_single_offense_needs_merger_review")
    if law_id:
        law = lib.law(law_id)
        cap = caps["laws"][law_id]["gambling_articles"][law.penalty_article]
        max_fine = max(t["fine"][1] for t in cap["tiers"].values())
        if fine > max_fine:
            reasons.append("fine_over_single_offense_needs_merger_review")
    if oc["type"] in ("警告", "不予处罚", "不构成违法"):
        reasons.append("nonstandard_outcome_needs_modifier_review")
    eligible = law_id is not None and cited == [law_id]
    inside = None
    if eligible:
        law = lib.law(law_id)
        options = [o for tier in law.tiers.values() for o in _statutory(law, tier)]
        inside = any(o.contains(days, fine) for o in options)
        if not inside:
            reasons.append("outside_default_statutory_options")
    return {"id": rid, "law_version": version, "cited_penalty_laws": cited,
            "observed_type": oc["type"], "observed_detention_days": days,
            "observed_fine": fine, "default_statutory_checkable": eligible,
            "inside_default_statutory_options": inside, "flags": sorted(set(reasons))}


def evaluate(rows: list[dict], caps: dict, lib) -> dict:
    details = [inspect_row(row, caps, lib) for row in rows]
    checkable = [d for d in details if d["default_statutory_checkable"]]
    inside = [d for d in checkable if d["inside_default_statutory_options"]]
    flags = Counter(flag for d in details for flag in d["flags"])
    return {"records": len(rows), "checkable_with_explicit_version_and_article": len(checkable),
            "inside_default_statutory_options": len(inside),
            "inside_rate_among_checkable": len(inside) / len(checkable) if checkable else None,
            "flags": dict(flags), "details": details,
            "interpretation": "历史观察处罚与默认国层罚则机械对照；档外可能为减轻或多项合并，不能直接称违法；不改历史目标。"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    ap.add_argument("--caps", type=Path, default=DEFAULT_CAPS)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows, manifest, hashes = load_slice(args.slice)
    caps_bytes = args.caps.read_bytes()
    caps = json.loads(caps_bytes)
    lib = load()
    verify_caps(caps, lib)
    report = {"task": "E-01", "slice_manifest_sha256": hashes["manifest.json"],
              "caps_sha256": hashlib.sha256(caps_bytes).hexdigest(),
              "audit": evaluate(rows, caps, lib)}
    out = args.out or args.slice.parents[1] / "engine" / "development" / f"{args.slice.name}-m2-legal-audit.json"
    if out.exists():
        raise FileExistsError("规范核查报告不可覆盖；指定新 --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"out": str(out), **{k: v for k, v in report["audit"].items() if k != "details"}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
