import { create } from 'zustand'
import { api, type FileRecord } from '../lib/api'

interface FileState {
  files: FileRecord[]
  loading: boolean
  load: () => Promise<void>
  remove: (id: string) => Promise<void>
}

export const useFileStore = create<FileState>((set, get) => ({
  files: [],
  loading: false,
  load: async () => {
    set({ loading: true })
    try {
      const files = await api.listFiles()
      set({ files, loading: false })
    } catch {
      set({ loading: false })
    }
  },
  remove: async (id) => {
    await api.deleteFile(id)
    set({ files: get().files.filter((f) => f.id !== id) })
  },
}))
