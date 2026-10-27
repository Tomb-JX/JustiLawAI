"""Label model: combine LF votes into a probability per candidate without any gold (Dawid–Skene EM).

Each LF (or a group of LFs from the same source) is a noisy annotator with a class-conditional
distribution over its outcomes. Abstaining is an outcome too: an LF that only ever votes YES
is informative through how often it fires on true and false candidates. LFs known to share a
source are one factor with a joint outcome (the two nearest-person layers, the two dependency
parsers, the three binding-v1 routes, the two LLMs), so their agreement is not counted as
independent evidence. EM alternates: E-step, posterior of each candidate from the current
annotator tables; M-step, class prior and tables from the posteriors (add-alpha smoothing).
A factor marked missing for a row (no LLM answer for that record) is left out of that row.
"""
from __future__ import annotations

import math
from collections import defaultdict

import labeling_functions as L

JOINT = (("nearest_regex", "nearest_ner"), ("tree_hanlp", "tree_ltp"),
         ("v1_chain", "v1_softmax", "v1_pair"), ("llm_qwen", "llm_deepseek"))


def factors(lfs: list[L.LF], task: str, use_llm: bool) -> list[tuple[str, ...]]:
    names = [n for n, t, g, _f in lfs if t == task and (use_llm or g != "llm")]
    out, used = [], set()
    for group in JOINT:
        members = tuple(f"{task[0]}_{g}" for g in group if f"{task[0]}_{g}" in names)
        if members:
            out.append(members)
            used.update(members)
    return out + [(n,) for n in names if n not in used]


def _is_llm(factor: tuple[str, ...]) -> bool:
    return "_llm_" in factor[0]


def outcomes(row: dict, facs: list[tuple[str, ...]], llm_ids: set[str]) -> list[tuple | None]:
    return [None if _is_llm(f) and row["id"] not in llm_ids else tuple(row["votes"][n] for n in f) for f in facs]


def majority(row: dict, names: list[str]) -> float:
    v = [row["votes"][n] for n in names if row["votes"][n] != L.ABSTAIN]
    return sum(x == L.YES for x in v) / len(v) if v else 0.0


class DawidSkene:
    def __init__(self, facs: list[tuple[str, ...]], alpha: float = 1.0, iters: int = 200):
        self.facs, self.alpha, self.iters = facs, alpha, iters

    def _post(self, obs: list[tuple | None]) -> float:
        logit = [math.log(self.prior[c]) for c in (0, 1)]
        for k, o in enumerate(obs):
            if o is None:
                continue
            for c in (0, 1):
                n = self.counts[k][c]
                logit[c] += math.log((n.get(o, 0.0) + self.alpha) / (self.total[k][c] + self.alpha * self.kinds[k]))
        m = max(logit)
        e = [math.exp(x - m) for x in logit]
        return e[1] / (e[0] + e[1])

    def fit(self, obs: list[list[tuple | None]], init: list[float]) -> "DawidSkene":
        q = list(init)
        self.kinds = [len({o[k] for o in obs if o[k] is not None}) + 1 for k in range(len(self.facs))]
        for _ in range(self.iters):
            p1 = sum(q) / len(q)
            self.prior = {0: max(1 - p1, 1e-6), 1: max(p1, 1e-6)}
            self.counts = [{0: defaultdict(float), 1: defaultdict(float)} for _ in self.facs]
            self.total = [{0: 0.0, 1: 0.0} for _ in self.facs]
            for o, w in zip(obs, q):
                for k, x in enumerate(o):
                    if x is None:
                        continue
                    for c, wc in ((0, 1 - w), (1, w)):
                        self.counts[k][c][x] += wc
                        self.total[k][c] += wc
            new = [self._post(o) for o in obs]
            delta = max(abs(a - b) for a, b in zip(new, q))
            q = new
            if delta < 1e-6:
                break
        return self

    def predict(self, obs: list[list[tuple | None]]) -> list[float]:
        return [self._post(o) for o in obs]
