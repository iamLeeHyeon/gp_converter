import { useState } from 'react'
import { api } from '../../lib/api'
import ShareModal from './ShareModal'

interface Props {
  fileId: string | null
  onPrint: () => void
}

export default function ExportMenu({ fileId, onPrint }: Props) {
  const [loading, setLoading] = useState<'gp5' | 'midi' | null>(null)
  const [shareOpen, setShareOpen] = useState(false)

  const handleGP5 = async () => {
    if (!fileId) return
    setLoading('gp5')
    try {
      await api.downloadGP5(fileId, 'score.gp5')
    } catch (e) {
      console.error('GP5 다운로드 실패', e)
    } finally {
      setLoading(null)
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
      <button onClick={handleGP5} disabled={!fileId || loading === 'gp5'}>
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
