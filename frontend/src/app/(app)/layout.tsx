'use client'

import { useRouter } from 'next/navigation'
import { type ReactNode, useEffect } from 'react'
import { AppShell } from '@/components/AppShell'
import { BrandLogo } from '@/components/BrandLogo'
import { useAuth } from '@/lib/auth'

/**
 * The authenticated frame. This is a convenience only — every API call is
 * authorised server-side, so a user who defeats this gate sees empty screens
 * and 403s, not data.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && !user) router.replace('/login')
  }, [isLoading, user, router])

  if (isLoading) {
    return (
      <div
        role="status"
        className="flex min-h-screen flex-col items-center justify-center gap-4 text-[13px] text-ink-muted"
      >
        <BrandLogo variant="icon" />
        Loading VitaCore…
      </div>
    )
  }
  if (!user) return null

  return <AppShell>{children}</AppShell>
}
