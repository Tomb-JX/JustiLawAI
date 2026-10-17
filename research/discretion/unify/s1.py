"""S1 模型层（parse-format-chain-design v1.2 §7）：远程旗舰调用 + 全程调用日志 + 引文命中率预检。

模型选型（用户 2026-10-17）：deepseek-flash（DeepSeek 官方 API）+ qwen3.8-flash（阿里云百炼
compatible-mode）。密钥存数据目录 config/s1_models.json（不入仓库），日志一律掩码。
调用纪律：temperature=0、JSON 输出、重试=同模型 1 次→换提供商 1 次（design §7.3）；
缓存键 = text_orig_sha256 + clean_version + prompt_version + model（重跑不重复付费）。

产物（$JUSTILAW_DATA_DIR/s1_runs/<run_id>/）：
- manifest.json   运行元数据（配置指纹<掩码>、输入批次+SHA、提示版本、参数、起止）
- receipts.jsonl  每次 HTTP 尝试一行（状态/时延/token/请求与响应摘要 SHA，键掩码）
- outputs.jsonl   每记录一行（原始返回、解析 JSON、校验违规、引文命中预检、重试链）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from cleanse import sentence_table  # noqa: E402  句表（seg-v2 分区坐标基座）
from progress import ProgressTracker, classify_error, load_prices  # noqa: E402  监控基建

PROMPT_VERSION = "seg-v2"
# seg-v1 已冻结归档（试点报告 pilot300：引文命中率 99.92% 但摘引式分段致 coverage 51 件失败）。
# seg-v2 = 句表分区接口（parse-interface-v2-design §2）：输入为编号句表，输出为 run-length
# 分区 + 字段——覆盖/不重叠由"区间铺满句表"的结构校验保证；定性句归置由确定性 snap 执行。
SEG_TYPES = ["facts", "evidence", "reasoning", "decision", "review", "meta"]
OUTCOME_TYPES = ["不予处罚", "不构成违法", "警告", "罚款", "拘留", "拘留并处罚款", "移送刑事"]

_DEFAULT_DATA = Path(r"D:\02_Dev\Data\justilaw-research")


def data_root() -> Path:
    import os
    return Path(os.environ.get("JUSTILAW_DATA_DIR") or _DEFAULT_DATA)


def mask(key: str) -> str:
    if not key or len(key) < 12:
        return "***"
    return key[:5] + "***" + key[-4:]


# ---------- seg-v1 提示 ----------

SYSTEM_PROMPT = """你是行政处罚文书的结构化抽取器。输入是清洗后的文书，以编号句表（[S1]…[SN]）给出。只输出一个 JSON 对象。

【分区 zones】把全部 N 个句子依原顺序切成连续区间，每区间一个类型，必须完整铺满 [S1..SN]：
- facts：违法事实（"经查/查明/现查明"部分）——只写行为事实；
- evidence：证据列举（"以上事实有…证据"）；
- reasoning：认定理由与裁量说明，以及一切定性/结论句（"行为已构成赌博""情节严重""从轻处罚"等）；
- decision：处罚决定及其依据、执行方式（"决定给予…"）；
- review：复议/诉讼机关的审查意见与结论（无则不设）；
- meta：表单元数据（案件名称、文号、日期栏、当事人栏等）。

【硬性结构规则】
1. zones 依序衔接：首区间 from=1；相邻区间前一个 to+1=后一个 from；最后区间 to=N。无缝隙、不重叠、不跳句。
2. 定性/结论句（"已构成""情节严重""决定给予""从轻处罚"等）一律归 reasoning 或 decision，绝不进 facts；facts 的最后一句必须是行为事实陈述。
3. meta 用于表单元数据行（字段表/公示的名称、文号、日期、当事人栏）。

【字段（基于 facts/decision 区间内容）】
- 文书没有的信息给 null 或 []，不得编造；dates 缺失给 null。
- 文书明示数项违法行为或"合并执行"时 multi_violation=true 并给 executed_penalty（合并后总额）；否则 false、executed_penalty 两项填 0。
- articles 每项 {"text": 原文写法, "edition": "2012修正|2025修订|未知"}。
- gambling：本文书是否属赌博案件，verdict 是/否/待定 + 一句 reason。
- confidence：high/low。

