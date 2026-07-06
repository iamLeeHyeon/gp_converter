import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleSubmit = async () => {
    setError('')
    if (password !== confirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    const res = await fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail || '재설정에 실패했습니다.')
      return
    }
    navigate('/login')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>비밀번호 재설정</h1>
      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="password" placeholder="새 비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input type="password" placeholder="새 비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleSubmit} style={{ padding: '10px', cursor: 'pointer' }}>비밀번호 변경</button>
      </div>
    </div>
  )
}
