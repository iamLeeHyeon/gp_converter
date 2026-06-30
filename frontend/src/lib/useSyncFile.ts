import { useCallback, useEffect, useRef } from 'react'
import { api } from './api'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from './scoreTypes'

export function useSyncFile(
  fileId: string | null,
  snapshot: ScoreSnapshot | null,
): { syncNow: () => void; forceSync: () => Promise<void>; saveStatus: string } {
  const setSaveStatus = useEditorStore((s) => s.setSaveStatus)
  const saveStatus = useEditorStore((s) => s.saveStatus)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined!)

  const syncNow = useCallback(() => {
    clearTimeout(timerRef.current)
    if (!fileId || !snapshot) return
    setSaveStatus('saving')
    api
      .syncFile(fileId, snapshot)
      .then(() => setSaveStatus('saved'))
      .catch(() => setSaveStatus('error'))
  }, [fileId, snapshot, setSaveStatus])

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

  const forceSync = useCallback(async () => {
    if (!fileId || !snapshot) return
    try {
      useEditorStore.getState().setSaveStatus('saving')
      await api.syncFile(fileId, snapshot)
      const buf = await api.getGP5Buffer(fileId)
      useEditorStore.getState().setGp5Buffer(buf)
      useEditorStore.getState().setSaveStatus('saved')
    } catch {
      useEditorStore.getState().setSaveStatus('error')
    }
  }, [fileId, snapshot])

  return { syncNow, forceSync, saveStatus }
}
