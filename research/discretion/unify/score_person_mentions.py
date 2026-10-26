"""Score person-mention layers against the persons two LLM reviewers listed (aggregates only).

Reference per record: the verbatim person surfaces both models list (agreed) and either
lists (union); mask characters are compared by shape (钱xx = 钱XX = 钱**). Compared layers:
the old regex layer (`ownership.person_mentions`) and the NER layer (`person_mentions_ner`),
both over the same layout-wrapped packet the review tasks were built from.

  other_recall  agreed non-target surfaces the layer finds (exact surface)
  target_found  records where the layer marks at least one target mention
  false_pos     distinct non-target surfaces the layer proposes that neither model lists
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from ownership import person_mentions as regex_mentions
from person_mentions_ner import MASK_RUN
from person_mentions_ner import person_mentions as ner_mentions
from supply_packet import build_packet


def norm(surface: str) -> str:
    return re.sub(f"{MASK_RUN}+", lambda m: "x" * len(m.group(0)), re.sub(r"\s+", "", surface or ""))


def reference(labels: Path, rid: str, names: tuple[str, str]) -> dict | None:
    lists = []
    for name in names:
        path = labels / f"{rid}-{name}.json"
        if not path.exists():
            return None
        lists.append(json.loads(path.read_text("utf-8"))["answer"]["persons"])
    sets = [{norm(p["surface"]) for p in ps} for ps in lists]
    target = {norm(p["surface"]) for ps in lists for p in ps if p["is_target"] == "yes"}
    return {"agreed": sets[0] & sets[1], "union": sets[0] | sets[1], "target": target}


def score(inputs: Path, labels: Path, names: tuple[str, str]) -> dict:
    layers = {"regex": regex_mentions, "ner": ner_mentions}
    c = Counter()
    misses = {k: Counter() for k in layers}
    extras = {k: Counter() for k in layers}
    for r in rows(inputs):
        ref = reference(labels, r["id"], names)
        if ref is None:
            continue
        c["records"] += 1
        packet = build_packet(r["text_full"], r, record_id=r["id"], layout_wraps=True)
        others = ref["agreed"] - ref["target"]
        c["ref_other_agreed"] += len(others)
        for layer, fn in layers.items():
            ms = fn(packet, r)
            if layer == "ner":
                c["ner_fallback_mentions"] += sum(m.get("source") == "regex_fallback" for m in ms)
            surfaces = {norm(m["raw"]) for m in ms if not m["kind"].startswith("role")}
            c[f"{layer}:target_found"] += any(m["kind"] == "target" for m in ms)
            found = others & surfaces
            c[f"{layer}:other_found"] += len(found)
            misses[layer].update(others - surfaces)
            extra = {norm(m["raw"]) for m in ms if m["kind"] in ("masked", "plain")} - ref["union"] - ref["target"]
            c[f"{layer}:false_pos"] += len(extra)
            extras[layer].update(extra)
    out = dict(c)
    for layer in layers:
        out[f"{layer}:other_recall"] = round(c[f"{layer}:other_found"] / c["ref_other_agreed"], 3) if c["ref_other_agreed"] else None
        out[f"{layer}:target_found_rate"] = round(c[f"{layer}:target_found"] / c["records"], 3) if c["records"] else None
    out["examples"] = {f"{k}:missed": misses[k].most_common(15) for k in layers}
    out["examples"].update({f"{k}:false_pos": extras[k].most_common(15) for k in layers})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True, help="run_review_llm labels directory")
    ap.add_argument("--providers", default="bailian,deepseek")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = score(args.inputs, args.labels, tuple(args.providers.split(",")))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
