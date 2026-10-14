import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  ArrowLeft,
  Braces,
  Brain,
  Check,
  Globe,
  Library,
  Loader2,
  Merge,
  MessageSquare,
  Play,
  Save,
  Split,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { getWorkflow, listDatasets, listModels, updateWorkflow } from '@/api'
import { USE_MOCK } from '@/api/client'
import { streamWorkflowRun } from '@/api/sse'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageLoading } from '@/components/common/misc'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { runWorkflowSimulation, type RunLogEntry } from '@/mocks/workflow-run'
import { cn, uid } from '@/lib/utils'
import type { Dataset, ModelInfo, WorkflowEdge, WorkflowNode } from '@/types/api'

type NodeType = 'start' | 'llm' | 'retrieval' | 'branch' | 'http' | 'template' | 'aggregate' | 'reply'

const NODE_META: Record<
  NodeType,
  { label: string; icon: typeof Brain; ring: string }
> = {
  start: { label: '开始', icon: Play, ring: 'border-emerald-400/60 bg-emerald-400/5' },
  llm: { label: 'LLM 推理', icon: Brain, ring: 'border-primary/50 bg-primary/5' },
  retrieval: { label: '知识检索', icon: Library, ring: 'border-sky-400/50 bg-sky-400/5' },
  branch: { label: '条件分支', icon: Split, ring: 'border-amber-400/50 bg-amber-400/5' },
  http: { label: 'HTTP 请求', icon: Globe, ring: 'border-violet-400/50 bg-violet-400/5' },
  template: { label: '模板转换', icon: Braces, ring: 'border-teal-400/50 bg-teal-400/5' },
  aggregate: { label: '变量聚合', icon: Merge, ring: 'border-orange-400/50 bg-orange-400/5' },
  reply: { label: '直接回复', icon: MessageSquare, ring: 'border-rose-400/50 bg-rose-400/5' },
}

/* ---------- 自定义节点 ---------- */

function summarize(data: { nodeType: NodeType; config: Record<string, unknown> }): string {
  const c = data.config
  switch (data.nodeType) {
    case 'start':
      return `${Array.isArray(c.vars) ? c.vars.length : 0} 个输入变量`
    case 'llm':
      return `${(c.model as string) ?? '未选择模型'} · T=${c.temperature ?? 0.7}`
    case 'retrieval':
      return `${(c.dataset_name as string) ?? '选择知识库'} · top_k ${c.top_k ?? 5}`
    case 'branch':
      return (c.condition as string) || '未设置条件'
    case 'http':
      return `${(c.method as string) ?? 'GET'} ${(c.url as string) || '未设置 URL'}`
    case 'template':
      return (c.template as string)?.slice(0, 24) || '未设置模板'
    case 'aggregate':
      return '聚合上游变量'
    case 'reply':
      return '输出最终结果'
  }
}

