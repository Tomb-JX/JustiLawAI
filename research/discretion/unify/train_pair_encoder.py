"""Fine-tune a Chinese encoder on marked person–amount windows (runs in the NLP env).

Typed markers are added as special tokens; the classifier reads the [CLS] state
concatenated with the two opening-marker states (Zhou & Chen's entity-start
representation). `cv` trains on 4 event folds and predicts the 5th, for every
fold; `final` trains on all dev examples and predicts the holdout once.
Seeds and cuDNN determinism are fixed so reruns reproduce the same weights.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer

CLASSES = ("holds", "each_share", "gives", "receives", "none")
MARKERS = ["[额]", "[/额]", "[人:目标]", "[人:他人]", "[人:称谓]", "[/人]", "[无主]"]


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


class PairModel(nn.Module):
    def __init__(self, base: str, n_tokens: int):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(base)
        self.encoder.resize_token_embeddings(n_tokens)
        h = self.encoder.config.hidden_size
        self.head = nn.Sequential(nn.Dropout(0.1), nn.Linear(3 * h, h), nn.Tanh(), nn.Dropout(0.1),
                                  nn.Linear(h, len(CLASSES)))

    def forward(self, ids, mask, q_pos, p_pos):
        hidden = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state
        rows = torch.arange(hidden.size(0), device=hidden.device)
        # A person outside the window points at [CLS]; the classifier sees that as "no mention".
        rep = torch.cat([hidden[:, 0], hidden[rows, q_pos], hidden[rows, p_pos]], dim=-1)
        return self.head(rep)


def encode(tok, rows: list[dict], max_len: int):
    q_id, p_ids = tok.convert_tokens_to_ids("[额]"), {tok.convert_tokens_to_ids(m) for m in MARKERS[2:5]}
    enc = tok([r["text"] for r in rows], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
    q_pos, p_pos = [], []
    for ids in enc["input_ids"].tolist():
        q_pos.append(ids.index(q_id) if q_id in ids else 0)
        p_pos.append(next((i for i, t in enumerate(ids) if t in p_ids), 0))
    labels = torch.tensor([CLASSES.index(r["label"]) if r["label"] in CLASSES else -100 for r in rows])
    return enc["input_ids"], enc["attention_mask"], torch.tensor(q_pos), torch.tensor(p_pos), labels


def train(rows: list[dict], args, device) -> tuple:
    seed_all(args.seed)
    tok = AutoTokenizer.from_pretrained(args.base)
    tok.add_special_tokens({"additional_special_tokens": MARKERS})
    model = PairModel(args.base, len(tok)).to(device)
    data = encode(tok, rows, args.max_len)
    counts = torch.bincount(data[4][data[4] >= 0], minlength=len(CLASSES)).float()
    weight = (counts.sum() / (len(CLASSES) * counts.clamp(min=1))) ** args.class_weight_power
    loss_fn = nn.CrossEntropyLoss(weight=weight.to(device))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    n = len(rows)
    steps = args.epochs * ((n + args.batch - 1) // args.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / max(1, steps // 10)) *
                                              max(0.0, (steps - s) / steps))
    g = torch.Generator().manual_seed(args.seed)
    model.train()
    for _ in range(args.epochs):
        for idx in torch.randperm(n, generator=g).split(args.batch):
            batch = [t[idx].to(device) for t in data]
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(*batch[:4])
            loss = loss_fn(logits.float(), batch[4])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
    return tok, model


@torch.no_grad()
def predict(tok, model, rows: list[dict], args, device) -> list[dict]:
    model.eval()
    out = []
    for i in range(0, len(rows), 64):
        chunk = rows[i:i + 64]
        data = [t.to(device) for t in encode(tok, chunk, args.max_len)]
        probs = torch.softmax(model(*data[:4]).float(), dim=-1).cpu().tolist()
        for r, p in zip(chunk, probs):
            out.append({"id": r["id"], "q": r["q"], "p": r["p"], "label": r["label"],
                        "pred": CLASSES[int(np.argmax(p))], "probs": dict(zip(CLASSES, [round(x, 4) for x in p]))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("cv", "final"))
    ap.add_argument("--examples", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="hfl/chinese-roberta-wwm-ext")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--max-len", type=int, default=192)
    ap.add_argument("--class-weight-power", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=20261026)
    ap.add_argument("--save-model", type=Path)
    args = ap.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    rows = [json.loads(l) for l in args.examples.read_text("utf-8").splitlines() if l.strip()]
    dev = [r for r in rows if r["split"] == "dev"]
    labelled = [r for r in dev if r["label"] in CLASSES]
    preds = []
    if args.stage == "cv":
        for k in range(5):
            tok, model = train([r for r in labelled if r["fold"] != k], args, device)
            preds += predict(tok, model, [r for r in dev if r["fold"] == k], args, device)
            del model
            torch.cuda.empty_cache()
    else:
        tok, model = train(labelled, args, device)
        preds = predict(tok, model, [r for r in rows if r["split"] == "holdout"], args, device)
        if args.save_model:
            args.save_model.mkdir(parents=True, exist_ok=True)
            tok.save_pretrained(args.save_model)
            torch.save(model.state_dict(), args.save_model / "pair_model.pt")
    args.out.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in preds), "utf-8")
    scored = [p for p in preds if p["label"] in CLASSES]
    acc = sum(p["label"] == p["pred"] for p in scored) / max(1, len(scored))
    print(json.dumps({"stage": args.stage, "predictions": len(preds), "accuracy": round(acc, 3),
                      "device": str(device), "config": {k: v for k, v in vars(args).items()
                                                        if k in ("base", "epochs", "batch", "lr", "max_len",
                                                                 "class_weight_power", "seed")}}))


if __name__ == "__main__":
    main()
