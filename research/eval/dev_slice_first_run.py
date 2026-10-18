"""G2.3 引擎开发首跑：独立切片核查与历史处罚的简单基线。

只读冻结切片；只用 input 作模型特征，observed_outcome 只作历史目标。
开发 test 保留不评估；结果写外置 engine/development，不进入人工金标报告。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error
from sklearn.pipeline import make_pipeline

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "justilaw-api"))
from app.discretion.extract import cn_to_number  # noqa: E402

DEFAULT_SLICE = Path(os.environ.get("JUSTILAW_DATA_DIR", r"D:\02_Dev\Data\justilaw-research")) / "parsed2" / "dev-slice-20261018-codex-v2"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_slice(root: Path) -> tuple[list[dict], dict, dict]:
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    hashes = {name: sha((root / name).read_bytes()) for name in
              ("manifest.json", "records.jsonl", "excluded.jsonl")}
    for name in ("records.jsonl", "excluded.jsonl"):
        expected = manifest.get("artifact_hashes", {}).get(name)
        if expected != hashes[name]:
            raise ValueError(f"冻结切片文件哈希变化: {name}")
    rows = [json.loads(line) for line in (root / "records.jsonl").read_text("utf-8").splitlines() if line]
    return rows, manifest, hashes


_UPPER_NUMERALS = str.maketrans("壹贰叁肆伍陆柒捌玖拾佰仟", "一二三四五六七八九十百千")
_NUM = r"[0-9一二两三四五六七八九十百千万零〇壹贰叁肆伍陆柒捌玖拾佰仟.,，]+"


def _stated_number(quote: str, pattern: str) -> float | None:
    values = [cn_to_number(m.translate(_UPPER_NUMERALS)) for m in re.findall(pattern, quote)]
    values = [v for v in values if v is not None]
    return values[0] if len(values) == 1 else None


def numeric_outcome_audit(rows: list[dict]) -> dict:
    """只核原决定引文里唯一且显式的拘留天数/罚款额；其余不装作已核。"""
    checked = Counter()
    mismatch = []
    for r in rows:
        quote = r["observed_outcome_evidence"]["quote"]
        outcome = r["observed_outcome"]
        for field, pattern in (("detention_days", rf"(?:行政)?拘留\s*({_NUM})\s*[日天]"),
                               ("fine", rf"罚款\s*(?:人民币)?\s*({_NUM})\s*元")):
            stated = _stated_number(quote, pattern)
            if stated is None:
                continue
            checked[field] += 1
            if abs(stated - float(outcome[field])) > 1e-6:
                mismatch.append({"id": r["id"], "field": field,
                                 "stated": stated, "observed": outcome[field]})
    return {"checked": dict(checked), "mismatch": mismatch,
            "uncheckable": {field: len(rows) - checked[field] for field in ("detention_days", "fine")}}


def audit(rows: list[dict], manifest: dict) -> dict:
    problems: list[dict] = []
    split_by_event: dict[str, set[str]] = defaultdict(set)
    ids = Counter(str(r.get("id")) for r in rows)
    if len(rows) != manifest.get("records") or len({r.get("event_id") for r in rows}) != manifest.get("events"):
        problems.append({"id": "*", "code": "manifest_count_mismatch"})
    for r in rows:
        rid = str(r.get("id"))
        source = r.get("source_text") or ""
        inp = r.get("input") or {}
        target = inp.get("target") or ""
        split_by_event[str(r.get("event_id"))].add(str(r.get("development_split")))
        if ids[rid] != 1:
            problems.append({"id": rid, "code": "duplicate_id"})
        if sha(source.encode("utf-8")) != r.get("text_orig_sha256"):
            problems.append({"id": rid, "code": "original_hash"})
        views = inp.get("views") or []
        if not target or target not in source or target not in "\n".join(v.get("text", "") for v in views):
            problems.append({"id": rid, "code": "target_not_grounded"})
        spans = []
        for view in views:
            a, b = view.get("start"), view.get("end")
            if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source)
                    or source[a:b] != view.get("text")):
                problems.append({"id": rid, "code": "input_span"})
            else:
                spans.append((a, b))
        facts = [v["text"] for v in views if v.get("type") == "facts"]
        if len(facts) != 1 or facts[0] != inp.get("facts_text"):
            problems.append({"id": rid, "code": "facts_view"})
        ev = r.get("observed_outcome_evidence") or {}
        a, b = ev.get("start"), ev.get("end")
        if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source)
                or source[a:b] != ev.get("quote")):
            problems.append({"id": rid, "code": "outcome_span"})
        elif any(max(a, x) < min(b, y) for x, y in spans):
            problems.append({"id": rid, "code": "input_outcome_overlap"})
        outcome = r.get("observed_outcome") or {}
        days, fine, typ = outcome.get("detention_days"), outcome.get("fine"), outcome.get("type")
        expected = {"拘留": days > 0 and fine == 0, "拘留并处罚款": days > 0 and fine > 0,
                    "罚款": days == 0 and fine > 0, "警告": days == 0 and fine == 0,
                    "不予处罚": days == 0 and fine == 0} if type(days) is int and type(fine) in (int, float) else {}
        if not expected.get(typ, False) or outcome.get("fine_masked"):
            problems.append({"id": rid, "code": "outcome_value_shape"})
        if r.get("reference_elements") is not None or r.get("release_approved") is not False:
            problems.append({"id": rid, "code": "development_status"})
    crossing = [e for e, splits in split_by_event.items() if len(splits) != 1]
    if crossing:
        problems.append({"id": "*", "code": "event_cross_split", "count": len(crossing)})
    attribution_review_ids = [r["id"] for r in rows if r["input"]["target"].casefold()
                              not in r["observed_outcome_evidence"]["quote"].casefold()]
    return {"records": len(rows), "events": len(split_by_event),
            "split_counts": dict(Counter(r["development_split"] for r in rows)),
            "target_in_outcome_quote": sum(r["input"]["target"] in r["observed_outcome_evidence"]["quote"] for r in rows),
            "attribution_review_ids": attribution_review_ids,
            "numeric_outcome_evidence": numeric_outcome_audit(rows),
            "problem_counts": dict(Counter(p["code"] for p in problems)), "problems": problems,
            "semantic_outcome_review": "pending_independent_review"}


def text_input(r: dict) -> str:
    return "\n".join(v["text"] for v in r["input"]["views"])


def _vectorizer():
    return TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True,
                           min_df=2, max_features=200_000)


def baselines(rows: list[dict]) -> dict:
    train = [r for r in rows if r["development_split"] == "train"]
    val = [r for r in rows if r["development_split"] == "validation"]
    if not train or not val:
        raise ValueError("切片缺少 train 或 validation")
    Xtr, Xva = [text_input(r) for r in train], [text_input(r) for r in val]
    ytr = [r["observed_outcome"]["type"] for r in train]
    yva = [r["observed_outcome"]["type"] for r in val]
    classes = sorted(set(ytr) | set(yva))
    result = {"target": "source_parser_observed_outcome", "feature": "input.views only",
              "test_evaluated": False, "train_n": len(train), "validation_n": len(val),
              "train_types": dict(Counter(ytr)), "validation_types": dict(Counter(yva)),
              "classification": {}, "numeric": {}, "example_cards": []}
    models = {
        "majority": DummyClassifier(strategy="most_frequent"),
        "B4_tfidf_lr": make_pipeline(_vectorizer(), LogisticRegression(C=3.0, max_iter=3000)),
    }
    for name, model in models.items():
        pred = model.fit(Xtr, ytr).predict(Xva)
        result["classification"][name] = {"accuracy": float(accuracy_score(yva, pred)),
                                          "macro_f1": float(f1_score(yva, pred, labels=classes,
                                                                      average="macro", zero_division=0))}
        if name == "B4_tfidf_lr":
            selected = {}
            for row, guess in sorted(zip(val, pred, strict=True), key=lambda pair: pair[0]["id"]):
                typ = row["observed_outcome"]["type"]
                selected.setdefault(typ, {"id": row["id"], "observed_type": typ,
                                          "predicted_type": str(guess),
                                          "observed_outcome_source": "source_parser_observation",
                                          "normative_review": "not_run",
                                          "similar_cases": "not_implemented",
                                          "prediction_interval": "not_implemented"})
            result["example_cards"] = [selected[k] for k in sorted(selected)]
    for field in ("detention_days", "fine"):
        ytr_num = [float(r["observed_outcome"][field]) for r in train]
        yva_num = [float(r["observed_outcome"][field]) for r in val]
        for name, model in {"median": DummyRegressor(strategy="median"),
                            "B4_tfidf_ridge": make_pipeline(_vectorizer(), Ridge(alpha=1.0))}.items():
            import numpy as np
            pred = np.expm1(model.fit(Xtr, np.log1p(ytr_num)).predict(Xva)).clip(min=0)
            result["numeric"].setdefault(field, {})[name] = {
                "mae": float(mean_absolute_error(yva_num, pred)),
                "within_20pct": float(np.mean(np.where(np.array(yva_num) == 0,
                                                         pred < 0.5,
                                                         np.abs(pred - yva_num) <= .2 * np.array(yva_num))))}
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows, manifest, hashes = load_slice(args.slice)
    checked = audit(rows, manifest)
    report = {"slice": args.slice.name, "hashes": hashes, "audit": checked,
              "field_accuracy": None, "field_accuracy_reason": "reference_elements=null",
              "development_only": True}
    if not checked["problems"]:
        report["baselines"] = baselines(rows)
    out = args.out or args.slice.parents[1] / "engine" / "development" / f"{args.slice.name}-first-run.json"
    if out.exists():
        raise FileExistsError("首跑报告不可原地覆盖；指定新 --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({"out": str(out), "audit_problems": checked["problem_counts"],
                      "baselines": report.get("baselines", {}).get("classification")}, ensure_ascii=False))
    return 1 if checked["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
