import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

export default function OAuthCallback() {
  const navigate = useNavigate()
  const setToken = useAuthStore((s) => s.setToken)
  const processed = useRef(false)

  useEffect(() => {
    // StrictMode(dev)가 effect를 두 번 실행한다. navigate('/')가 URL 해시를
    // 지우기 때문에, 가드 없이 두 번째로 실행되면 "해시 없음"으로 읽어
    // /login으로 되돌려보낸다(실사례로 재현된 버그) — 한 번만 처리하게 막는다.
    if (processed.current) return
    processed.current = true

    const hash = window.location.hash.slice(1) // '#' 제거
    const params = new URLSearchParams(hash)
    const access = params.get('access_token')
    const refresh = params.get('refresh_token')
    if (access && refresh) {
      setToken(access, refresh)
      navigate('/', { replace: true })
    } else {
      navigate('/login', { replace: true })
    }
  }, [navigate, setToken])

  return <p>로그인 처리 중...</p>
}
