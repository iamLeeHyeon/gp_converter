import { useState } from 'react'
import { Link } from 'react-router-dom'

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
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>비밀번호 찾기</h1>
      {sent ? (
        <p>메일이 발송되었으면 잠시 후 확인해주세요.</p>
      ) : (
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
          <input type="email" placeholder="가입한 이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button onClick={handleSubmit} style={{ padding: '10px', cursor: 'pointer' }}>재설정 링크 받기</button>
        </div>
      )}
      <Link to="/login" style={{ fontSize: 13, marginTop: 16 }}>로그인으로 돌아가기</Link>
    </div>
  )
}
