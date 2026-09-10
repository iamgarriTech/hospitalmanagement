'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type ReferralPrint = {
  id: number
  printed_by: number
  printed_by_email: string
  printed_at: string
  is_reprint: boolean
}

export type Referral = {
  id: number
  reference: string
  kind: 'internal' | 'external'
  kind_display: string
  patient: number
  patient_name: string
  hospital_number: string
  facility: number
  encounter: number | null
  visit: number | null
  admission: number | null
  to_department: number | null
  to_department_name: string | null
  to_clinician: number | null
  to_clinician_name: string | null
  to_organisation: string
  to_external_clinician: string
  to_address: string
  destination: string
  reason: string
  clinical_question: string
  what_was_sent: string
  urgency: 'routine' | 'urgent' | 'two_week'
  urgency_display: string
  status: 'draft' | 'sent' | 'accepted' | 'seen' | 'declined' | 'cancelled'
  status_display: string
  referred_by: number
  referred_by_email: string
  referred_by_name: string
  referred_at: string
  sent_at: string | null
  outcome: string
  outcome_recorded_by: number | null
  outcome_recorded_by_email: string | null
  outcome_recorded_at: string | null
  print_count: number
  prints: ReferralPrint[]
  is_open: boolean
}

export type ReferralLetter = {
  letter: {
    reference: string
    written_on: string
    sent_on: string | null
    urgency: string
    from: { clinician: string; facility: string; department: string }
    to: { kind: string; name: string; address: string }
    patient: {
      name: string
      hospital_number: string
      date_of_birth: string | null
      age_years: number | null
      sex: string
      phone: string
    }
    reason: string
    clinical_question: string
    what_was_sent: string
    outcome: string
  }
  is_reprint: boolean
  print_count: number
}

export function useReferrals(params = '') {
  return useQuery({
    queryKey: ['referrals', params],
    queryFn: async () => (await request<Page<Referral>>(`/referrals/${params}`)).results,
  })
}

function invalidate(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ['referrals'] })
}

export function useCreateReferral() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      kind: 'internal' | 'external'
      visit?: number | null
      admission?: number | null
      encounter?: number | null
      to_department?: number | null
      to_clinician?: number | null
      to_organisation?: string
      to_external_clinician?: string
      to_address?: string
      reason: string
      clinical_question: string
      what_was_sent?: string
      urgency: string
    }) => request<Referral>('/referrals/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}

function action(name: string) {
  return function useReferralAction() {
    const client = useQueryClient()
    return useMutation({
      mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
        request<Referral>(`/referrals/${id}/${name}/`, {
          method: 'POST',
          body: Object.keys(body).length ? body : undefined,
        }),
      onSettled: () => invalidate(client),
    })
  }
}

export const useSendReferral = action('send')
export const useAcceptReferral = action('accept')
export const useReferralOutcome = action('outcome')
export const useCancelReferral = action('cancel')

/**
 * The letter.
 *
 * Fetched on demand rather than cached, because every read is a print and
 * every print is logged — a cached copy would mean the second person to open
 * it leaves no trace.
 */
export function useReferralLetter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => request<ReferralLetter>(`/referrals/${id}/letter/`),
    onSettled: () => invalidate(client),
  })
}
