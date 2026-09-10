'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'

/**
 * The patient portal's own client.
 *
 * Deliberately not built on `useAuth` or anything else in `lib/auth.ts`. The
 * portal has its own cookie, its own session table and its own account model
 * on the server, and sharing a client here would be the first step towards
 * sharing something that matters.
 */

export type PortalMe = {
  patient_name: string
  hospital_number: string
  date_of_birth: string | null
  must_change_password: boolean
  session_expires_at: string
}

export type PortalVisit = {
  id: number
  arrived_at: string
  facility: string
  clinic: string | null
  reason: string
  status: string
  closed_at: string | null
}

export type PortalResult = {
  id: number
  test: string
  parameter: string
  value: string
  unit: string
  flag: string
  reference_range: string
  verified_at: string
  laboratory_comment: string
}

export type PortalMedication = {
  id: number
  medication: string
  dose: string
  route: string
  times_a_day: number
  days: number
  instructions: string
  prescribed_at: string
  status: string
}

export type PortalBill = {
  id: number
  invoice_number: string
  facility: string
  created_at: string
  status: string
  total: string
  amount_paid: string
  balance: string
  items: { description: string; quantity: number; unit_price: string }[]
}

export function usePortalMe() {
  return useQuery({
    queryKey: ['portal-me'],
    queryFn: () => request<PortalMe>('/portal/auth/me/'),
    retry: false,
  })
}

export function usePortalLogin() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { login_identifier: string; password: string }) =>
      request<{
        patient_name: string
        hospital_number: string
        must_change_password: boolean
      }>('/portal/auth/login/', { method: 'POST', body: payload }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['portal-me'] }),
  })
}

export function usePortalLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => request<void>('/portal/auth/logout/', { method: 'POST' }),
    onSettled: () => client.clear(),
  })
}

export function usePortalPasswordChange() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      request<void>('/portal/auth/me/', { method: 'POST', body: payload }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['portal-me'] }),
  })
}

function record<T>(name: string) {
  return function usePortalRecord(enabled = true) {
    return useQuery({
      queryKey: ['portal', name],
      queryFn: () => request<T[]>(`/portal/record/${name}/`),
      enabled,
      retry: false,
    })
  }
}

export const usePortalVisits = record<PortalVisit>('visits')
export const usePortalResults = record<PortalResult>('results')
export const usePortalMedication = record<PortalMedication>('medication')
export const usePortalBills = record<PortalBill>('bills')
