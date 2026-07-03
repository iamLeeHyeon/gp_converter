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

  return (
    <div style={{ marginTop: 16, fontSize: 12, borderTop: '1px solid #ddd', paddingTop: 12 }}>
      <strong>요금제: {usage.plan === 'pro' ? 'Pro' : 'Free'}</strong>
      {usage.plan === 'free' ? (
        <div>
          <p>변환 {usage.conversions_used}/{usage.conversions_limit}</p>
          <p>저장 {usage.files_used}/{usage.files_limit}</p>
          <button onClick={handleUpgrade} disabled={busy}>Pro로 업그레이드</button>
        </div>
      ) : (
        <div>
          <p>무제한</p>
          <button onClick={handleManage} disabled={busy}>구독 관리</button>
        </div>
      )}
    </div>
  )
}