【输出 JSON 结构】
{"zones":[{"type":"facts","from":1,"to":10},{"type":"reasoning","from":11,"to":12},{"type":"decision","from":13,"to":14}],
 "subject":{"mention":"本人原写法或null","aliases":[]},
 "outcome":{"type":"不予处罚|不构成违法|警告|罚款|拘留|拘留并处罚款|移送刑事",
   "detention_days":0,"fine":0,"not_executed":"是|否",
   "multi_violation":false,"executed_penalty":{"detention_days":0,"fine":0},
   "confiscation":[],"detention_items":[],
   "articles":[{"text":"…","edition":"2012修正|2025修订|未知"}],
   "stated_circumstances":[]},
 "dates":{"behavior":"YYYY-MM-DD或null","decision":"YYYY-MM-DD或null"},
 "review":{"result":"维持|变更|撤销|确认违法|程序驳回|无","changed_outcome":null},
 "gambling":{"verdict":"是|否|待定","reason":"…"},
 "confidence":"high|low"}"""


def build_user_prompt(form: str, source_type: str, sentences: list[str]) -> str:
    lines = [f"[S{i}] {t}" for i, t in enumerate(sentences, 1)]
    return f"[form] {form} | [source_type] {source_type} | 共 {len(sentences)} 句\n句表：\n" + "\n".join(lines)


# ---------- 提供商客户端 ----------

class Provider:
    def __init__(self, name: str, cfg: dict, params: dict):
        self.name = name
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self._key = cfg["api_key"]
        self.temperature = params.get("temperature", 0)
        self.max_tokens = params.get("max_tokens", 3500)
        self.timeout = params.get("timeout_s", 120)

    def chat(self, system: str, user: str) -> tuple[str, dict]:
        """返回 (content, usage)。非 200 / 超时抛 RuntimeError（由调用方记回执并重试）。"""
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self._key}",
                     "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {e}") from None
        latency = round((time.monotonic() - t0) * 1000)
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content") or ""
        usage = data.get("usage") or {}
        if not content:
            raise RuntimeError(f"空返回（finish={ (data.get('choices') or [{}])[0].get('finish_reason') }）")
        return content, {"latency_ms": latency, "usage": usage}


# ---------- 输出解析与预检 ----------

def extract_json(content: str) -> dict:
    """容错提取 JSON 对象：直接 parse → 剥 ```json 围栏 → 首个 { 到末个 }。"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    i, j = content.find("{"), content.rfind("}")
    if i >= 0 and j > i:
        return json.loads(content[i:j + 1])
    raise ValueError("无法提取 JSON")


def validate(out: dict, n_sentences: int = 0) -> list[str]:
    """结构校验：分区铺满句表（覆盖性/不重叠由结构保证的断言点）+ 字段枚举。"""
    errs = []
    zones = out.get("zones")
    if not isinstance(zones, list) or not zones:
        return ["zones 缺失或为空"]
    prev_to = 0
    for z in zones:
        t, a, b = z.get("type"), z.get("from"), z.get("to")
        if t not in SEG_TYPES:
            errs.append(f"zone.type 非法: {t!r}")
        if not isinstance(a, int) or not isinstance(b, int) or a > b:
            errs.append(f"zone 区间非法: from={a!r} to={b!r}")
            continue
        if a != prev_to + 1:
            errs.append(f"zones 不连续（有缝隙或重叠）: from={a} 应为 {prev_to + 1}")
        prev_to = b
    if n_sentences and prev_to != n_sentences:
        errs.append(f"zones 未铺满句表: to={prev_to} ≠ {n_sentences}")
    oc = out.get("outcome") or {}
    if oc.get("type") not in OUTCOME_TYPES:
        errs.append(f"outcome.type 非法: {oc.get('type')!r}")
    g = (out.get("gambling") or {}).get("verdict")
    if g not in ("是", "否", "待定"):
        errs.append(f"gambling.verdict 非法: {g!r}")
    rv = (out.get("review") or {}).get("result")
    if rv not in ("维持", "变更", "撤销", "确认违法", "程序驳回", "无"):
        errs.append(f"review.result 非法: {rv!r}")
    if out.get("confidence") not in ("high", "low"):
        errs.append(f"confidence 非法: {out.get('confidence')!r}")
    return errs


# ---------- 运行器 ----------

class Runner:
    def __init__(self, providers: dict[str, Provider], run_dir: Path, order: list[str], total: int = 0,
                 tracker_meta: dict | None = None):
        self.providers = providers
        self.order = order
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self._receipt_f = open(run_dir / "receipts.jsonl", "a", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self.t0 = time.monotonic()
        # 监控基建：心跳 + 费用（价格表接线）+ 熔断
        prices = load_prices(data_root() / "config" / "s1_prices.json")
        self.tracker = ProgressTracker(run_dir, total=total, prices=prices,
                                       meta={**(tracker_meta or {}),
                                             "provider_primary": order[0] if order else ""})
        self.cost_meter = self.tracker.cost
        self.dead: set[str] = set()
        self.consec_fail: Counter = Counter()
        self._breaker_lock = threading.Lock()

    def receipt(self, **kw) -> None:
        kw["ts"] = datetime.now().isoformat(timespec="seconds")
        kw["elapsed_s"] = round(time.monotonic() - self.t0, 1)
        with self._lock:
            self._receipt_f.write(json.dumps(kw, ensure_ascii=False) + "\n")
            self._receipt_f.flush()

    def _breaker(self, pname: str, err: str) -> str | None:
        """熔断：balance/auth 一次即判死；其他类连续 3 次判死。返回分类或 None。"""
        cat = classify_error(err)
        with self._breaker_lock:
            if cat in ("balance", "auth"):
                self.dead.add(pname)
                self.receipt(event="circuit_break", provider=pname, cat=cat, status="dead")
                return cat
            self.consec_fail[pname] += 1
            if self.consec_fail[pname] >= 3:
                self.dead.add(pname)
                self.receipt(event="circuit_break", provider=pname, cat=cat, status="dead")
        return cat

    def extract_one(self, rec: dict, primary: str) -> dict:
        """单记录抽取：主提供商 → 失败重试 1 次 → 换备提供商 1 次。熔断跳过判死提供商。全程回执。"""
        cleaned = rec.get("cleaned_text") or ""
        sentences = sentence_table(cleaned)
        texts = [cleaned[a:b] for a, b in sentences]
        user = build_user_prompt(rec["form"], rec["source_type"], texts)
        chain, last_err = [], None
        self.tracker.begin_record()
        # 尝试序列：主×2 → 备×1（判死的提供商跳过）
        seq = [p for p in ([primary, primary] + [q for q in self.order if q != primary][:1])
               if p not in self.dead]
        if not seq:
            self.tracker.finish_record(False, 0, "", error="all_providers_dead", latency_ms=0)
            return {"id": rec["id"], "ok": False, "error": "all_providers_dead（熔断：全部提供商判死）",
                    "chain": []}
        for i, pname in enumerate(seq):
            if pname in self.dead:
                continue   # 熔断跳过（同一记录内判死即止，不再浪费重试）
            prov = self.providers[pname]
            try:
                content, meta = prov.chat(SYSTEM_PROMPT, user)
                self.cost_meter.add(prov.model, meta.get("usage") or {})
                self.receipt(event="call", provider=pname, model=prov.model, id=rec["id"],
                             attempt=i + 1, status="ok", **meta)
                try:
                    out = extract_json(content)
                except Exception as e:
                    self.receipt(event="extract", provider=pname, model=prov.model, id=rec["id"],
                                 attempt=i + 1, status="fail",
                                 error=f"JSON 提取失败: {str(e)[:200]}",
                                 content_sha=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16])
                    raise
                errs = validate(out, n_sentences=len(sentences))
                zc = {"n_zones": len(out.get("zones") or []), "n_sentences": len(sentences)}
                chain.append({"provider": pname, "ok": True})
                self.tracker.finish_record(True, i + 1, pname,
                                           latency_ms=meta.get("latency_ms", 0))
                return {"id": rec["id"], "provider_used": pname, "attempts": i + 1,
                        "ok": True, "validation_errors": errs, "zone_check": zc,
                        "content_sha": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                        "output": out, "raw": content, "chain": chain}
            except Exception as e:
                last_err = str(e)[:300]
                self.receipt(event="call", provider=pname, model=prov.model, id=rec["id"],
                             attempt=i + 1, status="fail", error=last_err)
                chain.append({"provider": pname, "ok": False, "error": last_err})
                self._breaker(pname, last_err)
        self.tracker.finish_record(False, len(seq), seq[-1] if seq else "", error=last_err or "?")
        return {"id": rec["id"], "ok": False, "error": last_err, "chain": chain}

    def close(self) -> None:
        self._receipt_f.close()


def load_config() -> tuple[dict[str, Provider], dict, str]:
    cfg_path = data_root() / "config" / "s1_models.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    params = cfg.get("params") or {}
    providers = {name: Provider(name, pcfg, params)
                 for name, pcfg in cfg.items()
                 if isinstance(pcfg, dict) and pcfg.get("api_key") and pcfg.get("base_url")}
    fp = hashlib.sha256(cfg_path.read_bytes()).hexdigest()[:8]
    masked = {k: {**v, "api_key": mask(v["api_key"])} for k, v in cfg.items()
              if isinstance(v, dict) and "api_key" in v}
    return providers, {"fingerprint": fp, "providers": masked, "params": params}, cfg_path.name


def sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SAMPLE_SEED = 20261017


def pilot_ids(rows: list[dict], n: int, seed: int = SAMPLE_SEED) -> list[dict]:
    """form 分层抽样（少数 form 保底 10 件），固定种子，双模型共用同批。"""
    by_form: dict[str, list[dict]] = {}
    for r in rows:
        by_form.setdefault(r["form"], []).append(r)
    rng = random.Random(seed)
    picked: list[dict] = []
    forms = sorted(by_form)
    for f in forms:
        pool = sorted(by_form[f], key=lambda x: x["id"])
        rng.shuffle(pool)
        take = min(len(pool), max(10, round(n * len(pool) / len(rows))))
        picked.extend(pool[:take])
    if len(picked) > n:
        rng.shuffle(picked)
        picked = picked[:n]
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="unified_raw records.jsonl")
    ap.add_argument("--provider", default="deepseek",
                    help="主提供商（config 键；缺省 deepseek）")
    ap.add_argument("--pilot", type=int, default=0, help="form 分层抽样的记录数（0=全部放行记录）")
    ap.add_argument("--limit", type=int, default=0, help="直接取前 N 条放行记录（调试）")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()

    providers, cfg_meta, _ = load_config()
    rows = [json.loads(l) for l in open(a.batch, encoding="utf-8")]
    rows = [r for r in rows if r["prefilter"]["release"]]
    if a.limit:
        rows = rows[:a.limit]
    elif a.pilot:
        rows = pilot_ids(rows, a.pilot)
    print(f"输入 {a.batch}\n放行记录 {len(rows)} 条；主提供商 {a.provider} "
          f"({providers[a.provider].model})；form 分布 {dict(Counter(r['form'] for r in rows))}")

    run_id = a.run_id or f"s1-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = data_root() / "s1_runs" / run_id
    runner = Runner(providers, run_dir, [a.provider] + [p for p in providers if p != a.provider],
                    total=len(rows),
                    tracker_meta={"run_id": run_id, "prompt_version": PROMPT_VERSION,
                                  "input_batch": a.batch})
    manifest = {
        "run_id": run_id, "prompt_version": PROMPT_VERSION,
        "config": cfg_meta, "input_batch": a.batch,
        "input_sha256": sha256_file(a.batch),
        "provider_primary": a.provider,
        "models": {k: v.model for k, v in providers.items()},
        "n_records": len(rows), "ids": [r["id"] for r in rows],
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    runner.receipt(event="run_start", run_id=run_id, n=len(rows), primary=a.provider)

    # 缓存：同 run 内已成功的 id 跳过（断点续跑）
    done: dict[str, dict] = {}
    out_path = run_dir / "outputs.jsonl"
    if out_path.exists():
        for l in open(out_path, encoding="utf-8"):
            try:
                d = json.loads(l)
                if d.get("ok"):
                    done[d["id"]] = d
            except json.JSONDecodeError:
                pass
    todo = [r for r in rows if r["id"] not in done]
    print(f"缓存命中 {len(done)}，待调用 {len(todo)}")

    results: list[dict] = list(done.values())
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(runner.extract_one, r, a.provider): r for r in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            d = fut.result()
            results.append(d)
            with open(out_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
            if i % 10 == 0 or i == len(todo):
                print(f"  进度 {i}/{len(todo)}")

    runner.receipt(event="run_end", done=len(results))
    runner.tracker.set_phase("done")
    runner.close()
    # 运行索引（监控列表用）
    idx_path = data_root() / "s1_runs" / "index.json"
    idx = {}
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
    idx[run_id] = {"phase": "done", "n": len(results), "ok": len(ok),
                   "cost": runner.tracker.cost.total(), "updated": datetime.now().isoformat(timespec="seconds")}
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    ok = [d for d in results if d.get("ok")]
    zn = sum(d["zone_check"]["n_zones"] for d in ok)
    summary = {
        "run_id": run_id, "n": len(results), "ok": len(ok),
        "json_ok_rate": round(len(ok) / len(results), 4) if results else 0,
        "validation_clean": sum(1 for d in ok if not d["validation_errors"]),
        "zones": {"total": zn, "avg_per_record": round(zn / len(ok), 2) if ok else 0},
        "tiling_violations": sum(1 for d in ok if any("铺满" in e or "连续" in e for e in d["validation_errors"])),
        "attempts_dist": dict(Counter(d.get("attempts") for d in results)),
        "provider_used": dict(Counter(d.get("provider_used") for d in results)),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
