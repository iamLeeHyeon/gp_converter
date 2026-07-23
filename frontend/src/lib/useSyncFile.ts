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
  // 디바운스 타이머가 아직 못 쏜(3초 안 지난) 최신 편집 — 파일 전환/언마운트
  // 시 이게 남아있으면 그 편집이 서버로 전송된 적 없이 사라진다는 뜻이라
  // 즉시 flush해야 한다(clearTimeout만 하면 편집이 조용히 유실됨).
  const pendingRef = useRef<{ fileId: string; snapshot: ScoreSnapshot } | null>(null)

  useEffect(() => {
    if (!fileId || !snapshot) return
    clearTimeout(timerRef.current)
    pendingRef.current = { fileId, snapshot }
    timerRef.current = setTimeout(async () => {
      pendingRef.current = null
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

  // fileId가 바뀌거나(다른 파일 선택) 컴포넌트가 언마운트될 때만 flush한다.
  // snapshot만 바뀌는 매 편집마다는 실행되지 않아야(디바운스 취지 유지) 하므로
  // 의존성 배열을 [fileId]로 좁게 잡는다.
  useEffect(() => {
    return () => {
      const pending = pendingRef.current
      if (!pending) return
      pendingRef.current = null
      api.syncFile(pending.fileId, pending.snapshot).catch(() => {
        setSaveStatus('error')
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId])

  // 탭 닫기/새로고침 시에도 같은 방식으로 flush를 시도한다. fetch의
  // keepalive 옵션은 페이지가 언로드돼도 요청이 살아남게 해준다(sendBeacon과
  // 달리 Authorization 헤더를 그대로 쓸 수 있어서 이 방식을 택함).
  useEffect(() => {
    const handler = () => {
      const pending = pendingRef.current
      if (!pending) return
      pendingRef.current = null
      api.syncFile(pending.fileId, pending.snapshot, { keepalive: true }).catch(() => {})
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

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
