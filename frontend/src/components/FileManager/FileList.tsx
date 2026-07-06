import { useEffect } from 'react'
import { useFileStore } from '../../store/fileStore'
import { api } from '../../lib/api'

interface Props {
  onSelect: (gp5Buffer: ArrayBuffer, fileId: string) => void
}

export default function FileList({ onSelect }: Props) {
  const { files, loading, load, remove } = useFileStore()

  useEffect(() => { load() }, [load])

  if (loading) return <p>불러오는 중...</p>
  if (files.length === 0) return <p>저장된 파일이 없습니다</p>

  return (
    <ul style={{ listStyle: 'none', padding: 0 }}>
      {files.map((f) => (
        <li key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
          <button
            onClick={async () => {
              const buf = await api.getGP5Buffer(f.id)
              onSelect(buf, f.id)
            }}
            style={{ flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
          >
            {f.name}
          </button>
          <small style={{ color: '#999' }}>{f.created_at.slice(0, 10)}</small>
          <button
            onClick={() => remove(f.id)}
            style={{ color: 'red', background: 'none', border: 'none', cursor: 'pointer' }}
            aria-label={`${f.name} 삭제`}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}
