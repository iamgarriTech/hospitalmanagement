'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

export type OutboundMessage = {
  id: number
  channel: 'sms' | 'email'
  channel_display: string
  to_address: string
  subject: string
  source_type: string
  source_id: string
  facility: number | null
  patient_reference: string
  status: 'pending' | 'sending' | 'sent' | 'failed' | 'cancelled'
  status_display: string
  attempts: number
  max_attempts: number
  attempts_left: number
  next_attempt_at: string
  last_error: string
  provider_reference: string
  created_at: string
  sent_at: string | null
  failed_at: string | null
}

export type OutboxSummary = {
  pending: number
  sent: number
  failed: number
  cancelled: number
  oldest_pending: string | null
}

export function useOutbox(params = '') {
  return useQuery({
    queryKey: ['outbox', params],
    queryFn: async () =>
      (await request<Page<OutboundMessage>>(`/outbox/${params}`)).results,
    refetchInterval: 60_000,
  })
}

export function useOutboxSummary() {
  return useQuery({
    queryKey: ['outbox-summary'],
    queryFn: () => request<OutboxSummary>('/outbox/summary/'),
    refetchInterval: 60_000,
  })
}

export function useRetryMessage() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<OutboundMessage>(`/outbox/${id}/retry/`, { method: 'POST' }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['outbox'] })
      client.invalidateQueries({ queryKey: ['outbox-summary'] })
    },
  })
}
