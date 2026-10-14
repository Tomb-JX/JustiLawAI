"""规范库加载与引用（M0）。

规范库是法律原文的机器可读版本：条文逐字存放，结构化参数由法律组核对。
引擎只从这里取法条原文，说理中引用的条文必须能在这里逐字找到（门禁红线 R2）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

NORMS_DIR = Path(__file__).resolve().parent / "norms"


@dataclass(frozen=True)
class Tier:
    combination: str                 # 或 / 并处 / 可以并处
    detention: tuple[int, int]
    fine: tuple[float, float]


@dataclass
class Law:
    law_id: str
    title: str
    effective_from: date
    effective_to: date | None
    articles: dict[str, str]
    penalty_article: str
    behaviors: dict[str, str]
    tiers: dict[str, Tier]
    modifiers: dict
    source: dict
    verification: dict

    def in_force(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)

    @property
    def verified(self) -> bool:
        return self.verification.get("status") == "已核验"


@dataclass
class NormLibrary:
    laws: list[Law]                                  # 只含有赌博罚则的法律，按施行日期排序
    temporal: dict                                   # 行政处罚法时间效力规则
    documents: dict[str, dict]                       # doc_id → 文件（含 articles、verification）
    mitigation_rules: dict
    calculation_rules: list[dict]
    criminal_thresholds: dict
    provinces: dict[str, dict] = field(default_factory=dict)

    def law_in_force(self, d: date) -> Law | None:
        return next((law for law in self.laws if law.in_force(d)), None)

    def law(self, law_id: str) -> Law:
        return next(law for law in self.laws if law.law_id == law_id)

    def cite(self, doc_id: str, article: str) -> str | None:
        """逐字原文；没有原文（未取得或未录入）返回 None，调用方不得引用。"""
        doc = self.documents.get(doc_id)
        return (doc or {}).get("articles", {}).get(article)

    def is_verified(self, doc_id: str) -> bool:
        doc = self.documents.get(doc_id) or {}
        return (doc.get("verification") or {}).get("status") == "已核验"


def _date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _load_law(raw: dict) -> Law:
    p = raw["penalty"]
    tiers = {name: Tier(t["combination"], tuple(t["detention"]), tuple(t["fine"])) for name, t in p["tiers"].items()}
    return Law(
        law_id=raw["law_id"], title=raw["title"],
        effective_from=_date(raw["effective_from"]), effective_to=_date(raw.get("effective_to")),
        articles={str(k): v for k, v in raw["articles"].items()},
        penalty_article=str(p["article"]), behaviors=p["behaviors"], tiers=tiers,
        modifiers=raw.get("modifiers") or {}, source=raw.get("source") or {},
        verification=raw.get("verification") or {},
    )


def validate(lib: NormLibrary) -> list[str]:
    """结构自检：引用的条文都存在、幅度合理、施行期间不重叠。返回问题列表（空 = 通过）。"""
    problems = []
    for law in lib.laws:
        refs = [law.penalty_article] + [m["article"] for m in law.modifiers.values() if "article" in m]
        problems += [f"{law.law_id}: 引用的第{a}条没有原文" for a in refs if str(a) not in law.articles]
        for name, t in law.tiers.items():
            if not (t.detention[0] <= t.detention[1] and t.fine[0] <= t.fine[1]):
                problems.append(f"{law.law_id}/{name}: 幅度上下限颠倒")
    for a, b in zip(lib.laws, lib.laws[1:]):
        if a.effective_to is None or a.effective_to >= b.effective_from:
            problems.append(f"{a.law_id} 与 {b.law_id} 施行期间重叠或未衔接")
    return problems


@lru_cache(maxsize=1)
def load(norms_dir: Path = NORMS_DIR) -> NormLibrary:
    national = norms_dir / "national"
    laws, documents, temporal, interp = [], {}, {}, {}
    for path in sorted(national.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text("utf-8"))
        if "penalty" in raw:
            law = _load_law(raw)
            laws.append(law)
            documents[law.law_id] = {"title": law.title, "articles": law.articles,
                                     "verification": law.verification, "source": law.source}
        elif "temporal_rule" in raw:
            temporal = raw["temporal_rule"]
            documents[raw["law_id"]] = {"title": raw["title"], "articles": {str(k): v for k, v in raw["articles"].items()},
                                        "verification": raw.get("verification") or {}, "source": raw.get("source") or {}}
        elif "documents" in raw:
            interp = raw
            for doc in raw["documents"]:
                documents[doc["doc_id"]] = {**doc, "articles": {str(k): v for k, v in (doc.get("articles") or {}).items()}}
    provinces = {}
    for path in sorted((norms_dir / "provinces").glob("*.yaml")):
        if not path.name.startswith("_"):
            raw = yaml.safe_load(path.read_text("utf-8"))
            provinces[str(raw["region"])] = raw
    laws.sort(key=lambda law: law.effective_from)
    lib = NormLibrary(laws=laws, temporal=temporal, documents=documents,
                      mitigation_rules=interp.get("mitigation_rules", {}),
                      calculation_rules=interp.get("calculation_rules", []),
                      criminal_thresholds=interp.get("criminal_thresholds", {}),
                      provinces=provinces)
    problems = validate(lib)
    if problems:
        raise ValueError("规范库自检失败：" + "；".join(problems))
    return lib
