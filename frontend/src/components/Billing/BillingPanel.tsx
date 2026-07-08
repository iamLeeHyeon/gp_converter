import { useEffect, useRef, useState } from 'react'
import { api, type UsageInfo } from '../../lib/api'

export default function BillingPanel() {
  const [usage, setUsage] = useState<UsageInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const isMountedRef = useRef(true)

  useEffect(() => {
    return () => { isMountedRef.current = false }
  }, [])

  useEffect(() => {
    let cancelled = false
    api.getUsage()
      .then(res => { if (!cancelled) setUsage(res) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function handleUpgrade() {
    setBusy(true)
    try {
      const { url } = await api.createCheckoutSession()
      window.location.href = url
    } catch {
      if (isMountedRef.current) setBusy(false)
    }
  }

  async function handleManage() {
    setBusy(true)
    try {
      const { url } = await api.createPortalSession()
      window.location.href = url
    } catch {
      if (isMountedRef.current) setBusy(false)
    }
  }

  if (!usage) return null

  const buttonStyle = {
    marginTop: 8,
    background: 'rgba(255,255,255,0.15)',
    border: '1px solid rgba(255,255,255,0.6)',
    color: '#ffffff',
    borderRadius: 8,
    padding: '6px 12px',
    fontSize: 12,
    cursor: 'pointer',
  }

  return (
    <div style={{ marginTop: 16, fontSize: 12, borderTop: '1px solid rgba(255,255,255,0.3)', paddingTop: 12, color: 'rgba(255,255,255,0.9)' }}>
      <strong style={{ color: '#ffffff' }}>요금제: {usage.plan === 'pro' ? 'Pro' : 'Free'}</strong>
      {usage.plan === 'free' ? (
        <div>
          <p style={{ margin: '4px 0' }}>변환 {usage.conversions_used}/{usage.conversions_limit}</p>
          <p style={{ margin: '4px 0' }}>저장 {usage.files_used}/{usage.files_limit}</p>
          <button onClick={handleUpgrade} disabled={busy} style={buttonStyle}>Pro로 업그레이드</button>
        </div>
      ) : (
        <div>
          <p style={{ margin: '4px 0' }}>무제한</p>
          <button onClick={handleManage} disabled={busy} style={buttonStyle}>구독 관리</button>
        </div>
      )}
    </div>
  )
}
