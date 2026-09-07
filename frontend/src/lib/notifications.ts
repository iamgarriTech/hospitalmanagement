'use client'

import { useQuery } from '@tanstack/react-query'
import { type Page, request } from './api'

export type Notification = {
  id: number
  kind: string
  urgency: 'urgent' | 'normal'
  subject: string
  body: string
  patient: number | null
  patient_name: string | null
  resource_type: string
  resource_id: string
  created_at: string
  read_at: string | null
}

export function useNotifications() {
  return useQuery({
    queryKey: ['notifications'],
    queryFn: async () => (await request<Page<Notification>>('/notifications/')).results,
    // A critical result must not sit unseen because nobody changed tabs.
    refetchInterval: 60_000,
  })
}
