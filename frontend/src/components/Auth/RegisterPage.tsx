import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

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
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail || '회원가입에 실패했습니다.')
      return
    }
    const data = await res.json()
    setToken(data.access_token, data.refresh_token)
    await fetchMe()
    setRegistered(true)
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
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
        <h1>가입 완료</h1>
        <p>인증 메일을 확인해주세요. 인증 전까지는 PDF 변환을 사용할 수 없습니다.</p>
        <button onClick={handleResend} style={{ marginTop: 16, cursor: 'pointer' }}>인증메일 다시 받기</button>
        <button onClick={() => navigate('/')} style={{ marginTop: 8, cursor: 'pointer' }}>앱으로 이동</button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>회원가입</h1>
      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input type="password" placeholder="비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleRegister} style={{ padding: '10px', cursor: 'pointer' }}>가입하기</button>
        <Link to="/login" style={{ fontSize: 13 }}>이미 계정이 있으신가요? 로그인</Link>
      </div>
    </div>
  )
}
