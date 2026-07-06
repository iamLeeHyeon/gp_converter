import { create } from 'zustand'

interface AuthState {
  token: string | null
  emailVerified: boolean | null
  plan: string | null
  setToken: (access: string, refresh: string) => void
  logout: () => void
  fetchMe: () => Promise<void>
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
}))