function WorkflowNodeView({ data, selected }: NodeProps) {
  const d = data as { nodeType: NodeType; name: string; config: Record<string, unknown> }
  const meta = NODE_META[d.nodeType]
  const Icon = meta.icon
  return (
    <div
      className={cn(
        'w-52 rounded-xl border-2 bg-card px-3 py-2.5 shadow-md transition-all',
        meta.ring,
        selected && 'ring-2 ring-primary/60',
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-2" />
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-primary" />
        <span className="truncate text-xs font-semibold">{d.name}</span>
      </div>
      <p className="mt-1 truncate text-[10px] text-muted-foreground">{summarize(d)}</p>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-2" />
    </div>
  )
}

const nodeTypes = { workflow: WorkflowNodeView }

/* ---------- 节点配置面板 ---------- */

function ConfigPanel({
  node,
  models,
  datasets,
  onChange,
  onDelete,
}: {
  node: Node
  models?: ModelInfo[]
  datasets?: Dataset[]
  onChange: (config: Record<string, unknown>) => void
  onDelete: () => void
}) {
  const d = node.data as { nodeType: NodeType; name: string; config: Record<string, unknown> }
  const c = d.config
  const meta = NODE_META[d.nodeType]
  const set = (patch: Record<string, unknown>) => onChange({ ...c, ...patch })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <meta.icon className="h-4 w-4 text-primary" />
          {meta.label}节点
        </span>
        {d.nodeType !== 'start' && (
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        )}
      </div>

      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium">节点名称</label>
          <NameInput node={node} />
        </div>

        {d.nodeType === 'start' && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium">输入变量</label>
            {(Array.isArray(c.vars) ? (c.vars as { name: string; label: string }[]) : []).map(
              (v, i, arr) => (
                <div key={i} className="flex gap-1.5">
                  <Input
                    value={v.name}
                    placeholder="变量名"
                    className="h-8 bg-background text-xs"
                    onChange={(e) => {
                      const vars = [...arr]
                      vars[i] = { ...v, name: e.target.value }
                      set({ vars })
                    }}
                  />
                  <Input
                    value={v.label}
                    placeholder="显示名"
                    className="h-8 bg-background text-xs"
                    onChange={(e) => {
                      const vars = [...arr]
                      vars[i] = { ...v, label: e.target.value }
                      set({ vars })
                    }}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => set({ vars: arr.filter((_, j) => j !== i) })}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ),
            )}
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => set({ vars: [...((c.vars as []) ?? []), { name: '', label: '' }] })}
            >
              添加变量
            </Button>
          </div>
        )}

        {d.nodeType === 'llm' && (
          <>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">模型</label>
              <Select value={(c.model as string) ?? ''} onValueChange={(v) => set({ model: v })}>
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="选择模型" />
                </SelectTrigger>
                <SelectContent>
                  {models?.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">提示词（支持 {'{{变量}}'} 引用）</label>
              <Textarea
                value={(c.prompt as string) ?? ''}
                onChange={(e) => set({ prompt: e.target.value })}
                className="min-h-[100px] bg-background font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">温度</label>
              <Input
                type="number"
                step={0.1}
                min={0}
                max={2}
                value={(c.temperature as number) ?? 0.7}
                onChange={(e) => set({ temperature: Number(e.target.value) })}
                className="bg-background"
              />
            </div>
          </>
        )}

        {d.nodeType === 'retrieval' && (
          <>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">知识库</label>
              <Select
                value={(c.dataset as string) ?? ''}
                onValueChange={(v) => {
                  const ds = datasets?.find((x) => x.id === v)
                  set({ dataset: v, dataset_name: ds?.name })
                }}
              >
                <SelectTrigger className="bg-background">
                  <SelectValue placeholder="选择知识库" />
                </SelectTrigger>
                <SelectContent>
                  {datasets?.map((d2) => (
                    <SelectItem key={d2.id} value={d2.id}>
                      {d2.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">Top-K</label>
              <Input
                type="number"
                min={1}
                max={20}
                value={(c.top_k as number) ?? 5}
                onChange={(e) => set({ top_k: Number(e.target.value) })}
                className="bg-background"
              />
            </div>
          </>
        )}

        {d.nodeType === 'branch' && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium">分支条件描述</label>
            <Textarea
              value={(c.condition as string) ?? ''}
              onChange={(e) => set({ condition: e.target.value })}
              placeholder="如：检索结果最高分 ≥ 0.7"
              className="min-h-[64px] bg-background"
            />
          </div>
        )}

        {d.nodeType === 'http' && (
          <>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">方法</label>
              <Select value={(c.method as string) ?? 'GET'} onValueChange={(v) => set({ method: v })}>
                <SelectTrigger className="bg-background">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium">URL</label>
              <Input
                value={(c.url as string) ?? ''}
                onChange={(e) => set({ url: e.target.value })}
                placeholder="https://api.example.com/predict"
                className="bg-background font-mono text-xs"
              />
            </div>
          </>
        )}

        {(d.nodeType === 'template' || d.nodeType === 'reply') && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium">
              {d.nodeType === 'template' ? '模板内容' : '回复模板（支持 {{变量}} 引用）'}
            </label>
            <Textarea
              value={
                (d.nodeType === 'template' ? (c.template as string) : (c.reply_template as string)) ?? ''
              }
              onChange={(e) => set(d.nodeType === 'template' ? { template: e.target.value } : { reply_template: e.target.value })}
              className="min-h-[100px] bg-background font-mono text-xs"
            />
          </div>
        )}

        {d.nodeType === 'aggregate' && (
          <p className="text-xs leading-relaxed text-muted-foreground">
            自动聚合上游多个分支的输出变量，无需额外配置。
          </p>
        )}
      </div>
    </div>
  )
}

/** 名称输入（独立组件避免整面板重挂） */
function NameInput({ node }: { node: Node }) {
  const d = node.data as { name: string }
  const { setNodes } = useReactFlow()
  return (
    <Input
      value={d.name}
      onChange={(e) =>
        setNodes((nds) =>
          nds.map((n) => (n.id === node.id ? { ...n, data: { ...n.data, name: e.target.value } } : n)),
        )
      }
      className="bg-background"
    />
  )
}

/* ---------- 画布编辑器 ---------- */

function Editor({ id }: { id: string }) {
  const { data: workflow, isLoading } = useQuery({ queryKey: ['workflows', id], queryFn: () => getWorkflow(id) })
  const { data: allModels } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const models = allModels?.filter((m) => (m.capabilities ?? ['completion']).includes('completion'))
  const { data: datasets } = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })
  const qc = useQueryClient()
  const reactFlow = useReactFlow()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [logs, setLogs] = useState<RunLogEntry[]>([])
  const [running, setRunning] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [answer, setAnswer] = useState('')
  const [runError, setRunError] = useState('')
  const [inputsOpen, setInputsOpen] = useState(false)
  const [inputValues, setInputValues] = useState<Record<string, string>>({})
  const initialized = useRef(false)
  const cancelRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  // 加载完成后初始化画布（必须在 effect 中，渲染期调用 useNodesState 的 setter 不生效）
  useEffect(() => {
    if (workflow && !initialized.current) {
      initialized.current = true
      setNodes(workflow.dsl.nodes as Node[])
      setEdges(workflow.dsl.edges as Edge[])
      setName(workflow.name)
    }
  }, [workflow, setNodes, setEdges])

  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((eds) => addEdge({ ...connection, id: uid('e') }, eds)),
    [setEdges],
  )

  const addNode = useCallback(
    (nodeType: NodeType, screenPos?: { x: number; y: number }) => {
      const position = screenPos
        ? reactFlow.screenToFlowPosition(screenPos)
        : { x: 120 + Math.random() * 200, y: 120 + Math.random() * 160 }
      const newNode: Node = {
        id: uid('nd'),
        type: 'workflow',
        position,
        data: { nodeType, name: NODE_META[nodeType].label, config: {} },
      }
      setNodes((nds) => [...nds, newNode])
      setSelectedId(newNode.id)
    },
    [reactFlow, setNodes],
  )

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null

  const updateSelectedConfig = (config: Record<string, unknown>) => {
    if (!selectedNode) return
    setNodes((nds) =>
      nds.map((n) => (n.id === selectedNode.id ? { ...n, data: { ...n.data, config } } : n)),
    )
  }
  const updateSelectedName = (nameStr: string) => {
    if (!selectedNode) return
    setNodes((nds) =>
      nds.map((n) => (n.id === selectedNode.id ? { ...n, data: { ...n.data, name: nameStr } } : n)),
    )
  }
  const deleteSelected = () => {
    if (!selectedNode) return
    setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id))
    setEdges((eds) => eds.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id))
    setSelectedId(null)
  }

  const saveMut = useMutation({
    mutationFn: () =>
      updateWorkflow(id, {
        name: name.trim(),
        dsl: { nodes: nodes as never, edges: edges as never },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      toast.success('工作流已保存')
    },
  })

  const startVars = useMemo(() => {
    const start = nodes.find((n) => (n.data as { nodeType: NodeType }).nodeType === 'start')
    const vars = (start?.data as { config?: { vars?: { name: string; label: string }[] } } | undefined)?.config?.vars
    return (vars ?? []).filter((v) => v.name)
  }, [nodes])

  const patchLog = (entry: Partial<RunLogEntry> & { node_id: string }) =>
    setLogs((prev) => prev.map((l) => (l.node_id === entry.node_id ? { ...l, ...entry } : l)))

  const startRun = () => {
    if (running || nodes.length === 0) return
    // 真实执行需要开始节点的输入变量值；模拟模式不需要
    if (!USE_MOCK && startVars.length) setInputsOpen(true)
    else void executeRun({})
  }

  const executeRun = async (inputs: Record<string, string>) => {
    setInputsOpen(false)
    cancelRef.current = false
    setRunning(true)
    setShowLogs(true)
    setAnswer('')
    setRunError('')
    setLogs(nodes.map((n) => ({ node_id: n.id, name: (n.data as { name: string }).name, status: 'waiting' })))
    try {
      if (USE_MOCK) {
        await runWorkflowSimulation(
          nodes as unknown as WorkflowNode[],
          edges as unknown as WorkflowEdge[],
          patchLog,
          () => cancelRef.current,
        )
        return
      }
      const ctrl = new AbortController()
      abortRef.current = ctrl
      // 试运行当前画布（含未保存的修改）
      await streamWorkflowRun(
        id,
        { inputs, dsl: { nodes, edges } },
        (event, data) => {
          if (event === 'workflow') patchLog(data as unknown as RunLogEntry)
          else if (event === 'message') setAnswer((prev) => prev + String(data.delta ?? ''))
          else if (event === 'error') throw new Error(String(data.message ?? '运行失败'))
        },
        ctrl.signal,
      )
    } catch (e) {
      if (!abortRef.current?.signal.aborted) {
        setRunError((e as Error).message)
        toast.error((e as Error).message)
      }
    } finally {
      abortRef.current = null
      setRunning(false)
    }
  }

  const stopRun = () => {
    cancelRef.current = true
    abortRef.current?.abort()
    setRunning(false)
  }

  const logsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    logsRef.current?.scrollTo({ top: logsRef.current.scrollHeight })
  }, [logs])

  if (isLoading) return <PageLoading />
  if (!workflow) return <div className="p-10 text-center text-sm text-muted-foreground">工作流不存在</div>

  return (
    <div className="flex h-full flex-col">
      {/* 顶栏 */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-4">
        <Link to="/workflows" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 w-56 bg-background text-sm font-medium"
        />
        <Badge variant={workflow.status === 'published' ? 'default' : 'outline'}>
          {workflow.status === 'published' ? '已发布' : '草稿'}
        </Badge>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => void startRun()} disabled={running}>
            {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            试运行
          </Button>
          {running && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={stopRun}
            >
              <Square className="h-3 w-3 fill-current" />
              停止
            </Button>
          )}
          <Button size="sm" className="gap-1.5" onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
            {saveMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            保存
          </Button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1">
        {/* 节点库 */}
        <div className="w-40 shrink-0 space-y-1.5 overflow-y-auto border-r bg-card p-3">
          <div className="px-1 pb-1 text-[11px] font-medium text-muted-foreground">节点库（点击或拖入）</div>
          {(Object.keys(NODE_META) as NodeType[]).map((t) => {
            const meta = NODE_META[t]
            return (
              <div
                key={t}
                draggable
                onDragStart={(e) => e.dataTransfer.setData('application/workflow-node', t)}
                onClick={() => addNode(t)}
                className="flex cursor-grab items-center gap-2 rounded-lg border bg-background px-2.5 py-2 text-xs transition-colors hover:border-primary/40 hover:bg-accent active:cursor-grabbing"
              >
                <meta.icon className="h-3.5 w-3.5 text-primary" />
                {meta.label}
              </div>
            )
          })}
        </div>

        {/* 画布 */}
        <div
          className="min-w-0 flex-1"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            const t = e.dataTransfer.getData('application/workflow-node') as NodeType
            if (t) addNode(t, { x: e.clientX, y: e.clientY })
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId(null)}
            nodeTypes={nodeTypes}
            fitView
            minZoom={0.4}
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls />
            <MiniMap pannable zoomable className="!hidden md:!block" />
          </ReactFlow>
        </div>

        {/* 配置面板 */}
        <div className="w-72 shrink-0 border-l bg-card">
          {selectedNode ? (
            <ConfigPanel
              key={selectedNode.id}
              node={selectedNode}
              models={models}
              datasets={datasets}
              onChange={(config) => {
                if (config) updateSelectedConfig(config)
              }}
              onDelete={deleteSelected}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center px-6 text-center">
              <Split className="h-6 w-6 text-muted-foreground/40" />
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                选中节点后在此配置参数
                <br />
                拖拽节点边缘连线；Delete 删除选中项
              </p>
            </div>
          )}
        </div>

        {/* 运行日志抽屉 */}
        {showLogs && (
          <div className="absolute inset-x-6 bottom-4 z-10 max-h-80 overflow-hidden rounded-xl border bg-card shadow-xl">
            <div className="flex items-center justify-between border-b px-4 py-2">
              <span className="text-xs font-semibold">试运行日志</span>
              <button className="text-muted-foreground hover:text-foreground" onClick={() => setShowLogs(false)}>
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <div ref={logsRef} className="scrollbar-thin max-h-64 space-y-1 overflow-y-auto p-3">
              {logs.map((l) => (
                <div key={l.node_id} className="flex items-center gap-2 rounded-lg bg-muted/40 px-3 py-1.5 text-xs">
                  {l.status === 'running' && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                  {l.status === 'succeeded' && <Check className="h-3 w-3 text-emerald-500" />}
                  {l.status === 'failed' && <X className="h-3 w-3 text-destructive" />}
                  {l.status === 'skipped' && <span className="h-3 w-3 rounded-full bg-muted-foreground/30" />}
                  {l.status === 'waiting' && <span className="h-3 w-3 rounded-full border border-muted-foreground/40" />}
                  <span className="font-medium">{l.name}</span>
                  {l.elapsed !== undefined && <span className="text-muted-foreground">{l.elapsed}ms</span>}
                  {l.output && <span className="truncate text-muted-foreground">{l.output}</span>}
                </div>
              ))}
              {!running &&
                !runError &&
                logs.length > 0 &&
                logs.every((l) => l.status === 'succeeded' || l.status === 'skipped') && (
                  <p className="px-3 pt-1 text-xs text-emerald-600">
                    ✓ 全部节点执行完成{USE_MOCK ? '（模拟）' : ''}
                  </p>
                )}
              {runError && <p className="px-3 pt-1 text-xs text-destructive">{runError}</p>}
              {answer && (
                <div className="mt-2 whitespace-pre-wrap rounded-lg border bg-background px-3 py-2 text-xs leading-relaxed">
                  {answer}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 试运行输入 */}
      <Dialog open={inputsOpen} onOpenChange={setInputsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>试运行输入</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {startVars.map((v) => (
              <div key={v.name} className="space-y-1.5">
                <label className="text-sm font-medium">{v.label || v.name}</label>
                <Textarea
                  value={inputValues[v.name] ?? ''}
                  onChange={(e) => setInputValues((prev) => ({ ...prev, [v.name]: e.target.value }))}
                  className="min-h-[80px]"
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInputsOpen(false)}>
              取消
            </Button>
            <Button
              className="gap-1.5"
              onClick={() =>
                void executeRun(Object.fromEntries(startVars.map((v) => [v.name, inputValues[v.name] ?? ''])))
              }
            >
              <Play className="h-3.5 w-3.5" />
              运行
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default function WorkflowEditorPage() {
  const { id } = useParams()
  if (!id) return null
  return (
    <ReactFlowProvider>
      <Editor key={id} id={id} />
    </ReactFlowProvider>
  )
}
