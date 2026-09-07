'use client'

import { useQuery } from '@tanstack/react-query'
import { request } from './api'

export type SampleLogin = {
  role: string
  name: string
  email: string
  password: string
  facility: string | null
}

export type DeploymentMeta = {
  organization: string | null
  demo_mode: boolean
  sample_logins: SampleLogin[]
}

/**
 * Read before sign-in, so it must not require a session. The sample logins it
 * carries are empty unless the server is in demo mode — the frontend never
 * decides that.
 */
export function useDeploymentMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: () => request<DeploymentMeta>('/meta/'),
    staleTime: 5 * 60_000,
    retry: false,
  })
}
