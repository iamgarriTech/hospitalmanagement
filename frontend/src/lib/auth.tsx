'use client'

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { ApiError, ensureCsrfCookie, request } from './api'

export type Facility = { id: number; code: string; name: string; timezone: string }

export type AuthUser = {
  id: number
  email: string
  full_name: string
  staff_id: string | null
  is_active: boolean
  is_superuser: boolean
  roles: { role: string; facility: string | null }[]
  /**
   * Flattened permissions, used only to decide what to render. The server
   * re-checks every request with facility scope, so a stale or generous list
   * here can never grant anything.
   */
  permissions: string[]
  facilities: Facility[]
}

type AuthContextValue = {
  user: AuthUser | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  can: (permission: string) => boolean
  canAny: (...permissions: string[]) => boolean
  facility: Facility | null
  setFacility: (facility: Facility) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)
const FACILITY_KEY = 'hms.facility'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [facilityCode, setFacilityCode] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await ensureCsrfCookie()
        const me = await request<AuthUser>('/auth/me/')
        if (!cancelled) setUser(me)
      } catch {
        // 403 here just means "not signed in"; the login screen handles it.
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    try {
      setFacilityCode(localStorage.getItem(FACILITY_KEY))
    } catch {
      // Private browsing can throw on access; a missing preference is fine.
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    await ensureCsrfCookie()
    const me = await request<AuthUser>('/auth/login/', { method: 'POST', body: { email, password } })
    setUser(me)
  }, [])

  const logout = useCallback(async () => {
    try {
      await request('/auth/logout/', { method: 'POST' })
    } catch (error) {
      // A failed logout must still clear the client, or the user is stuck
      // looking at a session they believe they have ended.
      if (!(error instanceof ApiError)) throw error
    }
    setUser(null)
  }, [])

  const can = useCallback(
    (permission: string) =>
      Boolean(user && (user.permissions.includes('*') || user.permissions.includes(permission))),
    [user],
  )

  const canAny = useCallback(
    (...permissions: string[]) => permissions.some((permission) => can(permission)),
    [can],
  )

  const facility = useMemo(() => {
    if (!user?.facilities.length) return null
    return user.facilities.find((entry) => entry.code === facilityCode) ?? user.facilities[0]
  }, [user, facilityCode])

  const setFacility = useCallback((next: Facility) => {
    setFacilityCode(next.code)
    try {
      localStorage.setItem(FACILITY_KEY, next.code)
    } catch {
      // Remembering the choice is a convenience, not a requirement.
    }
  }, [])

  const value = useMemo(
    () => ({ user, isLoading, login, logout, can, canAny, facility, setFacility }),
    [user, isLoading, login, logout, can, canAny, facility, setFacility],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
