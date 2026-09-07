'use client'

import { useQuery } from '@tanstack/react-query'
import { type Page, query, request } from './api'

/* Shared shapes. Kept hand-written for now: the OpenAPI schema is stable but
   the generated client is a separate step, and hand-writing the handful of
   types the screens actually read is honest about what is being consumed. */

export type QueueRow = {
  id: number
  visit_number: string
  patient: {
    id: number
    hospital_number: string
    full_name: string
    sex: string
    age_years: number | null
    phone_primary: string
    status: string
  }
  status: string
  visit_type: string
  clinic_name: string | null
  arrived_at: string
  waiting_minutes: number
  reason: string
  allergies: string[]
}

export type WorklistRow = {
  item_id: number
  order_number: string
  priority: 'routine' | 'urgent'
  patient_name: string
  hospital_number: string
  test: string
  specimen_type: string
  specimen_requirements: string
  status: string
  ordered_at: string
}

export type CriticalRow = {
  result_id: number
  patient_name: string
  hospital_number: string
  test: string
  parameter: string
  value: string
  flag_label: string
  reference: string
  entered_at: string
  ordered_by: string
}

export type PharmacyQueueRow = {
  id: number
  prescription_number: string
  patient_name: string
  hospital_number: string
  prescribed_at: string
  prescribed_by: string
  status: string
  allergies: string[]
  items: {
    item_id: number
    medication: string
    outstanding: number
    instructions: string
    overridden_warnings: string[]
  }[]
}

export type OutstandingInvoice = {
  id: number
  invoice_number: string
  patient_name: string
  hospital_number: string
  total: string
  amount_paid: string
  balance: string
  status: string
}

export type PatientSummary = {
  id: number
  hospital_number: string
  full_name: string
  sex: string
  date_of_birth: string | null
  date_of_birth_is_estimated: boolean
  age_years: number | null
  phone_primary: string
  status: string
}

const ACTIVE = 'waiting,called,in_consultation,sent_for_investigation,sent_to_pharmacy,sent_for_billing'

export function useQueue(params: { status?: string; enabled?: boolean } = {}) {
  const { status, enabled = true } = params
  return useQuery({
    queryKey: ['queue', status ?? ACTIVE],
    queryFn: () => request<QueueRow[]>(`/visits/queue/${query({ status })}`),
    enabled,
    // A wall-board view. Staff leave it open and act on what it says.
    refetchInterval: 20_000,
  })
}

export function useLabWorklist(enabled = true) {
  return useQuery({
    queryKey: ['lab-worklist'],
    queryFn: () => request<WorklistRow[]>('/lab-orders/worklist/'),
    enabled,
    refetchInterval: 30_000,
  })
}

export function useCriticalResults(enabled = true) {
  return useQuery({
    queryKey: ['critical-results'],
    queryFn: () => request<CriticalRow[]>('/lab-results/critical/'),
    enabled,
    refetchInterval: 30_000,
  })
}

export function usePharmacyQueue(enabled = true) {
  return useQuery({
    queryKey: ['pharmacy-queue'],
    queryFn: () => request<PharmacyQueueRow[]>('/prescriptions/queue/'),
    enabled,
    refetchInterval: 30_000,
  })
}

export function useOutstandingInvoices(enabled = true) {
  return useQuery({
    queryKey: ['outstanding-invoices'],
    queryFn: () => request<OutstandingInvoice[]>('/invoices/outstanding/'),
    enabled,
    refetchInterval: 60_000,
  })
}

export function usePatientSearch(term: string, enabled = true) {
  return useQuery({
    queryKey: ['patients', term],
    queryFn: () => request<Page<PatientSummary>>(`/patients/${query({ search: term })}`),
    enabled,
    // Search results are a lookup, not a live feed.
    staleTime: 30_000,
  })
}
