import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

export default function OAuthCallback() {
  const navigate = useNavigate()
  const setToken = useAuthStore((s) => s.setToken)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
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
