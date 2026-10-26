"""Export the frozen pair encoder to ONNX and check parity (runs in the NLP env).

Inputs: input_ids, attention_mask, q_pos, p_pos (int64); output: logits over
CLASSES. Parity: max |softmax(torch) - softmax(onnx)| and argmax agreement on
the given example windows, written next to the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from train_pair_encoder import CLASSES, MARKERS, PairModel, encode


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--examples", type=Path, required=True, help="windows to check parity on")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base", default="hfl/chinese-roberta-wwm-ext")
    ap.add_argument("--max-len", type=int, default=192)
    ap.add_argument("--n-check", type=int, default=512)
    args = ap.parse_args()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model_dir)
    model = PairModel(args.base, len(tok))
    model.load_state_dict(torch.load(args.model_dir / "pair_model.pt", map_location="cpu"))
    model.eval()
    rows = [json.loads(l) for l in args.examples.read_text("utf-8").splitlines() if l.strip()][:args.n_check]
    for r in rows:
        r["label"] = r["label"] or "none"
    ids, mask, q, p, _ = encode(tok, rows[:4], args.max_len)
    args.out.mkdir(parents=True, exist_ok=True)
    onnx_path = args.out / "pair_model.onnx"
    torch.onnx.export(model, (ids, mask, q, p), str(onnx_path), input_names=["input_ids", "attention_mask", "q_pos", "p_pos"],
                      output_names=["logits"], opset_version=17, dynamo=False,
                      dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"},
                                    "q_pos": {0: "b"}, "p_pos": {0: "b"}, "logits": {0: "b"}})
    for name in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.txt"):
        if (args.model_dir / name).exists():
            shutil.copy(args.model_dir / name, args.out / name)
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    diffs, agree = [], 0
    for i in range(0, len(rows), 32):
        chunk = rows[i:i + 32]
        ids, mask, q, p, _ = encode(tok, chunk, args.max_len)
        with torch.no_grad():
            t = torch.softmax(model(ids, mask, q, p), -1).numpy()
        o = sess.run(None, {"input_ids": ids.numpy(), "attention_mask": mask.numpy(),
                            "q_pos": q.numpy(), "p_pos": p.numpy()})[0]
        o = np.exp(o - o.max(-1, keepdims=True))
        o /= o.sum(-1, keepdims=True)
        diffs.append(np.abs(t - o).max())
        agree += int((t.argmax(-1) == o.argmax(-1)).sum())
    meta = {"classes": list(CLASSES), "markers": MARKERS, "max_len": args.max_len, "base": args.base,
            "onnx_sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest(),
            "parity": {"checked": len(rows), "max_abs_prob_diff": float(max(diffs)), "argmax_agree": agree}}
    (args.out / "pair_model.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(meta["parity"]))


if __name__ == "__main__":
    main()
