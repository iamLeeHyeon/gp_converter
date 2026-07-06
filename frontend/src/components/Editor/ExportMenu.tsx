import { useState } from 'react'
import { api } from '../../lib/api'
import ShareModal from './ShareModal'

interface Props {
  fileId: string | null
  gp5Buffer?: ArrayBuffer | null
  onPrint: () => void
}

export default function ExportMenu({ fileId, gp5Buffer = null, onPrint }: Props) {
  const [loading, setLoading] = useState<'gp5' | 'midi' | null>(null)
  const [shareOpen, setShareOpen] = useState(false)

  const handleGP5 = async () => {
    if (fileId) {
      setLoading('gp5')
      try {
        await api.downloadGP5(fileId, 'score.gp5')
      } catch (e) {
        console.error('GP5 다운로드 실패', e)
      } finally {
        setLoading(null)
      }
      return
    }
    // 비로그인(익명) 변환: 서버에 저장된 파일이 없으므로 이미 메모리에 있는
    // 원본 변환 결과 버퍼를 그대로 다운로드한다 (fileId 필요한 최신 편집본과 달리
    // 이 경로는 편집 반영이 안 된 최초 변환 결과다).
    if (gp5Buffer) {
      api.downloadBuffer(gp5Buffer, 'score.gp5')
    }
  }

  const handleMIDI = async () => {
    if (!fileId) return
    setLoading('midi')
    try {
      await api.downloadMIDI(fileId, 'score.mid')
    } catch (e) {
      console.error('MIDI 다운로드 실패', e)
    } finally {
      setLoading(null)
    }
  }

  return (
    <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
      <button onClick={handleGP5} disabled={(!fileId && !gp5Buffer) || loading === 'gp5'}>
        {loading === 'gp5' ? '…' : 'GP5 저장'}
      </button>
      <button onClick={onPrint}>PDF 저장</button>
      <button onClick={handleMIDI} disabled={!fileId || loading === 'midi'}>
        {loading === 'midi' ? '…' : 'MIDI 저장'}
      </button>
      <button onClick={() => setShareOpen(true)} disabled={!fileId}>공유</button>
      {shareOpen && fileId && (
        <ShareModal fileId={fileId} onClose={() => setShareOpen(false)} />
      )}
    </span>
  )
}
