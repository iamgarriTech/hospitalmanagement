/**
 * Everything goes through this app's own /api path, which proxies to Django
 * server-side (see app/api/[...path]/route.ts). There is no base URL and no
 * bearer token: the session is an HttpOnly cookie on this origin, so requests
 * simply carry it.
 */

export class ApiError extends Error {
  status: number
  /** Field-level errors, as DRF returns them, for rendering next to inputs. */
  fields: Record<string, string[]>
  /** The whole body, for the few endpoints that return structured payloads
   *  alongside a non-2xx — duplicate-patient candidates, safety warnings. */
  body: unknown

  constructor(status: number, detail: string, fields: Record<string, string[]> = {}, body: unknown = null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields
    this.body = body
  }
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * Django's CSRF cookie is readable by script on purpose — it has to be echoed
 * back in a header. It is not a credential: the session cookie is, and that
 * one stays HttpOnly.
 */
export async function ensureCsrfCookie(): Promise<void> {
  if (readCookie('csrftoken')) return
  await fetch('/api/auth/csrf/', { credentials: 'same-origin' })
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const isWrite = method !== 'GET'

  if (isWrite) await ensureCsrfCookie()

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (isWrite) {
    const token = readCookie('csrftoken')
    if (token) headers['X-CSRFToken'] = token
  }

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    signal: options.signal,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { detail: text }
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(response.status, payload), extractFields(payload), payload)
  }
  return payload as T
}

function extractDetail(status: number, payload: unknown): string {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>
    if (typeof record.detail === 'string') return record.detail
    // DRF field errors arrive as { field: ["message"] } with no `detail`.
    const first = Object.values(record).find(
      (value) => Array.isArray(value) && typeof value[0] === 'string',
    ) as string[] | undefined
    if (first) return first[0]
  }
  if (status === 403) return 'You do not have permission to do that.'
  if (status === 404) return 'Not found.'
  return 'Something went wrong. Please try again.'
}

function extractFields(payload: unknown): Record<string, string[]> {
  if (!payload || typeof payload !== 'object') return {}
  const fields: Record<string, string[]> = {}
  for (const [key, value] of Object.entries(payload as Record<string, unknown>)) {
    if (key === 'detail') continue
    if (Array.isArray(value) && value.every((entry) => typeof entry === 'string')) {
      fields[key] = value as string[]
    }
  }
  return fields
}

/** DRF page shape, so list screens do not each re-derive it. */
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] }

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}
