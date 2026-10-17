"""仲裁模块（协同指令 §5，金标线解散后由网页线吸收；D-002 方法学继续有效）。

裁决协议（沿用金标 merge_arbitration.py 的台账风格，采纳值按三方改写）：
  adopt ∈ {A=S1产出, B=历史锚(regex), C=裁判模型, new, unresolved}
  每条决定：{id, field, adopt, value, status: 明确|推断|未提及, evidence, reason_code, reason}

两条硬规则（写死在代码里，不靠自觉）：
1. **法律锚优先**：常量表判死的值，仲裁不得复活——fine/detention_days 对照 legal_caps，
   越限方直接判死；一方存活→自动采纳存活方（reason_code=legal_anchor，不调模型）；
   双方均越限→unresolved。
2. **模型隔离（D-002）**：裁判模型不得为生成方（deepseek），白名单 qwen3.8-max / kimi-k3。

用法：
  python research/discretion/unify/arbitrate.py --batch <parsed-1> --run <s1_run> \
      --divergences <anchor_compare 输出 csv> [--referee bailian-max] [--out dir]
产物（s1_runs/<run>/arbitration/）：decisions.jsonl、arbitration_stats.json、receipts.jsonl。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from progress import ProgressTracker  # noqa: E402  监控心跳（裁判调用也留进度）

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1 import Provider, load_config  # noqa: E402
from s3 import PENALTY_CAPS, ART16_DETENTION_MAX  # noqa: E402
from anchor_compare import s1_values, anchor_values, comparable, equal  # noqa: E402

ARBITER_MODEL_WHITELIST = {"qwen3.8-max", "kimi-k3", "mimo-v2.6-pro", "mimo-v2.6-flash"}
# 2026-10-18 用户改令：双标/仲裁弃用百炼（账户 400 待恢复），改用小米 MiMo v2.6（pro 为裁判档）；
# D-002 隔离纪律不变——裁判≠生成方（deepseek），白名单登记非 deepseek 系模型。
CAP_FIELDS = {"fine", "detention_days"}
REFEREE_PROMPT = """同一份行政处罚文书的一个字段出现两个不同的抽取值，请依正文裁决。

字段：{field}
候选 A：{a}
候选 B：{b}
正文：
{text}

