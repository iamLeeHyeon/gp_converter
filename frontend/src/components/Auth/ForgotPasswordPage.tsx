import { useState } from 'react'
import { Link } from 'react-router-dom'
import AuthLayout from './AuthLayout'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)

  const handleSubmit = async () => {
    await fetch('/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    setSent(true)
  }

  return (
    <AuthLayout title="비밀번호 찾기">
      {sent ? (
        <p style={{ fontSize: 14, color: 'var(--color-muted)', textAlign: 'center' }}>메일이 발송되었으면 잠시 후 확인해주세요.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <input className="field" type="email" placeholder="가입한 이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button onClick={handleSubmit} className="btn-primary">재설정 링크 받기</button>
        </div>
      )}
      <Link to="/login" style={{ fontSize: 13, display: 'block', textAlign: 'center', marginTop: 16 }}>로그인으로 돌아가기</Link>
    </AuthLayout>
  )
}
