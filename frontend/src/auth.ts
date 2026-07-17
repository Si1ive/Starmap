import { createContext } from 'react'

const AUTH_API_BASE = '/api/v1/auth'

export type AuthenticationStatus =
  | 'loading'
  | 'authenticated'
  | 'anonymous'
  | 'unavailable'

export interface AuthenticatedUser {
  id: string
  email: string
  email_verified: boolean
  display_name: string
  locale: string
  timezone: string
}

export interface AuthenticatedSession {
  id: string
  auth_method: string
  device_label: string | null
  created_at: string
  idle_expires_at: string
  absolute_expires_at: string
}

export interface AuthenticatedSessionData {
  authenticated: true
  csrf_token: string
  user: AuthenticatedUser
  session: AuthenticatedSession
}

export interface ManagedSession {
  id: string
  auth_method: string
  device_label: string
  created_at: string
  last_seen_at: string
  idle_expires_at: string
  absolute_expires_at: string
  is_current: boolean
  location_label: string | null
}

export interface ActiveSessionsData {
  sessions: ManagedSession[]
}

export interface LoginCredentials {
  email: string
  password: string
  remember_me: boolean
}

export interface RegistrationDetails {
  display_name: string
  email: string
  password: string
  password_confirmation: string
  accept_terms: true
  accept_privacy: true
}

export interface RegistrationAccepted {
  verification_required: true
  resend_after_seconds: number
}

export interface GitHubOAuthStartDetails {
  source: 'login' | 'register'
  return_path: string
  remember_me: boolean
  accept_terms: boolean
  accept_privacy: boolean
}

export interface GitHubOAuthAuthorization {
  authorization_url: string
  expires_at: string
}

export interface GitHubLinkStatus {
  linked: boolean
  username: string | null
  email: string | null
  linked_at: string | null
}

export interface VerifiedEmailUser {
  id: string
  email: string
  email_verified: true
  display_name: string
}

export interface UnauthenticatedEmailVerificationData {
  authenticated: false
  user: VerifiedEmailUser
}

export type EmailVerificationData =
  | AuthenticatedSessionData
  | UnauthenticatedEmailVerificationData

export type EmailVerificationCredential =
  | { token: string; code?: never }
  | { code: string; token?: never }

export interface ForgotPasswordAccepted {
  accepted: true
}

export interface PasswordResetCompleted {
  password_reset: true
  authenticated: false
}

interface ApiEnvelope<T> {
  code: number | string
  message: string
  data?: T
  request_id?: string
}

export class AuthApiError extends Error {
  readonly code: string
  readonly status: number
  readonly requestId?: string
  readonly retryAfterSeconds?: number

  constructor({
    code,
    message,
    status,
    requestId,
    retryAfterSeconds,
  }: {
    code: string
    message: string
    status: number
    requestId?: string
    retryAfterSeconds?: number
  }) {
    super(message)
    this.name = 'AuthApiError'
    this.code = code
    this.status = status
    this.requestId = requestId
    this.retryAfterSeconds = retryAfterSeconds
  }
}

export interface AuthContextValue {
  status: AuthenticationStatus
  user: AuthenticatedUser | null
  session: AuthenticatedSession | null
  login: (credentials: LoginCredentials) => Promise<AuthenticatedSessionData>
  verifyEmail: (
    credential: EmailVerificationCredential,
  ) => Promise<EmailVerificationData>
  startGitHubLink: () => Promise<GitHubOAuthAuthorization>
  revokeSession: (sessionId: string) => Promise<void>
  logout: () => Promise<void>
  restore: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
)

export function postLoginPath(state: unknown): string {
  const from = (
    state as {
      from?: {
        pathname?: unknown
        search?: unknown
        hash?: unknown
      }
    } | null
  )?.from
  if (
    !from ||
    typeof from.pathname !== 'string' ||
    !from.pathname.startsWith('/') ||
    from.pathname.startsWith('//') ||
    from.pathname === '/login'
  ) {
    return '/today'
  }
  const search = typeof from.search === 'string' ? from.search : ''
  const hash = typeof from.hash === 'string' ? from.hash : ''
  return `${from.pathname}${search}${hash}`
}

