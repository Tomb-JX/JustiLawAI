"""Person mentions from two Chinese NER models (HanLP, LTP) instead of grown regexes.

`ownership.person_mentions` finds people with surname regexes plus a growing list of
exceptions (PLACE_NEXT, NOT_GIVEN, PERSON_NEXT ...). On 921 cached fact segments it missed
184 of the 1,138 names both NER models agree on (16%: "杨××"-style masks, unmasked full
names) and proposed 79 non-names ("方式", "张封顶", "金额***"). This module reads the NER
spans cached by `parse_with_toolkits.py` (content-addressed by the segment's SHA256) and
combines them by structure, not by word lists:

  - both models tag the span (overlap)                         -> person;
  - one model tags it and it has a masked-name shape           -> person;
  - one model tags it and it sits in an enumeration ("、和与及") next to another person -> person;
  - neither tags it, but it is a bare masked name (surname + 1-3 mask chars, e.g. "匡**")
    -> person (NER tokenisers split rare surnames off their masks).

Role nouns (申请人, 违法行为人) stay a separate kind. A mention is the target when its surface
matches the target or an alias, mask runs compared by shape (钱** ~ 钱xx ~ 钱某某).
Segments missing from the cache fall back to the old regex layer and are flagged, so a
caller can tell NER coverage from fallback. Output matches `ownership.person_mentions`.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from ownership import ROLE_NOUN, SURNAME
from ownership import person_mentions as regex_mentions

CACHE = Path("D:/02_Dev/Data/justilaw-research/relation_annotation/parse-cache")
PERSON_LABELS = {"PERSON", "Nh"}
MASK = "xX×*＊ｘ某"
MASK_RUN = f"[{re.escape(MASK)}]"
# 钱xx / 钱某某 / 谢× / 邝建* / 王某1: surname, at most one given character, then a mask run.
MASKED_SHAPE = re.compile(SURNAME + f"[\u4e00-\u9fff]?{MASK_RUN}{{1,3}}\\d?")
# 匡** / 王某某; a single 某 is left to the NER models (王某扬 vs 王某赌资 needs context).
BARE_MASKED = re.compile(SURNAME + "(?:[xX×*＊ｘ]{1,3}|某某)(?![xX×*＊ｘ某])")
ENUM = set("、和与及")


@lru_cache(maxsize=2)
def ner_spans(toolkit: str, cache: Path = CACHE) -> dict[str, list[tuple[int, int]]]:
    """key -> person spans as character offsets inside the segment."""
    out = {}
    with (cache / f"{toolkit}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            offs = r["offsets"]
            out[r["key"]] = [(offs[a][0], offs[b][1]) for lab, a, b in (r.get("ner") or []) if lab in PERSON_LABELS]
    return out


def name_matcher(target: str, aliases) -> re.Pattern | None:
    """One pattern for the target and its aliases; every mask run matches 1–3 mask characters."""
    alts = []
    for name in {target, *(aliases or ())}:
        name = (name or "").strip()
        if len(name) < 2:
            continue
        parts = re.split(f"({MASK_RUN}+)", name)
        alts.append("".join(f"{MASK_RUN}{{1,3}}" if p and p[0] in MASK else re.escape(p) for p in parts if p))
    return re.compile("(?:" + "|".join(sorted(alts, key=len, reverse=True)) + ")") if alts else None


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


TRAILING_MASK = re.compile(r"(?:[xX×*＊ｘ]{1,3}|某某?)\d?")


def extend_masks(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """NER tokenisers split "李xx" into "李" + "xx" and tag only the surname: extend a person
    span over a mask run that directly follows it, so the mention is the whole masked name."""
    out = []
    for a, b in spans:
        m = TRAILING_MASK.match(text, b)
        out.append((a, m.end()) if m else (a, b))
    return out


def segment_people(text: str, hanlp: list[tuple[int, int]], ltp: list[tuple[int, int]]) -> list[tuple[int, int, str]]:
    """Person spans in one segment with the rule that admitted each."""
    hanlp, ltp = extend_masks(text, hanlp), extend_masks(text, ltp)
    # A person mention has at least two characters and a hanzi: a lone surname ("周") or a lone
    # mask ("xx") left over by tokenisation is not a name.
    hanlp, ltp = ([s for s in spans if s[1] - s[0] >= 2 and re.search("[一-鿿]", text[s[0]:s[1]])]
                  for spans in (hanlp, ltp))
    found: list[tuple[int, int, str]] = []
    for span in hanlp:
        if any(_overlaps(span, o) for o in ltp):
            found.append((*span, "both"))
    singles = [(s, "hanlp") for s in hanlp if not any(_overlaps(s, o) for o in ltp)]
    singles += [(s, "ltp") for s in ltp if not any(_overlaps(s, o) for o in hanlp)]
    for (a, b), src in singles:
        if MASKED_SHAPE.fullmatch(text[a:b]):
            found.append((a, b, src + "+masked"))
    # Enumeration counts only next to an anchored name (both models, or masked shape), so a
    # one-model span cannot pull in its own one-model neighbour.
    anchors = [(a, b) for a, b, _ in found]
    for (a, b), src in singles:
        if (a, b) in anchors:
            continue
        before, after = text[a - 1:a] if a else "", text[b:b + 1]
        if (before in ENUM and any(e == a - 1 for _, e in anchors)) or \
                (after in ENUM and any(s == b + 1 for s, _ in anchors)):
            found.append((a, b, src + "+enum"))
    for m in BARE_MASKED.finditer(text):
        span = (m.start(), m.end())
        if not any(_overlaps(span, (a, b)) for a, b, _ in found):
            found.append((*span, "masked_only"))
    return sorted(found)


def person_mentions(packet: dict, inp: dict, cache: Path = CACHE) -> list[dict]:
    hanlp, ltp = ner_spans("hanlp", cache), ner_spans("ltp", cache)
    match = name_matcher(inp["target"], inp.get("aliases"))
    target_spans = [(m["start"], m["end"]) for m in packet["mentions"]
                    if any(p["target"] and m["mention_id"] in p["mention_ids"] for p in packet["persons"])]
    found = [{"start": s, "end": e, "raw": packet_text(packet, s, e), "kind": "target", "source": "packet"}
             for s, e in target_spans]
    fallback = None
    for view in packet["visible_spans"]:
        if view["zone"] != "facts" or not view["quote"].strip():
            continue
        text, base = view["quote"], view["start"]
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key not in hanlp or key not in ltp:
            if fallback is None:
                fallback = regex_mentions(packet, inp)
            found += [dict(m, source="regex_fallback") for m in fallback
                      if base <= m["start"] < base + len(text) and m["kind"] != "target"]
            continue
        proposals = [(a, b, src, "person") for a, b, src in segment_people(text, hanlp[key], ltp[key])]
        proposals += [(m.start(), m.end(), "role", "role:" + m.group(0)) for m in ROLE_NOUN.finditer(text)]
        for a, b, src, kind in proposals:
            gs, ge = base + a, base + b
            if any(_overlaps((gs, ge), (f["start"], f["end"])) for f in found):
                continue
            raw = text[a:b]
            is_target = kind == "person" and match is not None and match.fullmatch(raw)
            found.append({"start": gs, "end": ge, "raw": raw, "source": src,
                          "kind": "target" if is_target else
                          ("masked" if kind == "person" and re.search(MASK_RUN, raw) else
                           "plain" if kind == "person" else kind)})
    return sorted(found, key=lambda m: m["start"])


def packet_text(packet: dict, start: int, end: int) -> str:
    for view in packet["visible_spans"]:
        if view["start"] <= start and end <= view["start"] + len(view["quote"]):
            return view["quote"][start - view["start"]:end - view["start"]]
    return ""
