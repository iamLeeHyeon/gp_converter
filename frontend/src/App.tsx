import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useEditorStore } from './store/editorStore'
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

function MainPage() {
  const [gp5Buffer, setGp5Buffer] = useState<ArrayBuffer | null>(null)
  const { token, emailVerified, logout, fetchMe } = useAuthStore()
  const { setFileId, clearHistory } = useEditorStore()

  useEffect(() => {
    if (token) fetchMe()
  }, [token])

  const handleComplete = (_jobId: string, buf: ArrayBuffer, fileId?: string | null) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId ?? null)
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
          <p style={{ fontSize: 13, color: '#666' }}>로그인하면 파일이 저장됩니다</p>
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
