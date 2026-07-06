import { create } from 'zustand'
import { api } from '../lib/api'

interface AuthState {
  token: string | null
  emailVerified: boolean | null
  plan: string | null
  setToken: (access: string, refresh: string) => void
  logout: () => void
  fetchMe: () => Promise<void>
  refreshAccessToken: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('access_token'),
  emailVerified: null,
  plan: null,
  setToken: (access, refresh) => {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
    set({ token: access })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ token: null, emailVerified: null, plan: null })
  },
  fetchMe: async () => {
    const token = get().token
    if (!token) return
    try {
      const res = await fetch('/auth/me', { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) return
      const data = await res.json()
      set({ emailVerified: data.email_verified, plan: data.plan })
    } catch {
      // /auth/me 조회 실패해도 호출부(로그인/가입) 흐름은 막지 않는다
    }
  },

  refreshAccessToken: async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) return
    try {
      const data = await api.refreshToken(refreshToken)
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      set({ token: data.access_token })
    } catch {
      // refresh_token 자체가 만료/무효 — 액세스 토큰만 조용히 죽어있는 상태로
      // 두면 로그인 화면인 것처럼 보이면서 실제로는 익명으로 동작하는(예: 변환은
      // 되는데 "내 파일"엔 저장 안 되는) 혼란스러운 상태가 된다. 명시적으로
      // 로그아웃시켜서 사용자가 다시 로그인하도록 한다.
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      set({ token: null, emailVerified: null, plan: null })
    }
  },
}))
