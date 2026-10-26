"""Parse exported jobs with HanLP or LTP (runs in the isolated NLP environment).

Each job text is split into sentences (offsets kept); tokens are aligned back to
character offsets. Output is normalised across toolkits to one record per job:
tokens, offsets, sent_of, dep/sdp arcs as [dependent, head, label] over global
token indices (root arcs dropped), srl frames {pred, args: [[role, start, end]]}
with inclusive token ranges, and ner spans. Appends to a content-addressed cache
and skips keys already present, so reruns are incremental.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

SPLIT = re.compile(r"[^。；;！？!?\n]+[。；;！？!?]?")
MAX_SENT = 200


def sentences(text: str) -> list[tuple[int, str]]:
    out = []
    for m in SPLIT.finditer(text):
        s, piece = m.start(), m.group(0)
        while len(piece) > MAX_SENT:
            cut = piece.rfind("，", 0, MAX_SENT)
            cut = cut + 1 if cut > 20 else MAX_SENT
            out.append((s, piece[:cut]))
            s, piece = s + cut, piece[cut:]
        if piece.strip():
            out.append((s, piece))
    return out


def align(text: str, start: int, tokens: list[str]) -> list[list[int]] | None:
    pos, out = start, []
    for tok in tokens:
        found = text.find(tok, pos)
        if found < 0 or found - pos > 3:
            return None
        out.append([found, found + len(tok)])
        pos = found + len(tok)
    return out


def hanlp_parser():
    import hanlp
    nlp = hanlp.load(hanlp.pretrained.mtl.CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_BASE_ZH)

    def run(sents: list[str]) -> list[dict]:
        doc = nlp(sents, tasks=["tok/fine", "ner/msra", "srl", "dep", "sdp"])
        out = []
        for i in range(len(sents)):
            toks = doc["tok/fine"][i]
            dep = [[j, h - 1, r] for j, (h, r) in enumerate(doc["dep"][i]) if h > 0]
            sdp = [[j, h - 1, r] for j, heads in enumerate(doc["sdp"][i]) for h, r in heads if h > 0]
            srl = []
            for frame in doc["srl"][i]:
                pred = next((s for _, role, s, e in frame if role == "PRED"), None)
                if pred is not None:
                    srl.append({"pred": pred, "args": [[role, s, e - 1] for _, role, s, e in frame if role != "PRED"]})
            ner = [[t, s, e - 1] for _, t, s, e in doc["ner/msra"][i]]
            out.append({"tokens": toks, "dep": dep, "sdp": sdp, "srl": srl, "ner": ner})
        return out
    return run, "hanlp@CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_BASE_ZH"


def ltp_parser():
    import torch
    from ltp import LTP
    nlp = LTP("LTP/base")
    if torch.cuda.is_available():
        nlp.to("cuda")

    def run(sents: list[str]) -> list[dict]:
        res = nlp.pipeline(sents, tasks=["cws", "pos", "ner", "srl", "dep", "sdpg"])
        out = []
        for i in range(len(sents)):
            dep = [[j, h - 1, r] for j, (h, r) in enumerate(zip(res.dep[i]["head"], res.dep[i]["label"])) if h > 0]
            sdp = [[d - 1, h - 1, r] for d, h, r in res.sdpg[i] if h > 0]
            srl = [{"pred": f["index"], "args": [[role, s, e] for role, _, s, e in f["arguments"]]} for f in res.srl[i]]
            ner = [[t, s, e] for t, _, s, e in res.ner[i]]
            out.append({"tokens": res.cws[i], "dep": dep, "sdp": sdp, "srl": srl, "ner": ner})
        return out
    return run, "ltp@LTP/base"


def merge(text: str, sents: list[tuple[int, str]], parsed: list[dict]) -> dict | None:
    doc = {"tokens": [], "offsets": [], "sent_of": [], "dep": [], "sdp": [], "srl": [], "ner": []}
    for k, ((start, sent), p) in enumerate(zip(sents, parsed)):
        offsets = align(text, start, p["tokens"])
        if offsets is None:
            return None
        base = len(doc["tokens"])
        doc["tokens"] += p["tokens"]
        doc["offsets"] += offsets
        doc["sent_of"] += [k] * len(p["tokens"])
        doc["dep"] += [[d + base, h + base, r] for d, h, r in p["dep"]]
        doc["sdp"] += [[d + base, h + base, r] for d, h, r in p["sdp"]]
        doc["srl"] += [{"pred": f["pred"] + base, "args": [[r, s + base, e + base] for r, s, e in f["args"]]}
                       for f in p["srl"]]
        doc["ner"] += [[t, s + base, e + base] for t, s, e in p["ner"]]
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("toolkit", choices=("hanlp", "ltp"))
    ap.add_argument("--jobs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chunk", type=int, default=64)
    args = ap.parse_args()
    run, name = hanlp_parser() if args.toolkit == "hanlp" else ltp_parser()
    done = set()
    if args.out.exists():
        done = {json.loads(l)["key"] for l in args.out.read_text("utf-8").splitlines() if l.strip()}
    jobs = [j for j in (json.loads(l) for l in args.jobs.read_text("utf-8").splitlines() if l.strip())
            if j["key"] not in done]
    started, failed = time.time(), 0
    with args.out.open("a", encoding="utf-8") as f:
        for i in range(0, len(jobs), args.chunk):
            chunk = jobs[i:i + args.chunk]
            split = [sentences(j["text"]) for j in chunk]
            flat = [s for ss in split for _, s in ss]
            parsed = run(flat) if flat else []
            pos = 0
            for job, ss in zip(chunk, split):
                part = parsed[pos:pos + len(ss)]
                pos += len(ss)
                doc = merge(job["text"], ss, part)
                if doc is None:
                    failed += 1
                    continue
                f.write(json.dumps({"key": job["key"], "toolkit": name, **doc}, ensure_ascii=False) + "\n")
            f.flush()
    print(json.dumps({"toolkit": name, "parsed": len(jobs) - failed, "alignment_failed": failed,
                      "skipped_cached": len(done), "seconds": round(time.time() - started, 1)}))


if __name__ == "__main__":
    main()
