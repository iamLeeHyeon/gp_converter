import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../lib/api'
import AuthLayout from './AuthLayout'

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
    try {
      await api.resetPassword(token, password)
      navigate('/login')
    } catch (e) {
      setError(e instanceof Error ? e.message : '재설정에 실패했습니다.')
    }
  }

  return (
    <AuthLayout title="비밀번호 재설정">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <input className="field" type="password" placeholder="새 비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input className="field" type="password" placeholder="새 비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}
        <button onClick={handleSubmit} className="btn-primary" style={{ marginTop: 4 }}>비밀번호 변경</button>
      </div>
    </AuthLayout>
  )
}
