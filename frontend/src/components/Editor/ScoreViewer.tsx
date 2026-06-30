import { useEffect, useRef, useState } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'

interface Props {
  gp5Buffer: ArrayBuffer | null
}

export default function ScoreViewer({ gp5Buffer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    const api = initAlphaTab(containerRef.current)
    apiRef.current = api

    api.scoreLoaded.on(() => setLoaded(true))
    api.playerStateChanged.on((e: any) => {
      setPlaying(e.state === 1) // 1 = Playing
    })

    return () => {
      api.destroy()
      apiRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!apiRef.current || !gp5Buffer) return
    setLoaded(false)
    apiRef.current.load(gp5Buffer)
  }, [gp5Buffer])

  if (!gp5Buffer) {
    return (
      <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>
        악보를 불러오세요 — PDF를 업로드하거나 파일 목록에서 선택하세요
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <button
          onClick={() => apiRef.current?.playPause()}
          disabled={!loaded}
        >
          {playing ? '일시정지' : '재생'}
        </button>
      </div>
      <div ref={containerRef} style={{ width: '100%' }} />
    </div>
  )
}
