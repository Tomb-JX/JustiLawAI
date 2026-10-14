import { Workflow } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

export default function WorkflowsPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
        <Workflow className="h-8 w-8 text-primary" />
      </div>
      <h1 className="mt-4 text-xl font-bold">工作流编排</h1>
      <p className="mt-2 max-w-md text-center text-sm leading-relaxed text-muted-foreground">
        可视化工作流画布（节点编排 / 知识检索 / 条件分支 / HTTP 调用 / 试运行日志）计划于
        里程碑 M5 交付，将预置「案情分析」「合同风险扫描」「判决预测」三套法律模板。
      </p>
      <Badge variant="outline" className="mt-4">
        M5 · 第 9-10 周
      </Badge>
    </div>
  )
}
