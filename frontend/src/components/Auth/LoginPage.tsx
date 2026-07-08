import { useState } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import { api } from '../../lib/api'
import AuthLayout from './AuthLayout'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { setToken, fetchMe } = useAuthStore()
  const [searchParams] = useSearchParams()
  const verifyStatus = searchParams.get('verify')

  const handleLogin = async () => {
    setError('')
    try {
      const data = await api.login(email, password)
      setToken(data.access_token, data.refresh_token)
      await fetchMe()
      navigate('/')
    } catch (e) {
      setError(e instanceof Error ? e.message : '로그인에 실패했습니다.')
    }
  }

  return (
    <AuthLayout title="GP Converter" subtitle="PDF 악보를 Guitar Pro 파일로 변환하고 웹에서 편집하세요">
      {verifyStatus === 'success' && (
        <p style={{ color: 'var(--color-primary)', fontSize: 13, marginBottom: 12 }}>이메일 인증이 완료되었습니다. 로그인해주세요.</p>
      )}
      {verifyStatus === 'expired' && (
        <p style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 12 }}>인증 링크가 유효하지 않거나 만료되었습니다.</p>
      )}

      <button
        onClick={() => { window.location.href = '/auth/google' }}
        className="btn-ghost"
        style={{ width: '100%' }}
      >
        Google로 로그인
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '20px 0' }}>
        <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
        <span style={{ fontSize: 12, color: 'var(--color-muted)' }}>또는</span>
        <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <input className="field" type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="field" type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{error}</p>}
        <button onClick={handleLogin} className="btn-primary" style={{ marginTop: 4 }}>이메일로 로그인</button>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginTop: 4 }}>
          <Link to="/register">회원가입</Link>
          <Link to="/forgot-password">비밀번호를 잊으셨나요?</Link>
        </div>
      </div>
    </AuthLayout>
  )
}
