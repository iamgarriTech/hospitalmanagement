'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type ProcedureConsumable = {
  id: number
  item: number
  item_name: string
  unit_of_issue: string
  quantity: number
}

export type Procedure = {
  id: number
  category: number
  category_name: string
  name: string
  code: string
  typical_duration_minutes: number
  requires_theatre: boolean
  requires_consent: boolean
  requires_anaesthesia: boolean
  billing_service: number | null
  service_code: string | null
  preparation: string
  is_active: boolean
  consumables: ProcedureConsumable[]
}

export type Theatre = {
  id: number
  facility: number
  facility_name: string
  name: string
  code: string
  store: number | null
  store_name: string | null
  is_active: boolean
  out_of_service_note: string
}

export type Consent = {
  id: number
  request: number
  given_by: 'patient' | 'next_of_kin' | 'two_doctors'
  given_by_display: string
  given_by_name: string
  relationship: string
  risks_discussed: string
  interpreter_used: boolean
  interpreter_name: string
  taken_by: number
  taken_by_email: string
  taken_at: string
  withdrawn_at: string | null
  withdrawal_reason: string
  is_valid: boolean
}

export type TheatreBooking = {
  id: number
  theatre: number
  theatre_name: string
  request: number
  reference: string
  procedure_name: string
  patient_name: string
  hospital_number: string
  starts_at: string
  ends_at: string
  status: 'scheduled' | 'in_progress' | 'completed' | 'cancelled'
  status_display: string
  lead_surgeon: number
  lead_surgeon_name: string
  anaesthetist: number | null
  anaesthetist_name: string | null
  booked_by: number
  booked_at: string
  cancelled_at: string | null
  cancellation_reason: string
}

export type OperationNoteVersion = {
  id: number
  version_number: number
  is_current: boolean
  findings: string
  procedure_performed: string
  closure: string
  estimated_blood_loss_ml: number | null
  specimens_taken: string
  complications: string
  post_operative_instructions: string
  author: number
  author_email: string
  author_name: string
  created_at: string
  amendment_reason: string
}

export type OperationNote = {
  id: number
  performed: number
  created_at: string
  current: OperationNoteVersion | null
  versions: OperationNoteVersion[]
}

export type PerformedProcedure = {
  id: number
  request: number
  reference: string
  procedure_name: string
  patient_name: string
  booking: number | null
  started_at: string
  finished_at: string
  duration_minutes: number
  outcome: 'completed' | 'abandoned'
  outcome_display: string
  lead_clinician: number
  lead_clinician_name: string
  recorded_by: number
  recorded_at: string
  is_billed: boolean
  team: { id: number; member: number; member_name: string; role: string; role_display: string }[]
  consumables_used: {
    id: number; item: number; item_name: string; quantity: number
    movement: number; store_name: string
  }[]
  medications: {
    id: number; medication: number; medication_name: string; dose: string
    route: string; given_at: string; given_by: number; given_by_name: string
  }[]
  note: OperationNote | null
}

export type ProcedureRequest = {
  id: number
  reference: string
  procedure: number
  procedure_name: string
  requires_consent: boolean
  requires_theatre: boolean
  patient: number
  patient_name: string
  hospital_number: string
  facility: number
  visit: number | null
  admission: number | null
  indication: string
  urgency: 'routine' | 'urgent' | 'emergency'
  urgency_display: string
  status: 'requested' | 'scheduled' | 'performed' | 'cancelled'
  status_display: string
  requested_by: number
  requested_by_email: string
  requested_at: string
  cancelled_at: string | null
  cancellation_reason: string
  consent: Consent | null
  bookings: TheatreBooking[]
  performed: PerformedProcedure | null
  consent_blocking: string | null
}

export function useProcedureCatalogue(enabled = true) {
  return useQuery({
    queryKey: ['procedure-catalogue'],
    queryFn: async () =>
      (await request<Page<Procedure>>('/procedures/?active=true')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useTheatres(enabled = true) {
  return useQuery({
    queryKey: ['theatres'],
    queryFn: async () => (await request<Page<Theatre>>('/theatres/')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useProcedureRequests(params = '') {
  return useQuery({
    queryKey: ['procedure-requests', params],
    queryFn: async () =>
      (await request<Page<ProcedureRequest>>(`/procedure-requests/${params}`)).results,
  })
}

export function useTheatreList(date: string, theatre: number | null = null) {
  return useQuery({
    queryKey: ['theatre-list', date, theatre],
    queryFn: () =>
      request<TheatreBooking[]>(
        `/theatre-list/?date=${date}${theatre ? `&theatre=${theatre}` : ''}`,
      ),
  })
}

export function usePerformedProcedures(patient: number | null = null) {
  return useQuery({
    queryKey: ['performed-procedures', patient],
    queryFn: async () =>
      (await request<Page<PerformedProcedure>>(
        patient ? `/performed-procedures/?patient=${patient}` : '/performed-procedures/',
      )).results,
  })
}

function invalidate(client: ReturnType<typeof useQueryClient>) {
  for (const key of [
    'procedure-requests', 'theatre-list', 'performed-procedures', 'operation-notes',
    'stock-records', 'stock-alerts', 'invoices', 'invoice', 'outstanding-invoices',
  ]) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useRequestProcedure() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      procedure: number
      visit?: number | null
      admission?: number | null
      indication: string
      urgency: string
    }) =>
      request<ProcedureRequest>('/procedure-requests/', {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useRecordConsent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, ...payload
    }: {
      id: number
      risks_discussed: string
      given_by: Consent['given_by']
      given_by_name: string
      relationship: string
      interpreter_used: boolean
      interpreter_name: string
    }) =>
      request<Consent>(`/procedure-requests/${id}/consent/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useWithdrawConsent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<Consent>(`/procedure-requests/${id}/withdraw-consent/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useBookTheatre() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, ...payload
    }: {
      id: number
      theatre: number
      starts_at: string
      ends_at: string
      lead_surgeon: number
      anaesthetist: number | null
    }) =>
      request<TheatreBooking>(`/procedure-requests/${id}/book/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useCancelBooking() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<TheatreBooking>(`/theatre-bookings/${id}/cancel/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useCancelProcedure() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<ProcedureRequest>(`/procedure-requests/${id}/cancel/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidate(client),
  })
}

export type PerformPayload = {
  id: number
  started_at: string
  finished_at: string
  lead_clinician: number
  outcome: 'completed' | 'abandoned'
  booking: number | null
  store: number | null
  findings: string
  procedure_performed: string
  closure: string
  blood_loss_ml: number | null
  specimens: string
  complications: string
  post_operative_instructions: string
  team: { member: number; role: string }[]
  consumables: { item: number; quantity: number }[]
  medications: { medication: number; dose: string; route: string }[]
}

export function usePerformProcedure() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: PerformPayload) =>
      request<PerformedProcedure>(`/procedure-requests/${id}/perform/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useAmendNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, ...payload
    }: {
      id: number
      reason: string
      findings?: string
      procedure_performed?: string
      complications?: string
      post_operative_instructions?: string
    }) =>
      request<OperationNote>(`/operation-notes/${id}/amend/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}
