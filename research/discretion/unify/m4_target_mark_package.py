"""Copy an M4 training package with the target's own mentions marked in facts_text (E8 fix ①).

M4 reads only `input.facts_text`. When several people of one event get the same facts text,
records with different outcomes are indistinguishable to the model (E8: 22 events / 67 records
in v3-clean). This writes the same package with every literal mention of the record's target
(the S1 `target` and its aliases) replaced by one marker character, so the text says which of
the named people the decision is about. A masked name matches the same surname with the same
number of mask characters in any mask style ("纪**" = "纪xx", "李*" = "李x" but not "李xx"); the
second-person address of a notice ("你伙同他人…你的赌资") is the target too. Nothing else changes: same ids,
splits, labels and metadata; the marker is a plain character, not a feature column.

The target map (id -> target, aliases) comes from the S1 inputs the records were cut from.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

MARK = "Ⓣ"
SPLITS = ("train", "old168", "lake706_valid70", "p3p7_valid119")


MASK = "xX×*＊ｘ某"
_RUN = re.compile(f"([{re.escape(MASK)}]+)")
_SECOND_PERSON = "你(?![们好])"


def surfaces(target: str, aliases: list[str]) -> list[str]:
    """Regex per surface of the target, longest first; spaced aliases ("李 x 军") also unspaced.
    A mask run of n characters matches exactly n mask characters of any style."""
    names = set()
    for name in [target, *aliases]:
        for s in (name or "", re.sub(r"\s+", "", name or "")):
            if len(s) >= 2:
                names.add(s)
    out = []
    for name in sorted(names, key=len, reverse=True):
        body = "".join(f"[{re.escape(MASK)}]{{{len(part)}}}" if _RUN.fullmatch(part) else re.escape(part)
                       for part in _RUN.split(name) if part)
        out.append(f"(?<![{re.escape(MASK)}]){body}(?![{re.escape(MASK)}])" if _RUN.search(name) else body)
    return out


def mark(text: str, names: list[str]) -> tuple[str, int]:
    pattern = re.compile("|".join([*names, _SECOND_PERSON]))
    return pattern.subn(MARK, text)


def collisions(rows: list[dict], key) -> int:
    """Records in events where one facts text carries more than one outcome."""
    groups = defaultdict(lambda: defaultdict(set))
    for r in rows:
        t = r["target"]
        groups[r["event_id"]][key(r)].add((t["type"], t["detention_days"], t["fine"]))
    return sum(1 for r in rows if len(groups[r["event_id"]][key(r)]) > 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True, help="JSON: id -> [[target, [aliases]], ...]")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    targets = json.loads(args.targets.read_text("utf-8"))
    args.out.mkdir(parents=True)
    stats, hashes = {}, {}
    for split in SPLITS:
        rows = [json.loads(l) for l in (args.package / f"{split}.jsonl").read_text("utf-8").splitlines() if l.strip()]
        c = Counter()
        before = collisions(rows, lambda r: r["input"]["facts_text"])
        out = []
        for r in rows:
            entries = targets.get(r["id"]) or []
            names = {e[0] for e in entries}
            if len(names) != 1:
                c["target_unknown_or_conflicting"] += 1
                out.append(r)
                continue
            aliases = sorted({a for e in entries for a in e[1]})
            text, n = mark(r["input"]["facts_text"], surfaces(next(iter(names)), aliases))
            c["marked" if n else "target_not_in_facts"] += 1
            out.append({**r, "input": {**r["input"], "facts_text": text}})
        after = collisions(out, lambda r: r["input"]["facts_text"])
        path = args.out / f"{split}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), "utf-8")
        hashes[f"{split}.jsonl"] = hashlib.sha256(path.read_bytes()).hexdigest()
        stats[split] = {"records": len(rows), **dict(c), "collision_records_before": before,
                        "collision_records_after": after}
    parent = json.loads((args.package / "manifest.json").read_text("utf-8"))
    manifest = {**parent, "parent_package": {"path": str(args.package),
                                             "manifest_sha256": hashlib.sha256((args.package / "manifest.json").read_bytes()).hexdigest()},
                "transform": {"name": "target_mark", "marker": MARK, "source": "S1 target + aliases, literal match",
                              "targets_sha256": hashlib.sha256(args.targets.read_bytes()).hexdigest()},
                "transform_stats": stats, "outputs": hashes}
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
