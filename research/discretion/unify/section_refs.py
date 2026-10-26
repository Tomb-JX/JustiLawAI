"""Fine references may overlap; mutually exclusive S1 zones remain untouched."""
from __future__ import annotations

import re

from element_contract import digest
from evidence_types import SourceSpan

VERSION = "section-refs-1"
PATTERNS = {
    "operative_outcome": r"决定(?:给予|予以|如下|对)|处以|不予(?:行政)?处罚|罚款|行政拘留",
    "legal_basis": r"(?:依据|根据)|《[^》]+》|第[〇零一二三四五六七八九十百\d]+条",
    "execution": r"(?:缴纳|缴交|收缴|执行|暂缓|不执行|合并执行)",
    "remedy_notice": r"(?:可以|可在|不服).*(?:复议|诉讼)|六十日内|六个月内",
    "review_result": r"维持|撤销|变更|确认违法|驳回",
    "legal_conclusion": r"构成|情节严重|情节轻微|从轻|从重|减轻",
}


def fine_references(original: str, views: list[dict]):
    refs = []
    for view in views:
        SourceSpan.from_text(original, view["start"], view["end"]).verify(original)
        if original[view["start"]:view["end"]] != view["text"]:
            raise ValueError("section_reference_source_mismatch")
        # Split only on strong boundaries; preserve comma-bound clauses so that
        # "依据…，决定…" can carry both kinds, with exact original provenance.
        for match in re.finditer(r"[^。；;\n]+[。；;\n]?", view["text"]):
            a, b = view["start"] + match.start(), view["start"] + match.end()
            span = SourceSpan.from_text(original, a, b)
            kinds = [kind for kind, pattern in PATTERNS.items() if re.search(pattern, span.quote)]
            if not kinds:
                kinds = ["unclassified"]
            refs.append({"id": "R-" + digest({"span": span.to_dict(), "version": VERSION})[:20],
                         "source_ref": span.to_dict(), "zone": view.get("type"), "kinds": kinds,
                         "classification": "lexical_candidate", "requires_semantic_review": True})
    return {"version": VERSION, "references": refs}
