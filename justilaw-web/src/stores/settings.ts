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
  ragEnabled: boolean
  ragDatasetId?: string
  setModel: (model: string) => void
  setParams: (patch: Partial<Params>) => void
  resetParams: (defaults: Params) => void
  setRag: (enabled: boolean, datasetId?: string) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      model: '',
      params: { temperature: 0.7, top_p: 0.9, max_tokens: 2048 },
      ragEnabled: false,
      ragDatasetId: undefined,
      setModel: (model) => set({ model }),
      setParams: (patch) => set((s) => ({ params: { ...s.params, ...patch } })),
      resetParams: (defaults) => set({ params: defaults }),
      setRag: (ragEnabled, ragDatasetId) => set({ ragEnabled, ragDatasetId }),
    }),
    { name: 'justilaw-settings' },
  ),
)
