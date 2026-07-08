import { useState } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'
import { api } from '../../lib/api'

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
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>GP Converter</h1>
      <p>PDF 악보를 Guitar Pro 파일로 변환하고 웹에서 편집하세요</p>

      {verifyStatus === 'success' && (
        <p style={{ color: 'green' }}>이메일 인증이 완료되었습니다. 로그인해주세요.</p>
      )}
      {verifyStatus === 'expired' && (
        <p style={{ color: 'red' }}>인증 링크가 유효하지 않거나 만료되었습니다.</p>
      )}

      <div style={{ display: 'flex', gap: 16, marginTop: 32 }}>
        <button
          onClick={() => { window.location.href = '/auth/google' }}
          style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
        >
          Google로 로그인
        </button>
      </div>

      <div style={{ marginTop: 32, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleLogin} style={{ padding: '10px', cursor: 'pointer' }}>이메일로 로그인</button>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
          <Link to="/register">회원가입</Link>
          <Link to="/forgot-password">비밀번호를 잊으셨나요?</Link>
        </div>
      </div>
    </div>
  )
}
