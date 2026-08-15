/**
 * The HTTP client.
 *
 * One origin in both environments: production serves the bundle and the API
 * from the same Gunicorn process, and in development Vite proxies /api to
 * Django. So requests are relative, always — an absolute URL here would be the
 * one thing that behaves differently after deployment (BUILD_PLAN §2.3, P-05).
 */

import type { Money } from './money'

// ---------------------------------------------------------------------------
// The error shape — one from every endpoint (§8.3)
// ---------------------------------------------------------------------------

export interface ApiFieldError {
  readonly code: string
  readonly message: string
}

export interface ApiErrorDetail {
  readonly code: string
  readonly message: string
  /** Rendered inline against the offending input. */
  readonly field_errors: Readonly<Record<string, readonly ApiFieldError[]>>
  /** Rendered as a banner stating that nothing was saved. */
  readonly non_field_errors: readonly ApiFieldError[]
  readonly correlation_id: string
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }

  /** The first message for a named field, if the server raised one. */
  fieldError(name: string): string | undefined {
    return this.detail.field_errors[name]?.[0]?.message
  }

  get nonFieldMessages(): readonly string[] {
    return this.detail.non_field_errors.map((error) => error.message)
  }

  get isUnauthenticated(): boolean {
    return this.status === 401 || this.status === 403
  }
}

const UNPARSEABLE: ApiErrorDetail = {
  code: 'unreachable',
  message:
    'The application did not answer. It may not be running — check that the Django ' +
    'development server is up on the port named in .env.',
  field_errors: {},
  non_field_errors: [],
  correlation_id: '',
}

// ---------------------------------------------------------------------------
// Advisories — never errors (§8.3)
// ---------------------------------------------------------------------------

export type AdvisoryKind = 'probable_duplicate' | 'rate_variance' | 'historic_restatement'

export interface Advisory {
  readonly kind: AdvisoryKind
  readonly message: string
  readonly detail: Readonly<Record<string, unknown>>
}

/** A successful response that may carry advisories. Its data was saved. */
export interface Envelope<T> {
  readonly data: T
  readonly advisories: readonly Advisory[]
}

export interface CompletenessSummary {
  readonly state: 'Complete' | 'Incomplete' | 'Missing' | 'Outside Range'
}

/**
 * Completeness, exclusions and rate provenance travel with every total (§8.2).
 *
 * Generic over the completeness shape so a caller that knows the fuller form
 * gets them typed, rather than everyone widening to `unknown` and asserting.
 */
export interface AggregateEnvelope<T, C extends CompletenessSummary = CompletenessSummary>
  extends Envelope<T> {
  readonly completeness: C
  readonly exclusions: readonly { readonly account: string; readonly reason: string }[]
  readonly rate_provenance: readonly {
    readonly pair: string
    readonly as_at: string
    readonly provenance: 'exact' | 'carried' | 'triangulated'
    readonly stale?: boolean
  }[]
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

function csrfToken(): string {
  const value = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/)?.[1]
  return value ? decodeURIComponent(value) : ''
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()

  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined) headers.set('Content-Type', 'application/json')
  if (UNSAFE.has(method)) headers.set('X-CSRFToken', csrfToken())

  const response = await fetch(`/api${path}`, {
    ...init,
    method,
    headers,
    // The session cookie is HttpOnly and same-origin. Nothing is read from
    // local storage, because anything in local storage is readable by any
    // script on the page (ADR-16).
    credentials: 'same-origin',
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const body: unknown = text ? JSON.parse(text) : null

  if (!response.ok) {
    const detail = (body as { error?: ApiErrorDetail } | null)?.error
    throw new ApiError(response.status, detail ?? UNPARSEABLE)
  }

  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  // Create-or-replace. Used by Month Close, where each call addresses a
  // distinct (account, month) key and several may be in flight at once.
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Shared response types
// ---------------------------------------------------------------------------

export interface SessionState {
  readonly authenticated: boolean
  readonly username: string | null
}

/** Re-exported so screens import one module for the types they render. */
export type { Money }
