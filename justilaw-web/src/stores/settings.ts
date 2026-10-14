import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface Params {
  temperature: number
  top_p: number
  max_tokens: number
}

interface SettingsState {
  model: string
  params: Params
  thinking: boolean
  ragEnabled: boolean
  ragDatasetId?: string
  setModel: (model: string) => void
  setParams: (patch: Partial<Params>) => void
  resetParams: (defaults: Params) => void
  setThinking: (v: boolean) => void
  setRag: (enabled: boolean, datasetId?: string) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      model: '',
      params: { temperature: 0.7, top_p: 0.9, max_tokens: 2048 },
      thinking: false,
      ragEnabled: false,
      ragDatasetId: undefined,
      setModel: (model) => set({ model }),
      setParams: (patch) => set((s) => ({ params: { ...s.params, ...patch } })),
      resetParams: (defaults) => set({ params: defaults }),
      setThinking: (thinking) => set({ thinking }),
      setRag: (ragEnabled, ragDatasetId) => set({ ragEnabled, ragDatasetId }),
    }),
    { name: 'justilaw-settings' },
  ),
)
