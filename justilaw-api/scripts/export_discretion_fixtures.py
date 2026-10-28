"""导出裁量能力层（契约 §3.12）的模拟数据，供前端 Mock 使用。

  python scripts/export_discretion_fixtures.py [--real <DeepSeek 冒烟结果 json>]

- 全部由真实路由生成：分段 / 抽取用测试里的假网关（不发真实请求），规则、实务参照、trace 都是引擎真实输出；
- --real：把一次真实模型（DeepSeek）的 review 结果转成轮询返回的形状一并导出；不给则保留已有文件；
- 输出到 justilaw-web/src/mocks/fixtures/discretion/，index.json 说明每个文件对应的接口与场景。
契约或引擎输出变化后重跑本脚本即可同步。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.model_gateway import gateway  # noqa: E402
from app.store import discretion_runs_db, settings_db  # noqa: E402
from tests.discretion import test_chain_routes as fx  # noqa: E402  复用假网关与样例文书

OUT = API.parent / "justilaw-web/src/mocks/fixtures/discretion"
JIANGSU = {"behavior_date": "2023-07-06", "decision_date": "2023-07-07", "region": "320582",
           "behavior_type": "参与赌博", "method": "麻将", "gambling_form": "其他",
           "personal_stake": {"min": 600, "max": 600}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real")
    args = ap.parse_args()
    discretion_runs_db.data, discretion_runs_db.save = {}, lambda: None
    settings_db.data, settings_db.save = {}, lambda: None
    gateway.provider_store.all_models = lambda capability=None: [{"id": "deepseek/deepseek-flash"}]
    gateway.provider_store.default_model = lambda kind: "deepseek/deepseek-flash"
    fake = fx.FakeGateway()
    gateway.call_json = fake
    app.dependency_overrides[current_user] = lambda: {"id": "u_demo", "role": "user"}
    c = TestClient(app)
    files, index = {}, []

    def put(name, endpoint, scene, body):
        files[name] = body
        index.append({"file": name, "endpoint": endpoint, "scene": scene})

    def submit(path, body):
        r = c.post(path, json=body)
        return r.json(), c.get(r.json()["data"]["poll"]).json()

    put("settings.json", "GET /discretion/settings", "模型槽位与链路版本", c.get("/api/v1/discretion/settings").json())
    put("assess-jiangsu-fine.json", "POST /discretion/assess", "江苏麻将、本人赌资 600 元：唯一档位 → 罚款；含实务参照与逐项贡献",
        c.post("/api/v1/discretion/assess", json=JIANGSU).json())
    put("assess-deviation.json", "POST /discretion/assess", "同上 + 拟处罚拘留 5 日：省级基准档位偏离",
        c.post("/api/v1/discretion/assess", json={**JIANGSU, "proposed": {"type": "拘留", "detention_days": 5}}).json())
    put("assess-candidates.json", "POST /discretion/assess", "河北网络赌博、赌资不明：多档候选 + 补查提示",
        c.post("/api/v1/discretion/assess", json={"behavior_date": "2023-04-26", "decision_date": "2023-05-01",
                                                  "region": "130102", "behavior_type": "参与赌博",
                                                  "method": "网络赌博"}).json())
    put("assess-out-of-scope.json", "POST /discretion/assess", "新法时期：实务参照 out_of_scope（不外推）",
        c.post("/api/v1/discretion/assess", json={**JIANGSU, "behavior_date": "2026-03-01",
                                                  "decision_date": "2026-03-05"}).json())

    sub, run = submit("/api/v1/discretion/parse", {"text": fx.TEXT, "doc_kind": "决定书"})
    put("parse-submit.json", "POST /discretion/parse → 202", "提交后立即返回任务号", sub)
    put("run-running.json", "GET /discretion/runs/{run_id}", "轮询：仍在执行",
        {"code": 0, "message": "ok", "data": {"run_id": sub["data"]["run_id"], "kind": "parse", "status": "running",
                                              "created_at": run["data"]["created_at"], "finished_at": None,
                                              "request_sha256": run["data"]["request_sha256"],
                                              "result": None, "error": None, "partial": None}})
    put("run-parse-succeeded.json", "GET /discretion/runs/{run_id}", "分段完成", run)
    _, run = submit("/api/v1/discretion/extract", {"parse_run_id": sub["data"]["run_id"], "region": "320582"})
    put("run-extract-succeeded.json", "GET /discretion/runs/{run_id}", "抽取完成：要素 + 证据 + assess_input", run)

    bad = fx.element_payload()
    bad["amounts"]["commission"] = {"status": "明确", "value": {"min": 5, "max": 5}, "evidence": [{"sentence_ids": ["S2.1"]}]}
    orig = fx.element_payload
    fx.element_payload = lambda: bad
    _, run = submit("/api/v1/discretion/extract", {"text": fx.TEXT, "region": "320582"})
    fx.element_payload = orig
    put("run-extract-dropped.json", "GET /discretion/runs/{run_id}", "抽取完成但一个字段校验不过：dropped + 待核实", run)

    _, run = submit("/api/v1/discretion/review", {"text": fx.TEXT, "region": "320582"})
    put("run-review-succeeded.json", "GET /discretion/runs/{run_id}", "决定书审查完成：未发现偏离", run)
    _, run = submit("/api/v1/discretion/review", {"elements": JIANGSU, "actual": {"type": "拘留", "detention_days": 5}})
    put("run-review-elements-deviation.json", "GET /discretion/runs/{run_id}", "已确认要素 + 实际处罚：存在偏离", run)
    dates = fx.S1_OUT["dates"]
    fx.S1_OUT["dates"] = {"behavior": None, "decision": None}
    _, run = submit("/api/v1/discretion/review", {"text": fx.TEXT, "region": "320582"})
    fx.S1_OUT["dates"] = dates
    put("run-review-failed-missing-date.json", "GET /discretion/runs/{run_id}", "审查失败：缺行为日期，partial 保留解析与抽取", run)
    fake.script["segment"] = ["error", "error"]
    _, run = submit("/api/v1/discretion/parse", {"text": fx.TEXT})
    put("run-parse-failed-model.json", "GET /discretion/runs/{run_id}", "模型调用全部失败：502 语义，partial 含回执", run)

    real = OUT / "run-review-real-deepseek.json"
    if args.real:
        d = json.loads(Path(args.real).read_text("utf-8"))["response"]["data"]
        put(real.name, "GET /discretion/runs/{run_id}", "真实模型（DeepSeek）审查河北清河决定书 W-000114（已脱敏）",
            {"code": 0, "message": "ok", "data": {"run_id": d["run_id"], "kind": "review", "status": "succeeded",
                                                  "created_at": "2026-10-28T10:30:00+00:00",
                                                  "finished_at": "2026-10-28T10:31:00+00:00", "request_sha256": None,
                                                  "result": d, "error": None, "partial": None}})
    elif real.exists():
        index.append({"file": real.name, "endpoint": "GET /discretion/runs/{run_id}",
                      "scene": "真实模型（DeepSeek）审查河北清河决定书 W-000114（已脱敏）"})

    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (OUT / name).write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (OUT / "index.json").write_text(json.dumps({
        "contract": "docs/02-design/api-contract.md §3.12 v1.0",
        "generator": "justilaw-api/scripts/export_discretion_fixtures.py",
        "note": "parse / extract / review 先返回 202 + run_id，再轮询 runs；模拟时按 *-submit → run-running → run-*-succeeded/failed 的顺序返回",
        "files": index}, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{len(index)} files → {OUT}")


if __name__ == "__main__":
    main()
