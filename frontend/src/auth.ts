const AUTH_SESSION_KEY = 'starmap.authenticated'

export function hasAuthenticatedSession() {
  return (
    window.localStorage.getItem(AUTH_SESSION_KEY) === 'true' ||
    window.sessionStorage.getItem(AUTH_SESSION_KEY) === 'true'
  )
}

export function startAuthenticatedSession(remember: boolean) {
  const preferredStorage = remember ? window.localStorage : window.sessionStorage
  const staleStorage = remember ? window.sessionStorage : window.localStorage

  staleStorage.removeItem(AUTH_SESSION_KEY)
  preferredStorage.setItem(AUTH_SESSION_KEY, 'true')
}
