import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import { connectSSE, ProgressEvent } from '../../lib/sse'
import ProgressBar from '../Editor/ProgressBar'

interface Props {
  onComplete: (jobId: string, gp5Buffer: ArrayBuffer) => void
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
      const { job_id } = await api.upload(file)
      setProgress({ status: 'running', pct: 5, step: 'queued' })
      connectSSE(
        job_id,
        (e) => setProgress(e),
        async () => {
          const buf = await api.getResult(job_id)
          setBusy(false)
          setProgress(null)
          onComplete(job_id, buf)
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
      <label htmlFor="pdf-input">PDF 파일 선택</label>
      <input
        id="pdf-input"
        ref={inputRef}
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        disabled={busy}
      />
      <button onClick={handleUpload} disabled={!file || busy}>
        변환 시작
      </button>
      <ProgressBar
        pct={progress?.pct ?? 0}
        step={progress?.step ?? ''}
        visible={!!progress}
      />
      {error && <p style={{ color: 'red' }}>{error}</p>}
    </div>
  )
}
