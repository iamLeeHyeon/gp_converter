import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import { connectSSE, type ProgressEvent } from '../../lib/sse'
import ProgressBar from '../Editor/ProgressBar'

interface Props {
  onComplete: (jobId: string, gp5Buffer: ArrayBuffer, fileId?: string | null) => void
}

export default function UploadButton({ onComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleUpload = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const { job_id, file_id } = await api.upload(file)
      setProgress({ status: 'running', pct: 5, step: 'queued' })
      connectSSE(
        job_id,
        (e) => setProgress(e),
        async () => {
          const buf = await api.getResult(job_id)
          setBusy(false)
          setProgress(null)
          onComplete(job_id, buf, file_id)
        },
        (msg) => {
          setError(msg)
          setBusy(false)
          setProgress(null)
        },
      )
    } catch (e: any) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div>
      <label htmlFor="pdf-input" style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'rgba(255,255,255,0.9)' }}>
        PDF 파일 선택
      </label>
      <input
        id="pdf-input"
        ref={inputRef}
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        disabled={busy}
        style={{
          display: 'block',
          width: '100%',
          fontSize: 12,
          color: '#ffffff',
          marginBottom: 12,
        }}
      />
      <button
        onClick={handleUpload}
        disabled={!file || busy}
        style={{
          width: '100%',
          background: !file || busy ? 'rgba(255,255,255,0.3)' : '#ffffff',
          color: !file || busy ? 'rgba(255,255,255,0.7)' : '#4a9df0',
          border: 'none',
          borderRadius: 8,
          padding: '10px 16px',
          fontSize: 14,
          fontWeight: 700,
          cursor: !file || busy ? 'not-allowed' : 'pointer',
        }}
      >
        변환 시작
      </button>
      <ProgressBar
        pct={progress?.pct ?? 0}
        step={progress?.step ?? ''}
        visible={!!progress}
      />
      {error && <p style={{ color: '#ffe5e5', fontSize: 13 }}>{error}</p>}
    </div>
  )
}
