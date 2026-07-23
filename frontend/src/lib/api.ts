import type { ScoreSnapshot } from './scoreTypes'

export interface FileRecord {
  id: string
  name: string
  created_at: string
}

export interface ShareInfo {
  token: string | null
  expires_at: string | null
}

export interface UsageInfo {
  plan: string
  conversions_used: number
  conversions_limit: number
  files_used: number
  files_limit: number
}

function getToken(): string {
  return localStorage.getItem('access_token') ?? ''
}

function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// 액세스 토큰은 15분이면 만료되는데, App.tsx의 10분 주기 자동갱신은 페이지가
// 열려있는 동안만 보장한다 — 이미 만료된 채로 페이지를 새로고침하거나 갱신
// 타이머가 아직 안 돈 시점에 요청을 보내면 401을 받는다(실사용 중 재현된
// 버그: 변환은 되는데 만료 토큰이 익명 요청으로 처리돼 "내 파일"에 하나도
// 안 남았음). 어떤 요청이든 401을 받으면 그 자리에서 리프레시 토큰으로
// 갱신 후 한 번 재시도해서, 타이밍에 의존하지 않고 항상 복구되게 한다.
let refreshPromise: Promise<string | null> | null = null

async function refreshAccessTokenOnce(): Promise<string | null> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const rt = localStorage.getItem('refresh_token')
    if (!rt) return null
    try {
      const res = await fetch('/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      })
      if (!res.ok) return null
      const data = await res.json()
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      return data.access_token as string
    } catch {
      return null
    }
  })()
  try {
    return await refreshPromise
  } finally {
    refreshPromise = null
  }
}

async function fetchWithAuth(url: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, { ...init, headers: { ...authHeaders(), ...(init.headers ?? {}) } })
  if (res.status !== 401 || !getToken()) return res
  const newToken = await refreshAccessTokenOnce()
  if (!newToken) return res
  return fetch(url, { ...init, headers: { ...authHeaders(), ...(init.headers ?? {}) } })
}

async function downloadBlob(url: string, filename: string): Promise<void> {
  const res = await fetchWithAuth(url)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  const blob = await res.blob()
  api.downloadBuffer(await blob.arrayBuffer(), filename)
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetchWithAuth(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json()
}

export const api = {
  async login(email: string, password: string): Promise<{ access_token: string; refresh_token: string }> {
    return request('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  },

  async register(email: string, password: string): Promise<{ access_token: string; refresh_token: string }> {
    return request('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  },

  async resetPassword(token: string, newPassword: string): Promise<void> {
    await request('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword }),
    })
  },

  async refreshToken(refreshToken: string): Promise<{ access_token: string; refresh_token: string }> {
    const res = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },

  async upload(file: File): Promise<{ job_id: string; file_id: string | null }> {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetchWithAuth('/convert', { method: 'POST', body: fd })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },

  async getResult(jobId: string): Promise<ArrayBuffer> {
    const res = await fetchWithAuth(`/jobs/${jobId}/result`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.arrayBuffer()
  },

  async listFiles(): Promise<FileRecord[]> {
    return request<FileRecord[]>('/files')
  },

  async deleteFile(id: string): Promise<void> {
    await request<void>(`/files/${id}`, { method: 'DELETE' })
  },

  async syncFile(fileId: string, snapshot: ScoreSnapshot, opts?: { keepalive?: boolean }): Promise<void> {
    await request<{ ok: boolean }>(`/files/${fileId}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
      keepalive: opts?.keepalive,
    })
  },

  async getGP5Buffer(fileId: string): Promise<ArrayBuffer> {
    const res = await fetchWithAuth(`/files/${fileId}/download`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.arrayBuffer()
  },

  async downloadGP5(fileId: string, filename: string): Promise<void> {
    await downloadBlob(`/files/${fileId}/download`, filename)
  },

  async downloadMIDI(fileId: string, filename: string): Promise<void> {
    await downloadBlob(`/files/${fileId}/export/midi`, filename)
  },

  downloadBuffer(buffer: ArrayBuffer, filename: string): void {
    const blob = new Blob([buffer], { type: 'application/octet-stream' })
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    URL.revokeObjectURL(href)
  },

  async getShareStatus(fileId: string): Promise<ShareInfo> {
    return request<ShareInfo>(`/files/${fileId}/share`)
  },

  async createShareLink(fileId: string, expiresInDays: 7 | 30 | null): Promise<ShareInfo> {
    return request<ShareInfo>(`/files/${fileId}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_in_days: expiresInDays }),
    })
  },

  async revokeShareLink(fileId: string): Promise<void> {
    await request<unknown>(`/files/${fileId}/share`, { method: 'DELETE' })
  },

  async fetchSharedGP5(token: string): Promise<ArrayBuffer> {
    const res = await fetch(`/files/shared/${token}`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.arrayBuffer()
  },

  async getUsage(): Promise<UsageInfo> {
    return request<UsageInfo>('/billing/usage')
  },

  async createCheckoutSession(): Promise<{ url: string }> {
    return request<{ url: string }>('/billing/checkout', { method: 'POST' })
  },

  async createPortalSession(): Promise<{ url: string }> {
    return request<{ url: string }>('/billing/portal', { method: 'POST' })
  },
}
