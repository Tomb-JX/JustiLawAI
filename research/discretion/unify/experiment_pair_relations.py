"""Person–amount relation classification on model-draft pair labels.

Reference: A/B agreement per (record, amount, person); disagreements go to the
blind C vote by strict majority; otherwise unresolved and unscored. Classes:
holds / each_share / gives / receives / none (uncertain is never a label).

Feature groups share examples, learner and folds:
  lexical  distance, nearest-person status and cue words between person and amount
  parser   semantic-dependency / dependency paths and SRL roles from a parser cache
Development = event-level 5-fold CV on the development batches; `holdout` scores
a frozen model once on the holdout batch. Derived amount ownership (target /
other / shared) is reported for comparison with the earlier 3-way owner model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from audit_supply_replay import rows
from experiment_joint_amount_roles import Softmax
from experiment_relation_edges import amounts_of, label_path
from experiment_selective_binding import event_fold
from ownership import CLAUSE, SENTENCE, bounds
from supply_packet import build_packet

CLASSES = ("holds", "each_share", "gives", "receives", "none")
PROVIDERS, ARBITER = ("bailian", "deepseek"), "kimi"
CUES = {
    "possess": ("持有", "携带", "身上", "赌资", "下注", "押注", "投注", "拿", "出资"),
    "toward": ("向", "给", "转给", "交给", "输给", "付给"),
    "from": ("从", "被", "收取", "收", "骗", "诈骗", "抽头", "抽取", "赢"),
    "transfer": ("转账", "充值", "支付", "微信", "支付宝", "红包"),
    "distributive": ("每人", "各自", "分别", "均", "各"),
    "total": ("共", "合计", "累计", "总计", "现场", "查获", "缴获", "收缴"),
    "win_loss": ("输", "赢", "输掉", "赢了"),
}


# ---------- references ----------

def vote(values: list[str]) -> str | None:
    top, n = Counter(values).most_common(1)[0]
    return top if n * 2 > len(values) else None


def load_pairs(batch: Path, labels: Path, split: str, require_labels: bool = True,
               arbiter: str = ARBITER) -> list[dict]:
    """One item per record with amounts: packet, person proposals and per-pair consensus.

    With require_labels=False, unlabelled records still yield items (persons from the
    same recogniser, no pair labels) so a frozen model can predict them.
    """
    from run_pair_relation_labels import persons_of
    items = []
    for record in rows(batch / "inputs.jsonl"):
        drafts = {}
        for name in PROVIDERS + (arbiter,):
            path = label_path(labels, record["id"], name)
            if path is not None:
                drafts[name] = json.loads(path.read_text("utf-8"))
        packet = build_packet(record["text_full"], record, record_id=record["id"])
        if not any(p in drafts for p in PROVIDERS):
            if require_labels or not amounts_of(packet):
                continue
            items.append({"id": record["id"], "record": record, "packet": packet,
                          "persons": persons_of(packet, record), "pairs": {}, "is_target": {}, "scene": {},
                          "split": split, "event": record["event_cluster_id"], "batch": batch.name,
                          "ab_complete": False})
            continue
        persons = next(iter(drafts.values()))["persons"]
        rel = {}
        for name, d in drafts.items():
            for a in d["annotation"]["amounts"]:
                for l in a["links"]:
                    rel.setdefault((a["candidate_id"], l["person_id"]), {})[name] = l["relation"]
        pairs = {}
        for key, votes in rel.items():
            ab = [votes[p] for p in PROVIDERS if p in votes]
            if len(ab) == 2 and ab[0] == ab[1]:
                label = ab[0]
            elif arbiter in votes and len(votes) >= 2:
                label = vote(list(votes.values()))
            else:
                label = None
            pairs[key] = label if label in CLASSES else None
        is_target = {}
        for p in persons:
            v = [d["annotation"]["persons"][i]["is_target"] for d in drafts.values()
                 for i, x in enumerate(d["annotation"]["persons"]) if x["person_id"] == p["person_id"]]
            is_target[p["person_id"]] = vote(v) if v else None
        scene = {}
        for a in amounts_of(packet):
            v = [x["scene_total"] for d in drafts.values() for x in d["annotation"]["amounts"]
                 if x["candidate_id"] == a["candidate_id"]]
            scene[a["candidate_id"]] = vote(v) if v else None
        items.append({"id": record["id"], "record": record, "packet": packet, "persons": persons,
                      "pairs": pairs, "is_target": is_target, "scene": scene, "split": split,
                      "event": record["event_cluster_id"], "batch": batch.name,
                      "ab_complete": all(p in drafts for p in PROVIDERS)})
    return items


# ---------- lexical features ----------

def view_of(packet: dict, start: int) -> dict:
    return next(v for v in packet["visible_spans"] if v["start"] <= start < v["end"])


def lexical(it: dict, q: dict, person: dict) -> dict[str, float]:
    view = view_of(it["packet"], q["start"])
    text, base = view["quote"], view["start"]
    a = q["start"] - base
    cl, cr = bounds(text, a, CLAUSE)
    sl, sr = bounds(text, a, SENTENCE)
    mentions = [(s - base, e - base) for s, e in person["mentions"] if base <= s and e <= base + len(text)]
    x = {"kind:" + ("target" if person["kind"] == "target" else person["kind"].split(":")[0]): 1.0}
    if person["kind"].startswith("role:"):
        x["role:" + person["kind"][5:]] = 1.0
    in_sentence = [(s, e) for s, e in mentions if sl <= s and e <= sr]
    if not in_sentence:
        x["same_sentence:False"] = 1.0
        return x
    x["same_sentence:True"] = 1.0
    left = [(s, e) for s, e in in_sentence if e <= a]
    right = [(s, e) for s, e in in_sentence if s >= q["end"] - base]
    near = left[-1] if left else None
    x["has_left:" + str(bool(left))] = 1.0
    x["has_right:" + str(bool(right))] = 1.0
    x["same_clause:" + str(any(cl <= s and e <= cr for s, e in in_sentence))] = 1.0
    others = [(s, e) for p in it["persons"] if p is not person for s, e in
              [(s - base, e - base) for s, e in p["mentions"]] if sl <= s and e <= sr]
    if near:
        gap = text[near[1]:a]
        d = len(gap)
        x["left_dist:" + ("0-3" if d <= 3 else "4-10" if d <= 10 else "11-25" if d <= 25 else "26+")] = 1.0
        x["nearest_left_person:" + str(not any(near[1] <= s < a for s, _ in others))] = 1.0
        x["gap_has_clause_break:" + str(bool(CLAUSE.search(gap)))] = 1.0
        for name, cues in CUES.items():
            if any(c in gap for c in cues):
                x["gap:" + name] = 1.0
                x["gap:" + name + ":near" + str(d <= 10)] = 1.0
    if right:
        gap = text[q["end"] - base:right[0][0]]
        d = len(gap)
        x["right_dist:" + ("0-3" if d <= 3 else "4-10" if d <= 10 else "11+")] = 1.0
        for name, cues in CUES.items():
            if any(c in gap for c in cues):
                x["rgap:" + name] = 1.0
    left_ctx = text[max(0, a - 6):a]
    for name, cues in CUES.items():
        if any(c in left_ctx for c in cues):
            x["amount_left:" + name] = 1.0
    x["others_in_sentence:" + str(min(3, len({p["person_id"] for p in it["persons"] if p is not person and any(
        sl <= s - base and e - base <= sr for s, e in p["mentions"])})))] = 1.0
    return x


# ---------- parser features (optional cache) ----------

class ParseCache:
    """Content-addressed parser output: key = sha256(view text); tokens with char offsets."""

    def __init__(self, path: Path | None):
        self.docs = {}
        if path and path.exists():
            for r in rows(path):
                self.docs[r["key"]] = r

    def __bool__(self) -> bool:
        return bool(self.docs)

    def get(self, view: dict) -> dict | None:
        return self.docs.get(hashlib.sha256(view["quote"].encode("utf-8")).hexdigest())


def token_at(doc: dict, offset: int) -> int | None:
    for i, (s, e) in enumerate(doc["offsets"]):
        if s <= offset < e:
            return i
    return None


def head_token(doc: dict, start: int, end: int) -> int | None:
    """Last token overlapping the span (Chinese NP/QP heads are rightmost)."""
    idx = [i for i, (s, e) in enumerate(doc["offsets"]) if s < end and e > start]
    return idx[-1] if idx else None


def graph_path(arcs: list[tuple[int, int, str]], a: int, b: int, limit: int = 6) -> list[str] | None:
    """Shortest labelled path a→b over undirected arcs (dep, head, label); ↑ = to head, ↓ = to dependent."""
    adj: dict[int, list[tuple[int, str]]] = {}
    for dep, head, label in arcs:
        adj.setdefault(dep, []).append((head, "↑" + label))
        adj.setdefault(head, []).append((dep, "↓" + label))
    frontier, seen = [(a, [])], {a}
    while frontier:
        nxt = []
        for node, path in frontier:
            if node == b:
                return path
            if len(path) >= limit:
                continue
            for to, lab in adj.get(node, []):
                if to not in seen:
                    seen.add(to)
                    nxt.append((to, path + [lab]))
        frontier = nxt
    return None


def parser(it: dict, q: dict, person: dict, cache: ParseCache) -> dict[str, float]:
    view = view_of(it["packet"], q["start"])
    doc = cache.get(view)
    if not doc:
        return {"parse:missing": 1.0}
    base = view["start"]
    qa = head_token(doc, q["start"] - base, q["end"] - base)
    x = {}
    best = None
    for s, e in person["mentions"]:
        if not (base <= s and e <= base + len(view["quote"])):
            continue
        pa = head_token(doc, s - base, e - base)
        if qa is None or pa is None or doc["sent_of"][pa] != doc["sent_of"][qa]:
            continue
        for rank, layer in enumerate(("sdp", "dep")):
            path = graph_path(doc[layer], qa, pa)
            # Semantic dependency first, then syntax; shorter paths across mentions of the same person.
            if path is not None and (best is None or (rank, len(path)) < best[:2]):
                best = (rank, len(path), layer, path)
        for frame in doc.get("srl", []):
            roles = {}
            for role, ts, te in frame["args"]:
                if ts <= qa <= te:
                    roles["amount"] = role
                if ts <= pa <= te:
                    roles["person"] = role
            if len(roles) == 2:
                pred = doc["tokens"][frame["pred"]]
                x[f"srl:{roles['person']}|{roles['amount']}"] = 1.0
                x[f"srl_pred:{pred}|{roles['person']}"] = 1.0
    if best is None:
        x["parse:no_path"] = 1.0
        return x
    layer, path = best[2], best[3]
    if not path:
        x["parse:same_token"] = 1.0
        return x
    labels = [p[1:] for p in path]
    x[f"{layer}:len:{min(len(path), 5)}"] = 1.0
    x[f"{layer}:first:{path[0]}"] = 1.0
    x[f"{layer}:last:{path[-1]}"] = 1.0
    x[f"{layer}:path:{'/'.join(path[:4])}"] = 1.0
    for lab in labels:
        x[f"{layer}:has:{lab}"] = 1.0
    return x


# ---------- learning ----------

def examples(items: list[dict], fn) -> list[tuple[dict, str, dict]]:
    out = []
    for it in items:
        persons = {p["person_id"]: p for p in it["persons"]}
        quantities = {q["candidate_id"]: q for q in amounts_of(it["packet"])}
        for (qid, pid), label in it["pairs"].items():
            if label is None or qid not in quantities or pid not in persons:
                continue
            out.append((fn(it, quantities[qid], persons[pid]), label,
                        {"id": it["id"], "q": qid, "p": pid, "event": it["event"]}))
    return out


def metrics(pairs: list[tuple[str, str]]) -> dict:
    c = Counter(pairs)
    out = {"n": len(pairs), "accuracy": round(sum(v for (y, p), v in c.items() if y == p) / max(1, len(pairs)), 3)}
    f1s = []
    for k in CLASSES:
        tp, pred = c[(k, k)], sum(v for (_, p), v in c.items() if p == k)
        gold = sum(v for (y, _), v in c.items() if y == k)
        pr, rc = (tp / pred if pred else 0.0), (tp / gold if gold else 0.0)
        f = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        f1s.append(f)
        out[k] = {"gold": gold, "pred": pred, "p": round(pr, 3), "r": round(rc, 3), "f1": round(f, 3)}
    out["macro_f1"] = round(sum(f1s) / len(f1s), 3)
    # The relation that decides ownership: is this person a holder (holds / each_share) of the amount?
    hold = {"holds", "each_share"}
    tp = sum(v for (y, p), v in c.items() if y in hold and p in hold)
    fp = sum(v for (y, p), v in c.items() if y not in hold and p in hold)
    fn = sum(v for (y, p), v in c.items() if y in hold and p not in hold)
    out["holder_edge"] = {"p": round(tp / (tp + fp), 3) if tp + fp else None,
                          "r": round(tp / (tp + fn), 3) if tp + fn else None,
                          "f1": round(2 * tp / (2 * tp + fp + fn), 3) if tp else 0.0}
    return out


FEATURE_SETS = ("lexical", "parser", "lexical+parser")


def feature_fn(name: str, cache: ParseCache):
    if name == "lexical":
        return lexical
    if name == "parser":
        return lambda it, q, p: {**{"k:" + k: v for k, v in lexical(it, q, p).items() if k.startswith(("kind:", "role:"))},
                                 **parser(it, q, p, cache)}
    return lambda it, q, p: {**lexical(it, q, p), **parser(it, q, p, cache)}


def cross_validate(dev: list[dict], fn) -> tuple[list[tuple[str, str]], list[dict]]:
    ex = examples(dev, fn)
    pairs, rows_out = [], []
    for k in range(5):
        train = [e for e in ex if event_fold(e[2]["event"]) != k]
        held = [e for e in ex if event_fold(e[2]["event"]) == k]
        model = Softmax(CLASSES)
        model.fit([(x, y) for x, y, _ in train])
        for x, y, meta in held:
            p = model.predict(x)
            pred = max(p, key=p.get)
            pairs.append((y, pred))
            rows_out.append({**meta, "label": y, "pred": pred, "probs": {c: round(v, 4) for c, v in p.items()}})
    return pairs, rows_out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("develop", "holdout"))
    ap.add_argument("--dev", type=Path, nargs=2, action="append", default=[], metavar=("BATCH", "LABELS"))
    ap.add_argument("--test", type=Path, nargs=2, metavar=("BATCH", "LABELS"))
    ap.add_argument("--parse-cache", type=Path)
    ap.add_argument("--features", default=",".join(FEATURE_SETS))
    ap.add_argument("--artifact", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("output_already_exists")
    cache = ParseCache(args.parse_cache)
    dev = [it for b, l in args.dev for it in load_pairs(b, l, "dev")]
    names = [n for n in args.features.split(",") if cache or n == "lexical"]
    report = {"scope": args.stage, "reference": "model-draft pair majority (not human gold)",
              "dev_records": len(dev), "parse_cache_docs": len(cache.docs),
              "label_counts": dict(Counter(l for it in dev for l in it["pairs"].values() if l)), "features": {}}
    if args.stage == "develop":
        for name in names:
            pairs, preds = cross_validate(dev, feature_fn(name, cache))
            report["features"][name] = metrics(pairs)
            args.out.with_suffix(f".{name.replace('+', '_')}.preds.jsonl").write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in preds), "utf-8")
    else:
        test = load_pairs(args.test[0], args.test[1], "holdout")
        report["holdout_records"] = len(test)
        for name in names:
            fn = feature_fn(name, cache)
            model = Softmax(CLASSES)
            model.fit([(x, y) for x, y, _ in examples(dev, fn)])
            ex = examples(test, fn)
            pairs = []
            for x, y, _ in ex:
                p = model.predict(x)
                pairs.append((y, max(p, key=p.get)))
            report["features"][name] = metrics(pairs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({n: {k: v[k] for k in ("n", "accuracy", "macro_f1", "holder_edge")}
                      for n, v in report["features"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