export async function fetchCurrentSession(
  signal?: AbortSignal,
): Promise<AuthenticatedSessionData | null> {
  try {
    return await authRequest<AuthenticatedSessionData>('/me', {
      method: 'GET',
      signal,
    })
  } catch (error) {
    if (error instanceof AuthApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

export function loginWithPassword(
  credentials: LoginCredentials,
): Promise<AuthenticatedSessionData> {
  return authRequest<AuthenticatedSessionData>('/login', {
    method: 'POST',
    body: JSON.stringify(credentials),
  })
}

export function registerWithPassword(
  details: RegistrationDetails,
): Promise<RegistrationAccepted> {
  return authRequest<RegistrationAccepted>('/register', {
    method: 'POST',
    body: JSON.stringify(details),
  })
}

export function startGitHubOAuth(
  details: GitHubOAuthStartDetails,
): Promise<GitHubOAuthAuthorization> {
  return authRequest<GitHubOAuthAuthorization>('/github/start', {
    method: 'POST',
    body: JSON.stringify(details),
  })
}

export function fetchGitHubLinkStatus(
  signal?: AbortSignal,
): Promise<GitHubLinkStatus> {
  return authRequest<GitHubLinkStatus>('/github/link', {
    method: 'GET',
    signal,
  })
}

export function startGitHubAccountLink(
  csrfToken: string,
): Promise<GitHubOAuthAuthorization> {
  return authRequest<GitHubOAuthAuthorization>('/github/link/start', {
    method: 'POST',
    headers: {
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify({ return_path: '/account' }),
  })
}

export function confirmEmailVerification(
  credential: EmailVerificationCredential,
): Promise<EmailVerificationData> {
  return authRequest<EmailVerificationData>('/email-verification/confirm', {
    method: 'POST',
    body: JSON.stringify(credential),
  })
}

export function resendEmailVerification(): Promise<RegistrationAccepted> {
  return authRequest<RegistrationAccepted>('/email-verification/resend', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export function requestPasswordReset(
  email: string,
): Promise<ForgotPasswordAccepted> {
  return authRequest<ForgotPasswordAccepted>('/password/forgot', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function resetPassword(details: {
  token: string
  password: string
  password_confirmation: string
}): Promise<PasswordResetCompleted> {
  return authRequest<PasswordResetCompleted>('/password/reset', {
    method: 'POST',
    body: JSON.stringify(details),
  })
}

export async function logoutCurrentSession(csrfToken: string): Promise<void> {
  await authRequest<{ authenticated: false }>('/logout', {
    method: 'POST',
    headers: {
      'X-CSRF-Token': csrfToken,
    },
    body: JSON.stringify({}),
  })
}

export function fetchActiveSessions(
  signal?: AbortSignal,
): Promise<ActiveSessionsData> {
  return authRequest<ActiveSessionsData>('/sessions', {
    method: 'GET',
    signal,
  })
}

export async function revokeActiveSession(
  sessionId: string,
  csrfToken: string,
): Promise<void> {
  await authRequest<{ revoked: true; session_id: string }>(
    `/sessions/${encodeURIComponent(sessionId)}/revoke`,
    {
      method: 'POST',
      headers: {
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify({}),
    },
  )
}

async function authRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(`${AUTH_API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new AuthApiError({
      code: 'AUTH_NETWORK_ERROR',
      message: '暂时无法连接认证服务，请检查网络后重试',
      status: 0,
    })
  }

  const payload = await readEnvelope<T>(response)
  if (!response.ok) {
    const retryAfter = Number(response.headers.get('Retry-After'))
    throw new AuthApiError({
      code:
        typeof payload.code === 'string' ? payload.code : 'AUTH_REQUEST_FAILED',
      message: payload.message || '认证请求失败，请稍后重试',
      status: response.status,
      requestId: payload.request_id,
      retryAfterSeconds:
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    })
  }
  if (payload.data === undefined) {
    throw new AuthApiError({
      code: 'AUTH_RESPONSE_INVALID',
      message: '认证服务返回了无效响应，请稍后重试',
      status: response.status,
      requestId: payload.request_id,
    })
  }
  return payload.data
}

async function readEnvelope<T>(response: Response): Promise<ApiEnvelope<T>> {
  try {
    return (await response.json()) as ApiEnvelope<T>
  } catch {
    throw new AuthApiError({
      code: 'AUTH_RESPONSE_INVALID',
      message: '认证服务返回了无效响应，请稍后重试',
      status: response.status,
    })
  }
}
