export default function LoginPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>GP Converter</h1>
      <p>PDF 악보를 Guitar Pro 파일로 변환하고 웹에서 편집하세요</p>
      <div style={{ display: 'flex', gap: 16, marginTop: 32 }}>
        <button
          onClick={() => { window.location.href = '/auth/google' }}
          style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
        >
          Google로 로그인
        </button>
        <button
          onClick={() => { window.location.href = '/auth/github' }}
          style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
        >
          GitHub로 로그인
        </button>
      </div>
    </div>
  )
}
