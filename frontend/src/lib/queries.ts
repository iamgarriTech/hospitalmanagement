'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  allowed_transitions: string[]
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
    medication_id: number
    medication: string
    dispensing_unit: string
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


/* --- mutations ---------------------------------------------------------- */

/**
 * Moving a patient through the queue. Invalidates rather than patching the
 * cache: two people work the same board, so after a move the truth is whatever
 * the server now says, not what this tab predicted.
 */
export function useMoveVisit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, to, note }: { id: number; to: string; note?: string }) =>
      request<QueueRow>(`/visits/${id}/move/`, { method: 'POST', body: { to, note: note ?? '' } }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['queue'] })
      client.invalidateQueries({ queryKey: ['visit'] })
    },
  })
}

export type CheckInPayload = {
  patient: number
  facility: number
  visit_type: string
  reason?: string
  clinic?: number | null
}

export function useCheckIn() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: CheckInPayload) =>
      request<{ id: number; visit_number: string; status: string }>('/visits/', {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ['queue'] }),
  })
}

export type PatientDetail = PatientSummary & {
  family_name: string
  given_name: string
  other_names: string
  blood_group: string
  genotype: string
  email: string
  phone_alternate: string
  address_line: string
  city: string
  state: string
  country: string
  facility: number
  merged_into: number | null
  merged_into_hospital_number: string | null
  allergies: {
    id: number
    substance: string
    reaction: string
    severity: string
    is_active: boolean
  }[]
  chronic_conditions: { id: number; condition: string; is_active: boolean }[]
  next_of_kin: {
    id: number
    full_name: string
    relationship: string
    phone: string
    is_emergency_contact: boolean
  }[]
  created_at: string
  updated_at: string
}

export function usePatient(id: number | null) {
  return useQuery({
    queryKey: ['patient', id],
    queryFn: () => request<PatientDetail>(`/patients/${id}/`),
    enabled: id !== null,
  })
}

export type DuplicateCandidate = {
  patient: PatientSummary
  score: number
  reasons: string[]
}

export function useRegisterPatient() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      request<PatientDetail>('/patients/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['patients'] }),
  })
}

export function useVisitsForPatient(patientId: number | null) {
  return useQuery({
    queryKey: ['visits', patientId],
    queryFn: () => request<Page<QueueRow>>(`/visits/${query({ patient: patientId })}`),
    enabled: patientId !== null,
  })
}


/* --- patient record ------------------------------------------------------ */

export type EncounterVersion = {
  id: number
  version_number: number
  is_current: boolean
  authored_by: string
  authored_at: string
  amendment_reason: string
  amends: number | null
  diagnoses: {
    id: number
    description: string
    certainty: string
    is_primary: boolean
    code_system: string
    code: string
  }[]
  presenting_complaint: string
  history_of_presenting_complaint: string
  past_medical_history: string
  surgical_history: string
  family_history: string
  social_history: string
  medication_history: string
  examination_findings: string
  clinical_notes: string
  treatment_plan: string
  follow_up_plan: string
}

export type Encounter = {
  id: number
  visit: number
  patient: number
  patient_name: string
  encounter_type: string
  status: 'draft' | 'final' | 'amended'
  clinician_email: string
  started_at: string
  finalised_at: string | null
  version_count: number
  current: EncounterVersion | null
}

export function useEncounters(params: { patient?: number; visit?: number; enabled?: boolean }) {
  const { patient, visit, enabled = true } = params
  return useQuery({
    queryKey: ['encounters', patient ?? null, visit ?? null],
    queryFn: () => request<Page<Encounter>>(`/encounters/${query({ patient, visit })}`),
    enabled,
  })
}

export type VitalsSeries = Record<string, { at: string; value: number }[]>

export function useVitalsTrend(patientId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['vitals-trend', patientId],
    queryFn: () => request<VitalsSeries>(`/vitals/trend/${query({ patient: patientId })}`),
    enabled: enabled && patientId !== null,
  })
}

