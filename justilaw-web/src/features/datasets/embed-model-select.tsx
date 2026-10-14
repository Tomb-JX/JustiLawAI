import { useQuery } from '@tanstack/react-query'
import { listModels } from '@/api'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** 嵌入模型下拉：只列出具备 embedding 能力的模型 */
export function EmbedModelSelect({ value, onChange }: { value?: string; onChange: (v: string) => void }) {
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const options = models?.filter((m) => m.capabilities?.includes('embedding')) ?? []
  return (
    <Select value={value ?? ''} onValueChange={onChange} disabled={!options.length}>
      <SelectTrigger className="bg-background">
        <SelectValue placeholder={options.length ? '使用默认嵌入模型' : '暂无可用嵌入模型'} />
      </SelectTrigger>
      <SelectContent>
        {options.map((m) => (
          <SelectItem key={m.id} value={m.id}>
            {m.name} · {m.provider_name ?? m.provider}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
