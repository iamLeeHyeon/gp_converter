import { useEffect, useRef } from 'react'
import { api } from './api'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from './scoreTypes'

export function useSyncFile(
  fileId: string | null,
  snapshot: ScoreSnapshot | null,
): { saveStatus: string } {
  const setSaveStatus = useEditorStore((s) => s.setSaveStatus)
  const saveStatus = useEditorStore((s) => s.saveStatus)
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

  return { saveStatus }
}

// 구조 편집(마디/트랙 추가삭제 등)은 alphaTab 인플레이스 반영 불가 → 백엔드
// 재동기화 후 리로드. TrackPanel/StructurePanel/ScoreViewer의 undo·redo가
// 공유하는 시퀀스.
export async function syncAndReload(fileId: string, snapshot: ScoreSnapshot): Promise<void> {
  const { setSaveStatus, setGp5Buffer } = useEditorStore.getState()
  setSaveStatus('saving')
  try {
    await api.syncFile(fileId, snapshot)
    const buf = await api.getGP5Buffer(fileId)
    setGp5Buffer(buf)
    setSaveStatus('saved')
  } catch {
    setSaveStatus('error')
  }
}
