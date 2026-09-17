const TOKEN_KEY = 'muzikk.token'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* private browsing */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private browsing */
  }
}

type RequestOptions = {
  method?: string
  body?: unknown
  query?: Record<string, string | number | boolean | undefined | null>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = path.startsWith('/api') ? path : `/api${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const serialized = params.toString()
  return serialized ? `${url}?${serialized}` : url
}

/** FastAPI answers with a string detail, or a list of validation errors. */
function extractDetail(payload: unknown): string {
  if (typeof payload === 'string') return payload
  if (!payload || typeof payload !== 'object') return ''
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === 'object' && 'msg' in item
          ? String((item as { msg: unknown }).msg)
          : String(item),
      )
      .join(', ')
  }
  return ''
}

export async function apiUpload<T>(path: string, body: FormData): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    body,
  })

  if (response.status === 204) return undefined as T

  const raw = await response.text()
  let payload: unknown = null
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch {
      payload = raw
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(payload) || `HTTP ${response.status}`)
  }

  return payload as T
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (response.status === 204) return undefined as T

  const raw = await response.text()
  let payload: unknown = null
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch {
      payload = raw
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(payload) || `HTTP ${response.status}`)
  }

  return payload as T
}

/** Same idea for <audio>, which cannot send an Authorization header either. */
export function streamUrl(path: string): string {
  const token = getToken()
  return token ? `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}` : path
}

/**
 * Why a media element refused a URL.
 *
 * An <audio> error event carries no HTTP status, so the same URL is asked again
 * for its first two bytes: cheap, and the server explains itself in JSON.
 */
export async function probeMedia(path: string): Promise<string> {
  try {
    const response = await fetch(buildUrl(path), {
      headers: { Range: 'bytes=0-1', ...authHeader() },
      credentials: 'same-origin',
    })
    if (response.ok || response.status === 206) return ''
    const raw = await response.text()
    let payload: unknown = raw
    try {
      payload = JSON.parse(raw)
    } catch {
      /* not JSON: keep the raw body */
    }
    return extractDetail(payload) || `HTTP ${response.status}`
  } catch (cause) {
    return cause instanceof Error ? cause.message : ''
  }
}

function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Image URLs travel through <img>, which cannot send an Authorization header. */
export function imageUrl(path: string | null | undefined, size?: number): string | undefined {
  if (!path) return undefined
  const token = getToken()
  const params = new URLSearchParams()
  if (size) params.set(path.includes('/jellyfin/') ? 'height' : 'size', String(size))
  if (token) params.set('token', token)
  const serialized = params.toString()
  return serialized ? `${path}${path.includes('?') ? '&' : '?'}${serialized}` : path
}
