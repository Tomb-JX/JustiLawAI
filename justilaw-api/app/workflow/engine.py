"""工作流执行器：按 DSL（React Flow 的 nodes/edges）拓扑顺序执行节点，逐节点回报进度。

变量引用：模板中的 {{name}} 依次匹配：开始节点输入变量 → 节点 ID → 节点名称 → 节点类型
（如 {{aggregate}}），取对应节点的输出文本。未配置提示词/模板时，节点默认使用上游输出。

节点语义：
- start      输出所有输入变量的拼接文本
- llm        渲染 prompt 后调用模型（未选模型用默认对话模型）
- retrieval  以上游输出为查询检索知识库，输出命中片段
- branch     条件为真则继续下游，为假则跳过只能经由本节点到达的下游节点；
             支持 `A 包含 B`、`A == B`、`A >= 0.7` 等简单比较，其余写法按"非空即真"
- http       GET/POST 外部接口（POST 发送 {"input": 上游输出, "vars": 输入变量}）
- template   渲染模板
- aggregate  拼接所有上游输出
- reply      渲染回复模板（为空则用上游输出）作为最终结果
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from .. import config
from ..model_gateway.gateway import complete, provider_store
from ..rag.retrieval import retrieve, to_context

VAR_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
COMPARE_RE = re.compile(r"^(.*?)\s*(==|!=|>=|<=|>|<|包含|不包含|contains)\s*(.*)$", re.S)
OUTPUT_PREVIEW = 300


class WorkflowError(ValueError):
    pass


@dataclass
class NodeEvent:
    node_id: str
    name: str
    status: str                 # running | succeeded | failed | skipped
    elapsed: int | None = None
    output: str | None = None


@dataclass
class RunState:
    inputs: dict
    nodes: dict[str, dict]
    outputs: dict[str, str] = field(default_factory=dict)

    def lookup(self, key: str) -> str | None:
        if key in self.inputs:
            return str(self.inputs[key])
        key_base = key.removesuffix(".output")
        if key_base in self.outputs:
            return self.outputs[key_base]
        for nid, n in self.nodes.items():
            d = n.get("data", {})
            if nid in self.outputs and key_base in (d.get("name"), d.get("nodeType")):
                return self.outputs[nid]
        return None

    def render(self, template: str) -> str:
        return VAR_RE.sub(lambda m: self.lookup(m.group(1)) or "", template or "")


def _topo_order(nodes: dict[str, dict], edges: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    indeg = {nid: 0 for nid in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes:
            parents[t].append(s)
            children[s].append(t)
            indeg[t] += 1
    queue = deque(sorted((nid for nid, d in indeg.items() if d == 0),
                         key=lambda nid: nodes[nid].get("position", {}).get("x", 0)))
    order = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for c in children[nid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                queue.append(c)
    if len(order) != len(nodes):
        raise WorkflowError("工作流存在环路，无法执行")
    return order, parents


def _eval_condition(expr: str) -> bool:
    expr = expr.strip()
    m = COMPARE_RE.match(expr)
    if not m:
        return bool(expr) and expr.lower() not in ("false", "0", "否", "no")
    left, op, right = (s.strip().strip("'\"") for s in m.groups())
    if op in ("包含", "contains"):
        return right in left
    if op == "不包含":
        return right not in left
    try:
        a, b = float(left), float(right)
    except ValueError:
        a, b = left, right
    return {"==": a == b, "!=": a != b, ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]


async def _run_node(node: dict, upstream: str, state: RunState) -> tuple[str, bool]:
    """返回 (输出文本, 是否继续下游)。"""
    d = node.get("data", {})
    ntype, cfg = d.get("nodeType"), d.get("config") or {}

    if ntype == "start":
        return "\n".join(f"{k}: {v}" for k, v in state.inputs.items()), True

    if ntype == "llm":
        model = cfg.get("model") or provider_store.default_model("chat")
        if not model:
            raise WorkflowError("没有可用的对话模型")
        if not provider_store.resolve(model):
            raise WorkflowError(f"模型不可用：{model}")
        prompt = state.render(cfg.get("prompt") or "")
        if upstream and not VAR_RE.search(cfg.get("prompt") or ""):
            # 提示词没有引用任何变量时自动附上上游输出，避免模型拿不到输入
            prompt = f"{prompt}\n\n【输入】\n{upstream}" if prompt else upstream
        text, _ = await complete(model, [{"role": "user", "content": prompt}],
                                 {"temperature": cfg.get("temperature", 0.7), "max_tokens": cfg.get("max_tokens", 2048)})
        return text, True

    if ntype == "retrieval":
        if not cfg.get("dataset"):
            raise WorkflowError("未选择知识库")
        query = state.render(cfg["query"]) if cfg.get("query") else upstream
        hits = await retrieve([cfg["dataset"]], query, int(cfg.get("top_k") or 5))
        return (to_context(hits) if hits else "（未检索到相关内容）"), True

    if ntype == "branch":
        cond = state.render(cfg.get("condition") or "")
        ok_ = _eval_condition(cond)
        return f"条件「{cond or '（空）'}」→ {'是' if ok_ else '否'}", ok_

    if ntype == "http":
        url = state.render(cfg.get("url") or "").strip()
        if urlparse(url).scheme not in ("http", "https"):
            raise WorkflowError("HTTP 节点需要 http(s) 地址")
        method = (cfg.get("method") or "GET").upper()
        async with httpx.AsyncClient(timeout=config.HTTP_NODE_TIMEOUT_S) as client:
            if method == "POST":
                r = await client.post(url, json={"input": upstream, "vars": state.inputs})
            else:
                r = await client.get(url)
        if r.status_code >= 400:
            raise WorkflowError(f"HTTP {r.status_code}：{r.text[:200]}")
        try:
            return json.dumps(r.json(), ensure_ascii=False, indent=1), True
        except ValueError:
            return r.text, True

    if ntype == "template":
        return state.render(cfg.get("template") or "") or upstream, True

    if ntype == "aggregate":
        return upstream, True

    if ntype == "reply":
        return (state.render(cfg["reply_template"]) if cfg.get("reply_template") else upstream), True

    raise WorkflowError(f"未知节点类型：{ntype}")


async def run_workflow(dsl: dict, inputs: dict) -> AsyncIterator[NodeEvent | dict]:
    """逐节点 yield NodeEvent，最后 yield {"outputs": {...}, "answer": str}。"""
    nodes = {n["id"]: n for n in dsl.get("nodes") or []}
    if not nodes:
        raise WorkflowError("工作流没有节点")
    order, parents = _topo_order(nodes, dsl.get("edges") or [])
    state = RunState(inputs=inputs or {}, nodes=nodes)
    blocked: set[str] = set()
    answer = ""

    for nid in order:
        node = nodes[nid]
        name = node.get("data", {}).get("name") or nid
        ps = parents[nid]
        # 所有上游都被跳过（或都被分支挡住）则本节点跳过
        if ps and all(p in blocked for p in ps):
            blocked.add(nid)
            yield NodeEvent(nid, name, "skipped", output="上游分支条件不满足，已跳过")
            continue
        upstream = "\n\n".join(state.outputs[p] for p in ps if p in state.outputs and p not in blocked)
        yield NodeEvent(nid, name, "running")
        t0 = time.time()
        try:
            out, cont = await _run_node(node, upstream, state)
        except Exception as e:
            yield NodeEvent(nid, name, "failed", int((time.time() - t0) * 1000), str(e)[:300])
            raise WorkflowError(f"节点「{name}」执行失败：{e}") from e
        state.outputs[nid] = out
        if not cont:
            blocked.add(nid)
        if node.get("data", {}).get("nodeType") == "reply":
            answer = out
        yield NodeEvent(nid, name, "succeeded", int((time.time() - t0) * 1000), out[:OUTPUT_PREVIEW])

    if not answer and order:  # 没有回复节点时以最后一个执行节点的输出为结果
        answer = next((state.outputs[n] for n in reversed(order) if n in state.outputs), "")
    yield {"outputs": state.outputs, "answer": answer}
