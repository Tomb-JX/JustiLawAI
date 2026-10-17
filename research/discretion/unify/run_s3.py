"""S3 运行器：对一份 S1 run 的全部成功输出跑校验注册表 + 多处命中消歧。

用法：
  python research/discretion/unify/run_s3.py --batch <unified_raw/records.jsonl> \
      --run <s1_runs/<run_id>> [--provider deepseek] [--workers 4]

产物（<s1_run>/s3/）：
- findings.jsonl  每记录一行：{id, status: pass|warn|error, findings, locates}
- summary.json    按 校验项×严重级、记录状态、form 分层的分布
- receipts.jsonl  消歧调用回执（掩码）
不做全量回填——回填时机由协调层指示（用户 2026-10-17）。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1 import Provider, load_config  # noqa: E402
from locate import OffsetIndex, locate  # noqa: E402
from s3 import collect_locates, run_checks  # noqa: E402

DISAMBIG_PROMPT = """下面的文书中，引文「{quote}」出现了 {n} 处，无法唯一定位。
请重新给出该段的【扩写引文】：从该段在正文中实际起始位置（含前面相邻的 8-16 个字）开始，到该段结束，逐字原样。
只输出 JSON：{{"quote": "扩写后的逐字引文"}}。正文：

{text}"""


class Disambiguator:
    def __init__(self, provider: Provider, run_dir: Path, enabled: bool = True):
        self.provider = provider
        self.enabled = enabled
        self.path = run_dir / "receipts.jsonl"
        self._lock = threading.Lock()
        self.t0 = time.monotonic()

    def receipt(self, **kw):
        kw["ts"] = datetime.now().isoformat(timespec="seconds")
        kw["elapsed_s"] = round(time.monotonic() - self.t0, 1)
        with self._lock:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def resolve(self, rec: dict, typ: str, quote: str, occurrences: int):
        """扩写引文消歧：返回 (new_locate, resolved: bool)。"""
        if not self.enabled:
            return None, False
        try:
            content, meta = self.provider.chat(
                "只输出一个 JSON 对象。",
                DISAMBIG_PROMPT.format(quote=quote[:80], n=occurrences, text=rec["cleaned_text"]))
            self.receipt(event="disambiguate", provider=self.provider.name, id=rec["id"],
                         seg=typ, status="ok", **meta)
            out = json.loads(content)
            new_quote = (out.get("quote") or "").strip()
            if not new_quote:
                return None, False
            idx = OffsetIndex(rec["_edits"])
            loc = locate(rec["cleaned_text"], new_quote, idx)
            return loc, loc.status in ("exact_unique", "ws_unique")
        except Exception as e:
            self.receipt(event="disambiguate", provider=self.provider.name, id=rec["id"],
                         seg=typ, status="fail", error=str(e)[:200])
            return None, False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True)
    ap.add_argument("--run", required=True, help="s1_runs/<run_id> 目录")
    ap.add_argument("--provider", default="deepseek", choices=["deepseek", "bailian"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-disambiguate", action="store_true")
    a = ap.parse_args()

    providers, _cfg, _ = load_config()
    records = {r["id"]: r for r in (json.loads(l) for l in open(a.batch, encoding="utf-8"))}
    outputs = [json.loads(l) for l in open(Path(a.run) / "outputs.jsonl", encoding="utf-8")]
    outputs = [o for o in outputs if o.get("ok")]
    s3_dir = Path(a.run) / "s3"
    s3_dir.mkdir(exist_ok=True)
    amb = Disambiguator(providers[a.provider], s3_dir, enabled=not a.no_disambiguate)

    # edits 预载（一次读入；日志在 unified_raw 批次目录）
    edits_path = Path(a.batch).parent / "edits.rle.jsonl"
    edits = {}
    for l in open(edits_path, encoding="utf-8"):
        e = json.loads(l)
        edits[e["id"]] = e

    def _quote_of(output: dict, typ: str) -> str:
        for s in (output.get("segments") or []):
            if s.get("type") == typ:
                return s.get("quote") or ""
        dates = output.get("dates") or {}
        for k in ("behavior", "decision"):
            if typ == k:
                return (dates.get(k) or {}).get("quote") or ""
        return ""

    def evaluate(o: dict) -> dict:
        rec = dict(records[o["id"]])
        cleaned = rec["cleaned_text"]
        index = OffsetIndex(edits[o["id"]])
        locates = collect_locates(o["output"], cleaned, index)
        disambiguated: dict[str, bool] = {}
        # 多处命中消歧（design §8 ①：要求模型给前后文，仍歧义才入队）
        for key, loc in list(locates.items()):
            if loc.status in ("exact_multi", "ws_multi"):
                typ = key.split(":", 1)[1]
                new_loc, ok = amb.resolve({**rec, "_edits": edits[o["id"]]}, typ,
                                          (o["output"].get("segments") or [{}]) and _quote_of(o["output"], typ),
                                          loc.occurrences)
                if ok and new_loc is not None:
                    locates[key] = new_loc
                    disambiguated[typ] = True
        ctx = {"record": rec, "output": o["output"], "locates": locates,
               "disambiguated": disambiguated, "index": index}
        findings = run_checks(ctx)
        status = "error" if any(f.severity == "error" for f in findings) else \
                 ("warn" if findings else "pass")
        return {"id": o["id"], "status": status, "form": rec["form"],
                "findings": [f.as_dict() for f in findings],
                "locates": {k: v.status for k, v in locates.items()}}

    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(evaluate, o) for o in outputs]
        for i, fut in enumerate(as_completed(futs), 1):
            results.append(fut.result())
            if i % 20 == 0 or i == len(futs):
                print(f"  进度 {i}/{len(futs)}")

    amb.receipt(event="s3_end")
    with open(s3_dir / "findings.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_check: Counter = Counter()
    status_c: Counter = Counter()
    form_err: Counter = Counter()
    for r in results:
        status_c[r["status"]] += 1
        if r["status"] == "error":
            form_err[r["form"]] += 1
        for fd in r["findings"]:
            by_check[(fd["check"], fd["severity"])] += 1
    summary = {
        "run": a.run, "n": len(results),
        "status": dict(status_c),
        "by_check": {f"{c}|{s}": n for (c, s), n in by_check.most_common()},
        "errors_by_form": dict(form_err),
        "disambiguation_enabled": not a.no_disambiguate,
    }
    (s3_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
