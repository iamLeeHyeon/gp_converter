import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { initAlphaTab } from '../../lib/alphatab'
import { api } from '../../lib/api'
import type * as alphaTab from '@coderline/alphatab'

export default function SharedScoreViewer() {
  const { token } = useParams<{ token: string }>()
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current || !token) return
    const atApi = initAlphaTab(containerRef.current)
    apiRef.current = atApi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    atApi.playerStateChanged.on((e: any) => setPlaying(e.state === 1))

    api.fetchSharedGP5(token)
      .then(buf => atApi.load(buf))
      .catch(() => setError('링크가 만료되었거나 존재하지 않습니다'))

    return () => { atApi.destroy(); apiRef.current = null }
  }, [token])

  if (error) {
    return <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>{error}</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div style={{ padding: 8 }}>
        <button onClick={() => apiRef.current?.playPause()}>
          {playing ? '일시정지' : '재생'}
        </button>
      </div>
      <div ref={containerRef} style={{ flex: 1, overflow: 'auto' }} />
    </div>
  )
}
