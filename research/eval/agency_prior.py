"""Event-weighted, as-of hierarchical prior for historical penalty types.

This is a statistical description of prior decisions, not a legal rule.  It
reads decision dates and issuing authorities from the existing S1 record
metadata; no element labels or sealed test cases are involved.  The decision
epoch is a date bucket, not a determination of the law applied to an incident.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from m4_type_algorithm_cv import LABELS


ROOT = Path("D:/02_Dev/Data/justilaw-research")
SOURCE_FILES = (
    "unified_raw_refresh/20261018-s1-repaired/records.jsonl",
    "unified_raw_refresh/20261026-P3P7-additions/records.jsonl",
    "unified_raw_refresh/20261027-P9-additions/records.jsonl",
)
PROVINCES = {
    "北京": "11", "天津": "12", "河北": "13", "山西": "14", "内蒙古": "15",
    "辽宁": "21", "吉林": "22", "黑龙江": "23", "上海": "31", "江苏": "32",
    "浙江": "33", "安徽": "34", "福建": "35", "江西": "36", "山东": "37",
    "河南": "41", "湖北": "42", "湖南": "43", "广东": "44", "广西": "45",
    "海南": "46", "重庆": "50", "四川": "51", "贵州": "52", "云南": "53",
    "西藏": "54", "陕西": "61", "甘肃": "62", "青海": "63", "宁夏": "64", "新疆": "65",
}
PROVINCE_PREFIXES = tuple(sorted(PROVINCES, key=len, reverse=True))


def _date(value: str | None) -> date | None:
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _authority(value: str | None) -> str | None:
    if not value:
        return None
    clean = re.sub(r"\s+", "", value).strip("，,。;；")
    return clean or None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Context:
    id: str
    event_id: str
    authority_id: str | None
    city_code: str | None
    province_code: str | None
    decision_date: date | None
    decision_epoch: str | None
    authority_source: str
    location_source: str

    def serializable(self) -> dict:
        out = asdict(self)
        out["decision_date"] = self.decision_date.isoformat() if self.decision_date else None
        return out


def load_contexts(rows: list[dict], root: Path = ROOT) -> tuple[dict[str, Context], dict]:
    """Join existing S1 metadata by stable id, never by event date or outcome."""
    wanted = {r["id"] for r in rows}
    records: dict[str, dict] = {}
    hashes = {}
    for relative in SOURCE_FILES:
        path = root / relative
        hashes[relative] = _sha(path)
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                raw = json.loads(line)
                rid = raw.get("id")
                if rid not in wanted:
                    continue
                if rid in records:
                    raise ValueError(f"S1 metadata id duplicated across frozen sources: {rid}")
                records[rid] = raw

    # Only exact authority matches with one location are admitted.  Fuzzy
    # matching or city-name guessing would silently fabricate parent groups.
    locations: dict[str, set[str]] = defaultdict(set)
    db = sqlite3.connect(str(root / "lake/catalog/lake.db"))
    try:
        for authority, region in db.execute(
                "select authority, region_code from documents "
                "where authority is not null and region_code is not null and region_code != ''"):
            key = _authority(authority)
            if key and re.fullmatch(r"\d{6}", region):
                locations[key].add(region[:4])
    finally:
        db.close()

    contexts = {}
    audit = Counter()
    for row in rows:
        rid = row["id"]
        source = records.get(rid, {})
        authority = _authority(source.get("authority"))
        authority_source = "s1_record" if authority else "missing"
        decision = _date(source.get("decision_date"))
        codes = locations.get(authority, set()) if authority else set()
        city = next(iter(codes)) if len(codes) == 1 else None
        province_candidates = {code[:2] for code in codes}
        province = next(iter(province_candidates)) if len(province_candidates) == 1 else None
        location_source = "lake_exact_authority" if province else "unknown"
        if province is None and authority:
            for prefix in PROVINCE_PREFIXES:
                if authority.startswith(prefix):
                    province = PROVINCES[prefix]
                    location_source = "explicit_authority_prefix"
                    break
        if len(province_candidates) > 1:
            province = city = None
            location_source = "conflicting_lake_regions"
        epoch = ("new_2026" if decision >= date(2026, 1, 1) else "old_pre_2026") if decision else None
        context = Context(rid, row["event_id"], authority, city, province,
                          decision, epoch, authority_source, location_source)
        contexts[rid] = context
        audit["source_record_found"] += bool(source)
        audit["authority_available"] += bool(authority)
        audit["decision_date_exact"] += bool(decision)
        audit["province_available"] += bool(province)
        audit["city_available"] += bool(city)
        audit[f"location_source:{location_source}"] += 1
        if source.get("event_id") != row["event_id"]:
            audit["source_event_id_differs"] += 1
    return contexts, {"counts": dict(audit), "source_sha256": hashes,
                      "scope": "frozen_train_metadata_only"}


@dataclass(frozen=True)
class PriorResult:
    probabilities: dict[str, float] | None
    global_probabilities: dict[str, float] | None
    source_level: str
    effective_events: float
    as_of: str | None
    decision_epoch: str | None


class AgencyPrior:
    """Fold-local counts with date-before-query and same-event exclusion."""

    def __init__(self, rows: list[dict], contexts: dict[str, Context],
                 train_indices, *, smoothing_events: float = 20.0):
        self.smoothing_events = smoothing_events
        train_indices = list(train_indices)
        event_sizes = Counter(rows[i]["event_id"] for i in train_indices)
        self.history = []
        for i in train_indices:
            row = rows[i]
            c = contexts[row["id"]]
            if c.decision_date is None or c.decision_epoch is None:
                continue
            y = row["target"]["type"]
            if y not in LABELS:
                y = "不予处罚"
            self.history.append((c, y, 1 / event_sizes[row["event_id"]]))

    def predict(self, query: Context, *, max_level: str = "agency") -> PriorResult:
        if query.decision_date is None or query.decision_epoch is None:
            return PriorResult(None, None, "unavailable_date", 0, None, query.decision_epoch)
        if max_level not in ("province", "city", "agency"):
            raise ValueError(f"unsupported prior level: {max_level}")
        counts = {level: Counter() for level in ("global", "province", "city", "agency")}
        for past, outcome, weight in self.history:
            if past.decision_date >= query.decision_date or past.event_id == query.event_id:
                continue
            if past.decision_epoch != query.decision_epoch:
                continue
            counts["global"][outcome] += weight
            if query.province_code and past.province_code == query.province_code:
                counts["province"][outcome] += weight
            if query.city_code and past.city_code == query.city_code:
                counts["city"][outcome] += weight
            if query.authority_id and past.authority_id == query.authority_id:
                counts["agency"][outcome] += weight
        total = sum(counts["global"].values())
        if total == 0:
            return PriorResult(None, None, "unavailable_epoch_history", 0,
                               query.decision_date.isoformat(), query.decision_epoch)
        # Symmetric pseudocounts keep ratios finite even for rare classes.
        global_p = {y: (counts["global"][y] + 1) / (total + len(LABELS)) for y in LABELS}
        parent = global_p
        used_level = "global"
        effective = total
        for level in ("province", "city", "agency"):
            if ((max_level == "province" and level == "city")
                    or (max_level == "city" and level == "agency")):
                break
            n = sum(counts[level].values())
            if n <= 0:
                continue
            parent = {y: (counts[level][y] + self.smoothing_events * parent[y]) /
                      (n + self.smoothing_events) for y in LABELS}
            used_level, effective = level, n
        return PriorResult(parent, global_p, used_level, effective,
                           query.decision_date.isoformat(), query.decision_epoch)
