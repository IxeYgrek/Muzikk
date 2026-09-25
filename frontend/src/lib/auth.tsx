import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError, api, clearToken, getToken, setToken } from './api'
import type { Session, User } from './types'

type AuthContextValue = {
  user: User | null
  autoApprove: boolean
  ready: boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [autoApprove, setAutoApprove] = useState(false)
  const [ready, setReady] = useState(false)

  const apply = useCallback((session: Session) => {
    setToken(session.token)
    setUser(session.user)
    setAutoApprove(session.auto_approve)
  }, [])

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setReady(true)
      return
    }
    try {
      apply(await api<Session>('/auth/me'))
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearToken()
      }
      setUser(null)
    } finally {
      setReady(true)
    }
  }, [apply])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const signIn = useCallback(
    async (username: string, password: string) => {
      const session = await api<Session>('/auth/login', {
        method: 'POST',
        body: { username, password },
      })
      apply(session)
      setReady(true)
    },
    [apply],
  )

  const signOut = useCallback(() => {
    void api('/auth/logout', { method: 'POST' }).catch(() => undefined)
    clearToken()
    setUser(null)
    setAutoApprove(false)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, autoApprove, ready, signIn, signOut, refresh }),
    [user, autoApprove, ready, signIn, signOut, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/** Whether this account may replace an owned lossy album with a lossless copy. */
export function canRequestUpgrade(user: User | null | undefined): boolean {
  return Boolean(user?.is_admin || user?.can_upgrade)
}

export function canRequestTrack(user: User | null | undefined): boolean {
  return Boolean(user?.is_admin || user?.can_request_track)
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}
