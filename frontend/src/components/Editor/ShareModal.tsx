import { useEffect, useRef, useState } from 'react'
import { api, type ShareInfo } from '../../lib/api'

interface Props {
  fileId: string
  onClose: () => void
}

export default function ShareModal({ fileId, onClose }: Props) {
  const [info, setInfo] = useState<ShareInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [expiresInDays, setExpiresInDays] = useState<7 | 30 | null>(7)
  const [copied, setCopied] = useState(false)
  const isMountedRef = useRef(true)

  useEffect(() => {
    return () => { isMountedRef.current = false }
  }, [])

  useEffect(() => {
    api.getShareStatus(fileId)
      .then(res => { if (isMountedRef.current) setInfo(res) })
      .finally(() => { if (isMountedRef.current) setLoading(false) })
  }, [fileId])

  async function handleCreate() {
    setLoading(true)
    try {
      const res = await api.createShareLink(fileId, expiresInDays)
      if (isMountedRef.current) setInfo(res)
    } catch (e) {
      console.error('공유 링크 생성 실패', e)
    } finally {
      if (isMountedRef.current) setLoading(false)
    }
  }

  async function handleRevoke() {
    setLoading(true)
    try {
      await api.revokeShareLink(fileId)
      if (isMountedRef.current) setInfo({ token: null, expires_at: null })
    } catch (e) {
      console.error('공유 중단 실패', e)
    } finally {
      if (isMountedRef.current) setLoading(false)
    }
  }

  function handleCopy() {
    if (!info?.token) return
    navigator.clipboard.writeText(`${window.location.origin}/share/${info.token}`)
    setCopied(true)
    setTimeout(() => {
      if (isMountedRef.current) setCopied(false)
    }, 1500)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#fff', padding: 16, minWidth: 300 }}>
        <h3 style={{ marginTop: 0 }}>공유 링크</h3>

        {loading && <p>로딩 중…</p>}

        {!loading && info?.token && (
          <div>
            <input readOnly value={`${window.location.origin}/share/${info.token}`} style={{ width: '100%' }} />
            <p style={{ fontSize: 12, color: '#666' }}>
              만료: {info.expires_at ? new Date(info.expires_at).toLocaleDateString() : '무기한'}
            </p>
            <button onClick={handleCopy}>{copied ? '복사됨' : '복사'}</button>
            <button onClick={handleRevoke}>공유 중단</button>
          </div>
        )}

        {!loading && !info?.token && (
          <div>
            <label>
              만료:
              <select
                aria-label="만료기간"
                value={expiresInDays === null ? 'null' : String(expiresInDays)}
                onChange={e => setExpiresInDays(e.target.value === 'null' ? null : (Number(e.target.value) as 7 | 30))}
              >
                <option value="7">7일</option>
                <option value="30">30일</option>
                <option value="null">무기한</option>
              </select>
            </label>
            <button onClick={handleCreate}>링크 생성</button>
          </div>
        )}

        <div style={{ marginTop: 8 }}>
          <button onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  )
}
