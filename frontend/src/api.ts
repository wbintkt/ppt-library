import { resetSearchState } from './searchState'
// API 封装（带 token 管理）
const BASE = '/ppt/api'

export interface TokenResp { access_token: string; token_type: string; username: string }
export interface FileSummary {
  id: number; name: string; category: string; tags: string; source: string
  file_size: number; page_count: number; status: string; error_message: string
  progress: number; upload_time: string; update_time: string
}
export interface PageSummary {
  id: number; file_id: number; page_no: number; title: string; text: string
  tags: string; embedding_status: string; file_name: string; file_category: string; file_source: string
}
export interface SearchItem {
  page_id: number; file_id: number; file_name: string; page_no: number
  title: string; text: string; tags: string; score: number; display_score: number | null
  embedding_status: string; category: string
}
export interface SearchResp { query: string; total: number; items: SearchItem[] }
export interface Stats { total_files: number; total_pages: number; indexed_pages: number; ready_files: number; vector_mode: boolean }
export interface SettingsInfo {
  embed_model: string; embed_dim: number; has_api_key: boolean
  total_files: number; total_pages: number; indexed_pages: number
}

export function getToken(): string {
  return localStorage.getItem('ppt_token') || ''
}

export function setToken(t: string) {
  localStorage.setItem('ppt_token', t)
}

export function clearToken() {
  localStorage.removeItem('ppt_token')
  resetSearchState()
}

export function isAuthed(): boolean {
  return !!getToken()
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string> || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(BASE + path, { ...options, headers })
  if (resp.status === 401) {
    clearToken()
    if (!location.hash.includes('/login')) location.hash = '#/login'
    throw new Error('登录已失效')
  }
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`
    try {
      const data = await resp.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

export const api = {
  login: (username: string, password: string) =>
    request<TokenResp>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`,
    }),
  upload: (file: File, category: string, tags: string, source: string, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    form.append('category', category)
    form.append('tags', tags)
    form.append('source', source)
    return new Promise<FileSummary>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${BASE}/files/upload`)
      xhr.setRequestHeader('Authorization', `Bearer ${getToken()}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText)
          if (xhr.status >= 200 && xhr.status < 300) resolve(data as FileSummary)
          else reject(new Error(data?.detail || `上传失败 (${xhr.status})`))
        } catch {
          reject(new Error(`上传失败 (${xhr.status})`))
        }
      }
      xhr.onerror = () => reject(new Error('网络错误'))
      xhr.send(form)
    })
  },
  listFiles: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString()
    return request<{ total: number; items: FileSummary[] }>(`/files?${qs}`)
  },
  getFile: (id: number) => request<FileSummary>(`/files/${id}`),
  getPage: (id: number) => request<PageSummary>(`/pages/${id}`),
  updateFile: (id: number, body: Record<string, string>) =>
    request<FileSummary>(`/files/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  deleteFile: (id: number) => request<{ ok: boolean }>(`/files/${id}`, { method: 'DELETE' }),
  reindex: (id: number) => request<{ ok: boolean }>(`/files/${id}/reindex`, { method: 'POST' }),
  downloadUrl: (id: number) => `${BASE}/files/${id}/download?token=${getToken()}`,
  categories: () => request<{ category: string; count: number }[]>('/files/categories'),
  taskStatus: (id: number) => request<{ file_id: number; status: string; progress: number; error_message: string; page_count: number }>(`/tasks/${id}`),
  listPages: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString()
    return request<{ total: number; items: PageSummary[] }>(`/pages?${qs}`)
  },
  search: (query: string, category: string = '', topK: number = 20, signal?: AbortSignal) =>
    request<SearchResp>('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, category, top_k: topK }),
      signal,
    }),
  pageImageUrl: (pageId: number) => `${BASE}/pages/${pageId}/image?token=${getToken()}`,
  exportPages: async (pageIds: number[]): Promise<Blob> => {
    const resp = await fetch(`${BASE}/pages/export`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ page_ids: pageIds }),
    })
    if (!resp.ok) {
      let detail = `导出失败 (${resp.status})`
      try {
        const data = await resp.json()
        if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
      } catch { /* ignore */ }
      throw new Error(detail)
    }
    return resp.blob()
  },
  similarPages: (pageId: number, topK: number = 6) =>
    request<{ page_id: number; file_id: number; page_no: number; title: string; text: string; file_name: string; score: number }[]>(`/pages/${pageId}/similar?top_k=${topK}`),
  stats: () => request<Stats>('/stats'),
  settings: () => request<SettingsInfo>('/settings'),
  saveApiKey: (key: string) =>
    request<{ ok: boolean; has_api_key: boolean }>('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dashscope_api_key: key }),
    }),
}

// 图片 URL 需要 token，手动拼接 query
export function imageUrl(pageId: number): string {
  return `${BASE}/pages/${pageId}/image?token=${encodeURIComponent(getToken())}`
}
