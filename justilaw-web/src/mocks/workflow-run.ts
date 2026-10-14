/**
 * 工作流试运行模拟器：按 DSL 节点顺序逐节点回报 running → succeeded，
 * 模拟各节点耗时与输出预览。真实后端交付后由 /workflows/{id}/run (SSE) 替代。
 */
import type { WorkflowEdge, WorkflowNode } from '@/types/api'

export interface RunLogEntry {
  node_id: string
  name: string
  status: 'waiting' | 'running' | 'succeeded' | 'failed' | 'skipped'
  elapsed?: number
  output?: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** 输出预览文案（模拟各节点的产物） */
function mockOutput(node: WorkflowNode): string {
  switch (node.data.nodeType) {
    case 'start':
      return '接收输入变量完成'
    case 'llm':
      return '（模拟输出）已完成推理，生成文本片段 312 tokens…'
    case 'retrieval':
      return '（模拟输出）命中 5 个分段，最高相似度 0.91'
    case 'branch':
      return '（模拟输出）条件判定：走"是"分支'
    case 'http':
      return '（模拟输出）HTTP 200，响应 1.2KB JSON'
    case 'template':
      return '（模拟输出）模板渲染完成，输出 0.8KB'
    case 'aggregate':
      return '（模拟输出）已聚合 2 路变量'
    case 'reply':
      return '（模拟输出）已回复最终内容'
    default:
      return '完成'
  }
}

export async function runWorkflowSimulation(
  nodes: WorkflowNode[],
  _edges: WorkflowEdge[],
  onEvent: (entry: RunLogEntry) => void,
  isCancelled: () => boolean,
): Promise<void> {
  for (const node of nodes) {
    if (isCancelled()) return
    onEvent({ node_id: node.id, name: node.data.name, status: 'running' })
    const elapsed = 300 + Math.floor(Math.random() * 900)
    await sleep(elapsed)
    if (isCancelled()) return
    onEvent({
      node_id: node.id,
      name: node.data.name,
      status: 'succeeded',
      elapsed,
      output: mockOutput(node),
    })
  }
}
