import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useEditorStore } from './store/editorStore'
import { useFileStore } from './store/fileStore'
import LoginPage from './components/Auth/LoginPage'
import RegisterPage from './components/Auth/RegisterPage'
import ForgotPasswordPage from './components/Auth/ForgotPasswordPage'
import ResetPasswordPage from './components/Auth/ResetPasswordPage'
import OAuthCallback from './components/Auth/OAuthCallback'
import ScoreViewer from './components/Editor/ScoreViewer'
import SharedScoreViewer from './components/Editor/SharedScoreViewer'
import UploadButton from './components/FileManager/UploadButton'
import FileList from './components/FileManager/FileList'
import BillingPanel from './components/Billing/BillingPanel'

// 액세스 토큰 수명(15분)보다 여유있게 10분마다 갱신 — 그냥 두면 세션이 조용히
// 죽어서(에러 없이) 로그인된 것처럼 보이는 화면에서 실제로는 익명으로 동작하는
// 혼란스러운 상태가 된다(예: 변환은 되는데 "내 파일"에 저장이 안 됨).
const TOKEN_REFRESH_INTERVAL_MS = 10 * 60 * 1000

function MainPage() {
  const [gp5Buffer, setGp5Buffer] = useState<ArrayBuffer | null>(null)
  const { token, emailVerified, logout, fetchMe, refreshAccessToken } = useAuthStore()
  const { setFileId, clearHistory } = useEditorStore()
  const { load: loadFiles } = useFileStore()

  useEffect(() => {
    if (token) fetchMe()
  }, [token])

  useEffect(() => {
    if (!token) return
    const id = setInterval(() => { refreshAccessToken() }, TOKEN_REFRESH_INTERVAL_MS)
    return () => clearInterval(id)
  }, [token, refreshAccessToken])

  const handleComplete = (_jobId: string, buf: ArrayBuffer, fileId?: string | null) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId ?? null)
    if (fileId) loadFiles()
  }

  const handleFileSelect = (buf: ArrayBuffer, fileId: string) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId)
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {/* 사이드바 */}
      <aside style={{ width: 260, minWidth: 200, borderRight: '1px solid #ddd', padding: 16, overflowY: 'auto', flexShrink: 0 }}>
        <h2 style={{ marginTop: 0 }}>GP Converter</h2>
        {token && emailVerified === false && (
          <div style={{ background: '#fff3cd', padding: 8, fontSize: 12, marginBottom: 12 }}>
            이메일 인증이 필요합니다 — 메일함을 확인하세요.
          </div>
        )}
        <UploadButton onComplete={handleComplete} />
        <hr />
        <h3>내 파일</h3>
        {token ? (
          <FileList onSelect={handleFileSelect} />
        ) : (
          <p style={{ fontSize: 13, color: '#666' }}>
            <Link to="/login">로그인</Link>하면 파일이 저장됩니다
          </p>
        )}
        {token && (
          <button onClick={logout} style={{ marginTop: 16, fontSize: 12 }}>로그아웃</button>
        )}
        {token && <BillingPanel />}
      </aside>

      {/* 메인 편집 영역 */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <ScoreViewer gp5Buffer={gp5Buffer} />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/auth/callback" element={<OAuthCallback />} />
        <Route path="/" element={<MainPage />} />
        <Route path="/share/:token" element={<SharedScoreViewer />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