export type LabResultRow = {
  id: number
  parameter_name: string
  display_value: string
  unit: string
  flag: string
  flag_label: string
  reference_text: string
  is_abnormal: boolean
  is_critical: boolean
  version: number
  amendment_reason: string
  entered_by_email: string
  entered_at: string
  acknowledgements: { by: string; at: string; action_taken: string }[]
}

export type LabOrderItemRow = {
  id: number
  test: number
  test_name: string
  test_code: string
  status: string
  specimen: { specimen_id: string; collected_at: string; condition: string } | null
  results: LabResultRow[]
  superseded_results: LabResultRow[]
  verified_by_email: string | null
  verified_at: string | null
  laboratory_comment: string
  allowed_transitions: string[]
}

export type LabOrderRow = {
  id: number
  order_number: string
  /** One or the other: an inpatient order on day nine has no attendance. */
  visit: number | null
  admission: number | null
  patient: number
  patient_name: string
  hospital_number: string
  ordered_by_email: string
  ordered_at: string
  priority: 'routine' | 'urgent'
  clinical_details: string
  items: LabOrderItemRow[]
}

export function useLabOrders(params: { patient?: number; visit?: number; enabled?: boolean }) {
  const { patient, visit, enabled = true } = params
  return useQuery({
    queryKey: ['lab-orders', patient ?? null, visit ?? null],
    queryFn: () => request<Page<LabOrderRow>>(`/lab-orders/${query({ patient, visit })}`),
    enabled,
  })
}

export type PrescriptionRow = {
  id: number
  prescription_number: string
  visit: number
  patient: number
  patient_name: string
  hospital_number: string
  prescribed_by_email: string
  prescribed_at: string
  status: string
  notes: string
  items: {
    id: number
    medication: number
    medication_label: string
    dose: string
    dose_unit: string
    route: string
    frequency_per_day: number
    duration_days: number
    quantity_prescribed: number
    quantity_dispensed: number
    quantity_outstanding: number
    instructions: string
    status: string
    dispenses: {
      id: number
      quantity: number
      batch_number: string
      expiry_date: string
      medication_label: string
      dispensed_by_email: string
      dispensed_at: string
    }[]
    overrides: { kind: string; detail: string; reason: string; by: string; at: string }[]
  }[]
}

export function usePrescriptions(params: {
  patient?: number
  visit?: number
  status?: string
  enabled?: boolean
}) {
  const { patient, visit, status, enabled = true } = params
  return useQuery({
    queryKey: ['prescriptions', patient ?? null, visit ?? null, status ?? null],
    queryFn: () =>
      request<Page<PrescriptionRow>>(`/prescriptions/${query({ patient, visit, status })}`),
    enabled,
  })
}

export type InvoiceRow = {
  id: number
  invoice_number: string
  patient: number
  patient_name: string
  hospital_number: string
  visit: number | null
  status: string
  discount_amount: string
  discount_reason: string
  tax_amount: string
  subtotal: string
  total: string
  amount_paid: string
  amount_refunded: string
  balance: string
  is_frozen: boolean
  created_at: string
  items: {
    id: number
    description: string
    quantity: number
    unit_price: string
    amount: string
    source_type: string
    is_cancelled: boolean
  }[]
  payments: {
    id: number
    receipt_number: string
    method_name: string
    amount: string
    reference: string
    received_by_email: string
    received_at: string
    reprint_count: number
    amount_refunded: string
    refunds: { id: number; reference: string; amount: string; reason: string }[]
  }[]
}

export function useInvoices(params: { patient?: number; visit?: number; enabled?: boolean }) {
  const { patient, visit, enabled = true } = params
  return useQuery({
    queryKey: ['invoices', patient ?? null, visit ?? null],
    queryFn: () => request<Page<InvoiceRow>>(`/invoices/${query({ patient, visit })}`),
    enabled,
  })
}

export type AccessLogEntry = {
  id: number
  occurred_at: string
  action: string
  outcome: string
  actor: string
  ip_address: string | null
  reason: string
}

export function useAccessLog(patientId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['access-log', patientId],
    queryFn: () => request<AccessLogEntry[]>(`/patients/${patientId}/access-log/`),
    enabled: enabled && patientId !== null,
  })
}
