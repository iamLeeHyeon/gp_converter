import { useEffect, useRef } from 'react'
import { api } from './api'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from './scoreTypes'

export function useSyncFile(fileId: string | null, snapshot: ScoreSnapshot | null): void {
  const setSaveStatus = useEditorStore((s) => s.setSaveStatus)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined!)

  useEffect(() => {
    if (!fileId || !snapshot) return
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setSaveStatus('saving')
      try {
        await api.syncFile(fileId, snapshot)
        setSaveStatus('saved')
      } catch {
        setSaveStatus('error')
      }
    }, 3000)

    return () => clearTimeout(timerRef.current)
  }, [fileId, snapshot, setSaveStatus])
}
