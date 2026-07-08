import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import { api } from '../../lib/api'
import AuthLayout from './AuthLayout'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [registered, setRegistered] = useState(false)
  const navigate = useNavigate()
  const { setToken, fetchMe } = useAuthStore()

  const handleRegister = async () => {
    setError('')
    if (password !== confirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    try {
      const data = await api.register(email, password)
      setToken(data.access_token, data.refresh_token)
      await fetchMe()
      setRegistered(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '회원가입에 실패했습니다.')
    }
  }

  const handleResend = async () => {
    await fetch('/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
  }

  if (registered) {
    return (
      <AuthLayout title="가입 완료" subtitle="인증 메일을 확인해주세요. 인증 전까지는 PDF 변환을 사용할 수 없습니다.">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <button onClick={handleResend} className="btn-ghost">인증메일 다시 받기</button>
          <button onClick={() => navigate('/')} className="btn-primary">앱으로 이동</button>
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title="회원가입">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <input className="field" type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="field" type="password" placeholder="비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input className="field" type="password" placeholder="비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}
        <button onClick={handleRegister} className="btn-primary" style={{ marginTop: 4 }}>가입하기</button>
        <Link to="/login" style={{ fontSize: 13, textAlign: 'center', marginTop: 4 }}>이미 계정이 있으신가요? 로그인</Link>
      </div>
    </AuthLayout>
  )
}
