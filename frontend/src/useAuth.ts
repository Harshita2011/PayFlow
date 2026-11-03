import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getProfile, loginUser } from './api'
import type { User } from './api'

interface Session {
  token: string
  user: User
  expiresAt: number
}

export function useAuth() {
  // Memory only: tokens are never written to localStorage, cookies, or the URL.
  const [session, setSession] = useState<Session | null>(null)
  const [sessionMessage, setSessionMessage] = useState('')
  const generation = useRef(0)

  const logout = useCallback((message = '') => {
    generation.current += 1
    setSession(null)
    setSessionMessage(message)
  }, [])

  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(
      () => logout('Your session has expired. Please sign in again.'),
      Math.max(0, session.expiresAt - Date.now()),
    )
    return () => window.clearTimeout(timer)
  }, [session, logout])

  async function login(email: string, password: string) {
    const current = ++generation.current
    const startedAt = Date.now()
    const result = await loginUser(email, password)
    const user = await getProfile(result.access_token)
    if (current !== generation.current) return
    setSession({ token: result.access_token, user, expiresAt: startedAt + result.expires_in * 1000 })
    setSessionMessage('')
  }

  async function refreshProfile() {
    if (!session) return false
    const current = generation.current
    try {
      const user = await getProfile(session.token)
      if (current !== generation.current) return false
      setSession({ ...session, user })
      return true
    } catch (error) {
      if (current !== generation.current) return false
      if (error instanceof ApiError && error.status === 401) {
        logout('Your session has expired. Please sign in again.')
      }
      throw error
    }
  }

  return { session, sessionMessage, login, logout, refreshProfile }
}
