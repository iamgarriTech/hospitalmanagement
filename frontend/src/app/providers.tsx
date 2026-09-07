'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { AuthProvider } from '@/lib/auth'

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Clinical data goes stale fast and staff act on what is on screen,
            // so refetch on focus and keep the window short.
            staleTime: 10_000,
            refetchOnWindowFocus: true,
            retry: (failureCount, error) => {
              // Never retry a refusal or a validation error — only transport
              // failures, and only briefly.
              const status = (error as { status?: number }).status
              if (status && status < 500) return false
              return failureCount < 2
            },
          },
        },
      }),
  )
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  )
}
