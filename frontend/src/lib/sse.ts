export interface ProgressEvent {
  status: 'queued' | 'running' | 'done' | 'failed'
  pct: number
  step: string
}

export function connectSSE(
  jobId: string,
  onProgress: (e: ProgressEvent) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): () => void {
  const es = new EventSource(`/jobs/${jobId}/stream`)

  es.onmessage = (e) => {
    const data: ProgressEvent = JSON.parse(e.data)
    onProgress(data)
    if (data.status === 'done') {
      es.close()
      onDone()
    } else if (data.status === 'failed') {
      es.close()
      onError(data.step || '변환 실패')
    }
  }

  es.onerror = () => {
    es.close()
    onError('SSE 연결 오류')
  }

  return () => es.close()
}
