import type { ScoreSnapshot } from './scoreTypes'

export interface FileRecord {
  id: string
  name: string
  created_at: string
}

function getToken(): string {
  return localStorage.getItem('access_token') ?? ''
}

function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
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
}
