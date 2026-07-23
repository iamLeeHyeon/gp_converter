import { useEffect, useState } from 'react'
import { useFileStore } from '../../store/fileStore'
import { api } from '../../lib/api'

interface Props {
  onSelect: (gp5Buffer: ArrayBuffer, fileId: string) => void
}

export default function FileList({ onSelect }: Props) {
  const { files, loading, load, remove } = useFileStore()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { load() }, [load])

  if (loading) return <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.85)' }}>불러오는 중...</p>
  if (files.length === 0) return <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.85)' }}>저장된 파일이 없습니다</p>

  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {error && <li style={{ color: '#ff8080', fontSize: 13, padding: '4px 0' }}>{error}</li>}
      {files.map((f) => (
        <li key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.15)' }}>
          <button
            onClick={async () => {
              setError(null)
              try {
                const buf = await api.getGP5Buffer(f.id)
                onSelect(buf, f.id)
              } catch {
                setError(`"${f.name}" 파일을 여는 데 실패했습니다`)
              }
            }}
            style={{ flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, color: '#ffffff' }}
          >
            {f.name}
          </button>
          <small style={{ color: 'rgba(255,255,255,0.6)' }}>{f.created_at.slice(0, 10)}</small>
          <button
            onClick={() => remove(f.id)}
            style={{ color: 'rgba(255,255,255,0.7)', background: 'none', border: 'none', cursor: 'pointer' }}
            aria-label={`${f.name} 삭제`}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}
