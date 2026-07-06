import { vi, beforeEach, afterEach, describe, it, expect } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    refreshToken: vi.fn(),
  },
}))

import { api } from '../lib/api'
import { useAuthStore } from '../store/authStore'

describe('authStore.refreshAccessToken', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    useAuthStore.setState({ token: null, emailVerified: null, plan: null })
  })

  it('refresh_token이 없으면 아무 것도 안 하고 조용히 리턴한다', async () => {
    await useAuthStore.getState().refreshAccessToken()
    expect(api.refreshToken).not.toHaveBeenCalled()
  })

  it('성공하면 access_token/refresh_token을 새로 저장하고 store token을 갱신한다', async () => {
    localStorage.setItem('access_token', 'old-access')
    localStorage.setItem('refresh_token', 'old-refresh')
    vi.mocked(api.refreshToken).mockResolvedValueOnce({
      access_token: 'new-access',
      refresh_token: 'new-refresh',
    })

    await useAuthStore.getState().refreshAccessToken()

    expect(api.refreshToken).toHaveBeenCalledWith('old-refresh')
    expect(localStorage.getItem('access_token')).toBe('new-access')
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh')
    expect(useAuthStore.getState().token).toBe('new-access')
  })

  it('refresh_token 자체가 만료/무효면 로그아웃 처리한다', async () => {
    localStorage.setItem('access_token', 'old-access')
    localStorage.setItem('refresh_token', 'expired-refresh')
    useAuthStore.setState({ token: 'old-access', emailVerified: true, plan: 'free' })
    vi.mocked(api.refreshToken).mockRejectedValueOnce(new Error('HTTP 401'))

    await useAuthStore.getState().refreshAccessToken()

    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
    expect(useAuthStore.getState().token).toBeNull()
  })
})
