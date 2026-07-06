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

async function downloadBlob(url: string, filename: string): Promise<void> {
  const res = await fetch(url, { headers: authHeaders() })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  const blob = await res.blob()
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  a.click()
  URL.revokeObjectURL(href)
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  async upload(file: File): Promise<{ job_id: string; file_id: string | null }> {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/convert', { method: 'POST', body: fd, headers: authHeaders() })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },

  async getResult(jobId: string): Promise<ArrayBuffer> {
    const res = await fetch(`/jobs/${jobId}/result`, { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.arrayBuffer()
  },

  async listFiles(): Promise<FileRecord[]> {
    return request<FileRecord[]>('/files')
  },

  async deleteFile(id: string): Promise<void> {
    await request<void>(`/files/${id}`, { method: 'DELETE' })
  },

  async syncFile(fileId: string, snapshot: ScoreSnapshot): Promise<void> {
    await request<{ ok: boolean }>(`/files/${fileId}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(snapshot),
    })
  },

  async getGP5Buffer(fileId: string): Promise<ArrayBuffer> {
    const res = await fetch(`/files/${fileId}/download`, { headers: authHeaders() })
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
