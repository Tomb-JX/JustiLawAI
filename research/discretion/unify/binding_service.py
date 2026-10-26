"""Binding service v1: frozen, deterministic field binding for gambling penalty notices.

Inference only. Loads a frozen artifact directory (checked against MANIFEST.json),
then for each record: supply packet -> person proposals -> ONNX pair scores ->
field routes -> gating policy:

  person.age                 bound when the date-interval derivation is unique
  persons.participant_count  bound only when an explicit "X人" and a name list give the same
                             number; otherwise the model value is a suggestion for review
  amounts.personal_stake,    bound only when frozen_chain, softmax/semantic and
  amounts.onsite_stake_total softmax/semantic_pair give the same value; all three
                             abstaining is "unresolved: source_absent_candidate";
                             any disagreement is "unresolved: relation_ambiguous"
                             with every method's proposal for human review.

No model is trained here and no LLM is called; same inputs give the same output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

import experiment_pair_integration as integ
from evaluate_relation_model_labels import CHAIN, chain_value, frozen_predictions
from experiment_age_count_closure import age_prediction
from experiment_joint_amount_roles import Softmax, Variant
from experiment_relation_edges import Variant as EdgeVariant, amounts_of, predict_count
from experiment_relation_suite import count_paths
from experiment_silver_supervised_pipeline import SparseLogistic
from export_pair_examples import window
from run_pair_relation_labels import persons_of
from supply_packet import build_packet

VERSION = "binding-v1"
AMOUNT_FIELDS = ("personal_stake", "onsite_stake_total")
ROUTES = ("frozen_chain", "softmax/semantic", "softmax/semantic_pair")
FIELD_PATH = {"personal_stake": "amounts.personal_stake", "onsite_stake_total": "amounts.onsite_stake_total",
              "participant_count": "persons.participant_count", "age": "person.age"}


class PairScorer:
    """ONNX person–amount relation scorer with the training tokenizer and markers."""

    def __init__(self, model_dir: Path, threads: int = 1):
        meta = json.loads((model_dir / "pair_model.meta.json").read_text("utf-8"))
        self.classes, self.max_len = meta["classes"], meta["max_len"]
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(self.max_len)
        # tokenizer.json ships with batch padding enabled; padding is done below with a real mask,
        # otherwise pad tokens of short rows would be attended to inside mixed-length batches.
        self.tok.no_padding()
        self.q_id = self.tok.token_to_id("[额]")
        self.p_ids = {self.tok.token_to_id(m) for m in ("[人:目标]", "[人:他人]", "[人:称谓]")}
        opts = ort.SessionOptions()
        # A fixed thread count keeps CPU kernels reproducible; check_threads verifies a count before use.
        opts.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(str(model_dir / "pair_model.onnx"), opts, providers=["CPUExecutionProvider"])

    def probs(self, texts: list[str], batch: int = 32) -> list[dict[str, float]]:
        out = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i:i + batch])
            width = max(len(e.ids) for e in enc)
            ids = np.zeros((len(enc), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            q = np.zeros(len(enc), dtype=np.int64)
            p = np.zeros(len(enc), dtype=np.int64)
            for j, e in enumerate(enc):
                ids[j, :len(e.ids)] = e.ids
                mask[j, :len(e.ids)] = e.attention_mask
                q[j] = e.ids.index(self.q_id) if self.q_id in e.ids else 0
                p[j] = next((k for k, t in enumerate(e.ids) if t in self.p_ids), 0)
            logits = self.sess.run(None, {"input_ids": ids, "attention_mask": mask, "q_pos": q, "p_pos": p})[0]
            z = np.exp(logits - logits.max(-1, keepdims=True))
            z /= z.sum(-1, keepdims=True)
            out += [dict(zip(self.classes, row.tolist())) for row in z]
        return out


class BindingService:
    def __init__(self, artifacts: Path, engine_root: Path, threads: int = 8):
        self.root, self.engine_root = artifacts, engine_root
        manifest = json.loads((artifacts / "MANIFEST.json").read_text("utf-8"))
        for rel, digest in manifest["files"].items():
            if hashlib.sha256((artifacts / rel).read_bytes()).hexdigest() != digest:
                raise ValueError("artifact_hash_mismatch:" + rel)
        self.manifest_sha256 = hashlib.sha256((artifacts / "MANIFEST.json").read_bytes()).hexdigest()
        routes = json.loads((artifacts / "amount_routes.json").read_text("utf-8"))
        self.routes = {n: (Variant(*n.split("/")), Softmax.load(r["softmax"]), r["thresholds"]) for n, r in routes.items()}
        count = json.loads((artifacts / "participant_count.json").read_text("utf-8"))["fields"]["participant_count"]
        self.count_variant = EdgeVariant("participant_count", count["variant"], [])
        self.count_model = SparseLogistic()
        self.count_model.weights.update(count["weights"])
        self.count_model.bias = count["bias"]
        self.count_threshold = count["threshold"]
        self.pairs = PairScorer(artifacts / "pair-model", threads=threads)

    # ---------- per record ----------

    def _items(self, records: list[dict]) -> list[dict]:
        items = []
        for r in records:
            packet = build_packet(r["text_full"], r, record_id=r["id"])
            items.append({"id": r["id"], "record": r, "packet": packet, "persons": persons_of(packet, r)})
        return items

    def _pair_features(self, items: list[dict]) -> None:
        rows, texts = [], []
        for it in items:
            for q in amounts_of(it["packet"]):
                for p in it["persons"]:
                    rows.append({"id": it["id"], "q": q["candidate_id"], "p": p["person_id"]})
                    texts.append(window(it, q, p)["text"])
        for row, probs in zip(rows, self.pairs.probs(texts)):
            row["probs"] = probs
        integ.PAIR_PROBS.clear()
        integ.summarize_pairs(rows, items)

    def _evidence(self, it: dict, candidate_id: str | None) -> list[dict]:
        q = next((q for q in it["packet"]["quantities"] if q["candidate_id"] == candidate_id), None)
        if q is None:
            return []
        return [{"candidate_id": candidate_id, "start": q["start"], "end": q["end"],
                 "quote": it["record"]["text_full"][q["start"]:q["end"]], "raw": q["raw"]}]

    def bind(self, records: list[dict]) -> list[dict]:
        items = self._items(records)
        self._pair_features(items)
        chain = frozen_predictions(records, self.root / "frozen_chain_amounts.json",
                                   self.root / "frozen_chain_age_count.json", self.engine_root)
        route_preds = {n: v.predict(items, m) for n, (v, m, _) in self.routes.items()}
        out = []
        for it in items:
            rid = it["id"]
            bindings = [self._amount(it, f, chain[rid], route_preds) for f in AMOUNT_FIELDS]
            bindings.append(self._count(it))
            bindings.append(self._age(it))
            out.append({"id": rid, "target": it["record"]["target"], "service_version": VERSION,
                        "artifact_manifest_sha256": self.manifest_sha256, "bindings": bindings})
        return out

    def _amount(self, it: dict, field: str, chain_fields: dict, route_preds: dict) -> dict:
        rid = it["id"]
        out = chain_fields[CHAIN[field]]
        proposals = {"frozen_chain": {"value": chain_value(field, out),
                                      "candidate_id": out.get("candidate_id") if out["status"] == "selected" else None}}
        for name, (_, _, thresholds) in self.routes.items():
            score, key, cid = route_preds[name][rid][field]
            keep = score >= thresholds[field]
            proposals[name] = {"value": key if keep else None, "candidate_id": cid if keep else None,
                               "score": round(float(score), 4)}
        values = {p["value"] for p in proposals.values()}
        base = {"field": FIELD_PATH[field], "target_id": rid, "proposals": proposals}
        if len(values) == 1 and None not in values:
            cid = proposals["softmax/semantic_pair"]["candidate_id"]
            return {**base, "binding_status": "bound", "value": next(iter(values)), "candidate_ids": [cid],
                    "evidence": self._evidence(it, cid), "decision_source": "consensus_of_3_routes",
                    "reason": None}
        if values == {None}:
            # All routes abstained. With amount candidates in the text this is not evidence of absence
            # (H3: 22 personal stakes were silently missed this way), so it goes to review with them.
            amounts = [q["candidate_id"] for q in amounts_of(it["packet"])]
            return {**base, "binding_status": "unresolved", "value": None, "candidate_ids": amounts,
                    "evidence": [e for c in amounts for e in self._evidence(it, c)],
                    "decision_source": "consensus_of_3_routes",
                    "reason": "no_route_output" if amounts else "no_candidate"}
        cids = sorted({p["candidate_id"] for p in proposals.values() if p["candidate_id"]})
        return {**base, "binding_status": "unresolved", "value": None, "candidate_ids": cids,
                "evidence": [e for c in cids for e in self._evidence(it, c)],
                "decision_source": "routes_disagree", "reason": "relation_ambiguous"}

    def _count(self, it: dict) -> dict:
        score, key, ranked = predict_count(it, self.count_model, self.count_variant.fn)
        base = {"field": FIELD_PATH["participant_count"], "target_id": it["id"],
                "decision_source": "count_candidate_nil", "proposals": {"score": round(float(score), 4)}}
        if key is None or score < self.count_threshold:
            return {**base, "binding_status": "unresolved", "value": None, "candidate_ids": [], "evidence": [],
                    "reason": "no_candidate" if key is None else "below_nil_threshold"}
        cid = ranked[0][1]
        value = int(key[4:])
        q = next((q for q in it["packet"]["quantities"] if q["candidate_id"] == cid), None)
        evidence = self._evidence(it, cid) if q else [{"candidate_id": cid, "kind": "name_list"}]
        paths = count_paths(it["packet"], it["record"]["target"], it["record"]["aliases"])
        sources = {k: {p["value"] for p in paths if p["kind"] == k} for k in ("explicit", "list")}
        # Auto-bind only when an explicit "X人" and a name list independently give the same number:
        # the single-source model was 82–83% precise on unseen batches (组织者人数, "伙同X三人" +1 errors).
        if value in sources["explicit"] and value in sources["list"]:
            return {**base, "binding_status": "bound", "value": value, "candidate_ids": [cid],
                    "evidence": evidence, "reason": None, "decision_source": "explicit_and_list_agree"}
        return {**base, "binding_status": "unresolved", "value": None, "candidate_ids": [cid],
                "evidence": evidence, "reason": "single_source_count",
                "proposals": {**base["proposals"], "suggested_value": value}}

    def _age(self, it: dict) -> dict:
        p = age_prediction(it["packet"])
        base = {"field": FIELD_PATH["age"], "target_id": it["id"], "decision_source": "date_interval_derivation"}
        if p["status"] != "selected":
            return {**base, "binding_status": "unresolved", "value": None, "candidate_ids": [], "evidence": [],
                    "reason": p["reason"]}
        ops = [p["birth_operand"], p["event_operand"]]
        return {**base, "binding_status": "bound", "value": p["value"],
                "candidate_ids": [o["candidate_id"] for o in ops],
                "evidence": [e for o in ops for e in self._evidence(it, o["candidate_id"])],
                "derivation": {"operation": "completed_years(birth, event_date)",
                               "consistent_operand_pairs": p["consistent_operand_pairs"]}, "reason": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("artifacts", "engine_root", "inputs", "out"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--chunk", type=int, default=64)
    ap.add_argument("--threads", type=int, default=8, help="ONNX CPU threads (8 verified bitwise equal to 1)")
    args = ap.parse_args()
    service = BindingService(args.artifacts, args.engine_root, threads=args.threads)
    records = [json.loads(l) for l in args.inputs.read_text("utf-8").splitlines() if l.strip()]
    with args.out.open("w", encoding="utf-8") as f:
        for i in range(0, len(records), args.chunk):
            for row in service.bind(records[i:i + args.chunk]):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"records": len(records), "out": str(args.out), "version": VERSION}))


if __name__ == "__main__":
    main()