规则：以正文逐字证据为准；正文没有的记"未提及"；两候选都错时给出正文支持的新值。
只输出 JSON：{{"adopt": "A|B|未提及|新值", "value": <裁决值或null>, "status": "明确|推断",
"evidence": ["逐字证据片段"], "reason": "一句话理由"}}"""


class IsolationError(AssertionError):
    """D-002 模型隔离违规。"""


def check_isolation(provider: Provider) -> None:
    if provider.name == "deepseek":
        raise IsolationError("D-002 模型隔离：仲裁/裁判模型不得为生成方 deepseek")
    if provider.model not in ARBITER_MODEL_WHITELIST:
        raise IsolationError(f"D-002 模型隔离：裁判模型 {provider.model} 不在白名单 {sorted(ARBITER_MODEL_WHITELIST)}")


def legal_anchor(field: str, a, b) -> tuple[str, object, str] | None:
    """法律锚优先：返回 (adopt, value, reason_code) 或 None（不适用，走裁判）。"""
    if field not in CAP_FIELDS:
        return None
    edition_caps = list(PENALTY_CAPS.values())
    ref_det = min(c["detention"] for c in edition_caps) if edition_caps else 15
    ref_fine = min(c["fine"] for c in edition_caps) if edition_caps else 3000

    def dead(v):
        try:
            x = float(v or 0)
        except (TypeError, ValueError):
            return True
        if field == "detention_days":
            return x > ART16_DETENTION_MAX or x > ref_det
        return x > ref_fine

    da, db = dead(a), dead(b)
    if da and not db:
        return ("B", b, "legal_anchor")
    if db and not da:
        return ("A", a, "legal_anchor")
    if da and db:
        return ("unresolved", None, "legal_anchor_both_violate")
    return None


class Arbitrator:
    def __init__(self, provider: Provider, run_dir: Path):
        check_isolation(provider)   # D-002 断言：构造即校验，隔离违规直接崩
        self.provider = provider
        self.path = run_dir / "receipts.jsonl"
        self._lock = threading.Lock()

    def receipt(self, **kw):
        kw["ts"] = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def referee(self, rec_id: str, field: str, a, b, text: str) -> dict:
        """裁判模型重抽裁决（候选 C）。"""
        content, meta = self.provider.chat(
            "只输出一个 JSON 对象。",
            REFEREE_PROMPT.format(field=field, a=json.dumps(a, ensure_ascii=False),
                                  b=json.dumps(b, ensure_ascii=False), text=text[:4000]))
        self.receipt(event="referee", provider=self.provider.name, model=self.provider.model,
                     id=rec_id, field=field, status="ok", **meta)
        out = json.loads(content)
        adopt = out.get("adopt")
        if adopt == "A":
            value, code = a, "referee_adopt_a"
        elif adopt == "B":
            value, code = b, "referee_adopt_b"
        elif adopt == "未提及":
            value, code = None, "referee_not_mentioned"
        else:   # 新值
            value, code = out.get("value"), "referee_new_value"
        return {"adopt": "C" if adopt not in ("A", "B") else adopt,
                "value": value, "status": out.get("status") or "推断",
                "evidence": out.get("evidence") or [], "reason_code": code,
                "reason": out.get("reason") or ""}


def resolve(arb: Arbitrator | None, rec: dict, s1_out: dict, div: dict) -> dict:
    """单条分歧的裁决：法律锚 → 裁判模型（如有）→ unresolved。"""
    rid, field = div["id"], div["field"]
    a = json.loads(div["s1"])
    b = json.loads(div["anchor"])
    la = legal_anchor(field, a, b)
    if la:
        adopt, value, code = la
        return {"id": rid, "field": field, "adopt": adopt, "value": value,
                "status": "明确", "evidence": [], "reason_code": code,
                "reason": "常量表判死越限值（法律锚优先，未调模型）"}
    if arb is None:
        return {"id": rid, "field": field, "adopt": "unresolved", "value": None,
                "status": "未提及", "evidence": [], "reason_code": "no_referee",
                "reason": "未启用裁判模型"}
    text = rec.get("text_full") or rec.get("cleaned_text") or ""
    try:
        return {"id": rid, "field": field, **arb.referee(rid, field, a, b, text)}
    except Exception as e:
        arb.receipt(event="referee", id=rid, field=field, status="fail", error=str(e)[:200])
        return {"id": rid, "field": field, "adopt": "unresolved", "value": None,
                "status": "未提及", "evidence": [], "reason_code": "referee_error",
                "reason": str(e)[:120]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="parsed-1 records.jsonl（历史锚来源）")
    ap.add_argument("--run", required=True, help="s1_runs/<id>")
    ap.add_argument("--divergences", required=True, help="anchor_compare 的 divergences.csv")
    ap.add_argument("--referee", default="", help="裁判提供商名（config 键，如 bailian-max）；空=不调模型")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    providers, _cfg, _ = load_config()
    out_dir = Path(a.run) / "arbitration"
    out_dir.mkdir(exist_ok=True)
    arb = None
    if a.referee:
        arb = Arbitrator(providers[a.referee], out_dir)

    recs = {r["id"]: r for r in (json.loads(l) for l in open(a.batch, encoding="utf-8"))}
    outs = {json.loads(l)["id"]: json.loads(l)
            for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8") if json.loads(l).get("ok")}
    divs = list(csv.DictReader(open(a.divergences, encoding="utf-8-sig")))

    decisions = []
    tracker = ProgressTracker(out_dir, total=len(divs),
                              meta={"phase_scope": "arbitration", "referee": a.referee or "none"})
    with ThreadPoolExecutor(max_workers=a.workers if arb else 1) as ex:
        futs = {}
        for d in divs:
            rec = recs.get(d["id"]) or {}
            o = outs.get(d["id"])
            if o is None:
                continue
            rec = {**rec, "cleaned_text": ""}
            futs[ex.submit(resolve, arb, rec, o, d)] = d
        for fut in as_completed(futs):
            decisions.append(fut.result())
            tracker.finish_record(True, 1, arb.provider.name if arb else "local")
    tracker.set_phase("done")

    with open(out_dir / "decisions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for d in sorted(decisions, key=lambda x: (x["id"], x["field"])):
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    stats = {
        "n_divergences": len(divs), "n_decisions": len(decisions),
        "by_adopt": dict(Counter(d["adopt"] for d in decisions)),
        "by_reason_code": dict(Counter(d["reason_code"] for d in decisions)),
        "by_field": dict(Counter(d["field"] for d in decisions)),
        "referee": f"{arb.provider.name}:{arb.provider.model}" if arb else None,
        "isolation": "D-002 断言通过（裁判≠deepseek，白名单内）" if arb else "未启用裁判",
    }
    (out_dir / "arbitration_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
