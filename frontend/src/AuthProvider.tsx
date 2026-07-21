import { ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import {
  AuthApiError,
  AuthContext,
  AuthContextValue,
  AuthenticatedSessionData,
  AuthenticationStatus,
  confirmEmailAccountLink,
  confirmEmailVerification,
  EmailLinkCredential,
  EmailLinkDetails,
  EmailVerificationCredential,
  fetchCurrentSession,
  LoginCredentials,
  loginWithPassword,
  logoutCurrentSession,
  revokeActiveSession,
  startEmailAccountLink,
  startGitHubAccountLink,
} from './auth'

interface AuthState {
  status: AuthenticationStatus
  data: AuthenticatedSessionData | null
}

const initialState: AuthState = {
  status: 'loading',
  data: null,
}

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initialState)

  const applySession = useCallback((data: AuthenticatedSessionData | null) => {
    setState({
      status: data ? 'authenticated' : 'anonymous',
      data,
    })
  }, [])

  const restore = useCallback(async () => {
    setState((current) => ({
      status: 'loading',
      data: current.data,
    }))
    try {
      applySession(await fetchCurrentSession())
    } catch {
      setState({
        status: 'unavailable',
        data: null,
      })
    }
  }, [applySession])

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    void fetchCurrentSession(controller.signal)
      .then((data) => {
        if (active) applySession(data)
      })
      .catch((error: unknown) => {
        if (
          active &&
          !(error instanceof DOMException && error.name === 'AbortError')
        ) {
          setState({
            status: 'unavailable',
            data: null,
          })
        }
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [applySession])

  const login = useCallback(
    async (credentials: LoginCredentials) => {
      const data = await loginWithPassword(credentials)
      applySession(data)
      return data
    },
    [applySession],
  )

  const verifyEmail = useCallback(
    async (credential: EmailVerificationCredential) => {
      const data = await confirmEmailVerification(credential)
      if (data.authenticated) {
        applySession(data)
      }
      return data
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    const csrfToken = state.data?.csrf_token
    if (!csrfToken) {
      applySession(null)
      return
    }
    try {
      await logoutCurrentSession(csrfToken)
      applySession(null)
    } catch (error) {
      if (error instanceof AuthApiError && error.status === 401) {
        applySession(null)
        return
      }
      throw error
    }
  }, [applySession, state.data?.csrf_token])

  const revokeSession = useCallback(
    async (sessionId: string) => {
      const csrfToken = state.data?.csrf_token
      if (!csrfToken) {
        applySession(null)
        throw new AuthApiError({
          code: 'AUTHENTICATION_REQUIRED',
          message: '请先登录',
          status: 401,
        })
      }
      try {
        await revokeActiveSession(sessionId, csrfToken)
      } catch (error) {
        if (error instanceof AuthApiError && error.status === 401) {
          applySession(null)
        }
        throw error
      }
    },
    [applySession, state.data?.csrf_token],
  )

  const startGitHubLink = useCallback(async () => {
    const csrfToken = state.data?.csrf_token
    if (!csrfToken) {
      applySession(null)
      throw new AuthApiError({
        code: 'AUTHENTICATION_REQUIRED',
        message: '请先登录',
        status: 401,
      })
    }
    try {
      return await startGitHubAccountLink(csrfToken)
    } catch (error) {
      if (error instanceof AuthApiError && error.status === 401) {
        applySession(null)
      }
      throw error
    }
  }, [applySession, state.data?.csrf_token])

  const startEmailLink = useCallback(
    async (details: EmailLinkDetails) => {
      const csrfToken = state.data?.csrf_token
      if (!csrfToken) {
        applySession(null)
        throw new AuthApiError({
          code: 'AUTHENTICATION_REQUIRED',
          message: '请先登录',
          status: 401,
        })
      }
      try {
        return await startEmailAccountLink(details, csrfToken)
      } catch (error) {
        if (error instanceof AuthApiError && error.status === 401) {
          applySession(null)
        }
        throw error
      }
    },
    [applySession, state.data?.csrf_token],
  )

  const confirmEmailLink = useCallback(
    async (credential: EmailLinkCredential) => {
      const csrfToken = state.data?.csrf_token
      if (!csrfToken) {
        applySession(null)
        throw new AuthApiError({
          code: 'AUTHENTICATION_REQUIRED',
          message: '请先登录',
          status: 401,
        })
      }
      try {
        const result = await confirmEmailAccountLink(credential, csrfToken)
        applySession(await fetchCurrentSession())
        return result
      } catch (error) {
        if (error instanceof AuthApiError && error.status === 401) {
          applySession(null)
        }
        throw error
      }
    },
    [applySession, state.data?.csrf_token],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      user: state.data?.user ?? null,
      session: state.data?.session ?? null,
      login,
      verifyEmail,
      startGitHubLink,
      startEmailLink,
      confirmEmailLink,
      revokeSession,
      logout,
      restore,
    }),
    [
      login,
      logout,
      restore,
      revokeSession,
      confirmEmailLink,
      startGitHubLink,
      startEmailLink,
      state,
      verifyEmail,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
