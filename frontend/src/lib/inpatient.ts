'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'
import type { PatientSummary } from './queries'

/* Shapes the inpatient screens actually read. Hand-written for the same reason
   the outpatient ones are: it is honest about what is being consumed. */

export type WardRow = {
  id: number
  facility: number
  facility_name: string
  name: string
  code: string
  ward_type: string
  ward_type_display: string
  nightly_service: number | null
  nightly_rate: string | null
  is_active: boolean
  occupancy: BedCensus
}

export type BedCensus = {
  beds: number
  occupied: number
  available: number
  reserved: number
  cleaning: number
  maintenance: number
}

export type OverdueDose = {
  dose_id: number
  medication: string
  due_at: string
  minutes_late: number | null
}

export type WardEscalation = {
  id: number
  measurement: string
  value: string
  direction: 'low' | 'high'
  instruction: string
  raised_at: string
  minutes_waiting: number
}

export type BoardBed = {
  bed: number
  bed_label: string
  room: string
  state: string
  state_display: string
  state_note: string
  patient: {
    id: number
    name: string
    hospital_number: string
    sex: string
    age_years: number | null
    admission: number
    admission_number: string
    admitted_at: string
    nights: number
    diagnosis: string
    consultant: string
    discharge_planned: boolean
    expected_discharge_date: string | null
    allergies: string[]
    overdue_doses: OverdueDose[]
    overdue_count: number
    escalations: WardEscalation[]
    escalation_count: number
  } | null
}

/** What the caller may act on. The board offers only the buttons that will work. */
export type BoardCapabilities = {
  admit: boolean
  transfer: boolean
  plan_discharge: boolean
  discharge: boolean
  administer: boolean
  observe: boolean
  manage_beds: boolean
}

export type WardBoard = {
  ward: { id: number; name: string; code: string }
  occupancy: BedCensus
  beds: BoardBed[]
  overdue: { window_hours: number; in_window: number; older: number }
  can: BoardCapabilities
}

export type BedRow = {
  id: number
  room: number
  room_code: string
  ward: number
  ward_name: string
  code: string
  label: string
  service_state: string
  state: string
  state_display: string
  state_note: string
  is_active: boolean
  occupant: {
    patient: number
    patient_name: string
    hospital_number: string
    admission: number
    admission_number: string
    since: string
    nights: number
  } | null
}

export type AdmissionRequestRow = {
  id: number
  patient: number
  patient_detail: PatientSummary
  visit: number | null
  facility: number
  ward: number
  ward_name: string
  reason: string
  working_diagnosis: string
  responsible_consultant: number
  consultant_name: string
  priority: 'routine' | 'urgent'
  requested_by: number
  requested_by_name: string
  requested_at: string
  status: string
  status_display: string
  decline_reason: string
  waiting_minutes: number
  admission: number | null
  /** Carried on the request itself: a ward clerk allocating a bed should not
   *  have to open a chart to learn the patient is allergic to something. */
  allergies: string[]
}

export type MovementLeg = {
  bed: string
  ward: string
  from: string
  to: string | null
  nights: number
}

export type AdmissionRow = {
  id: number
  admission_number: string
  patient: number
  patient_detail: PatientSummary
  visit: number | null
  facility: number
  admission_reason: string
  admission_diagnosis: string
  consultant_name: string
  admitted_by_name: string
  admitted_at: string
  status: string
  status_display: string
  expected_discharge_date: string | null
  discharge_destination: string
  destination_display: string
  discharge_plan_notes: string
  discharged_at: string | null
  discharged_by_name: string | null
  discharge_diagnosis: string
  follow_up_instructions: string
  billing_override_reason: string
  length_of_stay_nights: number
  bed: {
    id: number
    label: string
    room: string
    ward: number
    ward_name: string
    since: string
  } | null
  movement: MovementLeg[]
  transfers: {
    id: number
    from_bed: string
    from_ward: string
    to_bed: string
    to_ward: string
    changed_ward: boolean
    reason: string
    authorised_by_name: string
    moved_at: string
  }[]
  allergies: string[]
}

export type DischargeBilling = {
  admission: number
  nights_occupied: number
  nights_charged_now: { ward: string; date: string }[]
  invoices: {
    id: number
    invoice_number: string
    status: string
    total: string
    balance: string
    items: number
  }[]
  outstanding: string[]
  can_override: boolean
}

export type DischargeSummary = {
  admission_number: string
  patient_name: string
  hospital_number: string
  sex: string
  age_years: number | null
  facility: string
  admitted_at: string
  discharged_at: string | null
  nights: number
  admission_diagnosis: string
  discharge_diagnosis: string
  destination: string
  responsible_consultant: string
  movement: MovementLeg[]
  reviews: { date: string; clinician: string; notes: string; diagnoses: string[] }[]
  investigations: {
    test: string
    when: string
    results: { parameter: string; value: string; flag: string }[]
  }[]
  imaging: { procedure: string; when: string | null; conclusion: string; amended: boolean }[]
  discharge_medication: {
    medication: string
    directions: string
    instructions: string
    quantity: number
  }[]
  follow_up_instructions: string
}

/* --- the drug chart ------------------------------------------------------ */

export type ChartCell = {
  dose_id: number
  due_at: string
  status: string
  state_label: string
  by: string | null
  at: string | null
  minutes_late: number | null
  reason: string
}

export type ChartRow = {
  item_id: number
  medication: string
  medication_id: number
  directions: string
  status: string
  cells: Record<string, ChartCell>
}

export type DrugChart = { columns: string[]; rows: ChartRow[] }

export type BedsideWarning = { kind: string; severity: string; detail: string }

/* --- nursing ------------------------------------------------------------- */

export type NursingAssessmentRow = {
  id: number
  admission: number
  patient: number
  patient_name: string
  shift: string
  shift_display: string
  observations: number | null
  consciousness: string
  consciousness_display: string
  mobility: string
  mobility_display: string
  falls_risk: boolean
  pressure_area_concern: boolean
  eating_and_drinking: string
  continence: string
  summary: string
  recorded_by_name: string
  recorded_at: string
}

export type NursingNoteRow = {
  id: number
  admission: number
  shift: string
  shift_display: string
  note: string
  supersedes: number | null
  correction_reason: string
  is_superseded: boolean
  corrected_by: number | null
  author_name: string
  recorded_at: string
}

export type FluidBalance = {
  from: string
  to: string
  hours: number
  intake_ml: number
  output_ml: number
  balance_ml: number
  by_route: Record<string, number>
  entries: number
}

export type EscalationRow = {
  id: number
  admission: number
  patient: number
  patient_name: string
  observations: number
  measurement: string
  measurement_display: string
  value: string
  direction: 'low' | 'high'
  breached_bound: string
  instruction: string
  summary: string
  raised_at: string
  raised_by_name: string
  escalated_to_name: string | null
  escalated_at: string | null
  acknowledged_by_name: string | null
  acknowledged_at: string | null
  action_taken: string
  is_outstanding: boolean
  minutes_waiting: number
}

export type EscalationThresholdRow = {
  id: number
  ward: number
  measurement: string
  measurement_display: string
  low: string | null
  high: string | null
  instruction: string
  is_active: boolean
}

/* --- reads --------------------------------------------------------------- */

function invalidateWard(client: ReturnType<typeof useQueryClient>) {
  for (const key of [
    'ward-board',
    'wards',
    'beds',
    'admissions',
    'admission',
    'admission-requests',
    'drug-chart',
    'overdue-doses',
    'escalations',
    'notifications',
  ]) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useWards(facility?: number) {
  return useQuery({
    queryKey: ['wards', facility ?? null],
    queryFn: () =>
      request<Page<WardRow>>(`/wards/${query(facility ? { facility: String(facility) } : {})}`),
    select: (page: Page<WardRow>) => page.results,
  })
}

/**
 * The board a ward keeps open. Refetched on an interval because a handover
 * screen showing a bed as free after somebody filled it is worse than one that
 * is briefly a few seconds behind.
 */
export function useWardBoard(wardId: number | null) {
  return useQuery({
    queryKey: ['ward-board', wardId],
    queryFn: () => request<WardBoard>(`/wards/${wardId}/board/`),
    enabled: wardId !== null,
    refetchInterval: 30_000,
  })
}

export function useBeds(params: Record<string, string>) {
  return useQuery({
    queryKey: ['beds', params],
    queryFn: () => request<Page<BedRow>>(`/beds/${query(params)}`),
    select: (page: Page<BedRow>) => page.results,
  })
}

export function usePendingAdmissionRequests(wardId?: number) {
  return useQuery({
    queryKey: ['admission-requests', wardId ?? null],
    queryFn: () =>
      request<AdmissionRequestRow[]>(
        `/admission-requests/pending/${wardId ? `?ward=${wardId}` : ''}`,
      ),
    refetchInterval: 60_000,
  })
}

export function useAdmissions(params: Record<string, string>) {
  return useQuery({
    queryKey: ['admissions', params],
    queryFn: () => request<Page<AdmissionRow>>(`/admissions/${query(params)}`),
    select: (page: Page<AdmissionRow>) => page.results,
  })
}

export function useAdmission(id: number | null) {
  return useQuery({
    queryKey: ['admission', id],
    queryFn: () => request<AdmissionRow>(`/admissions/${id}/`),
    enabled: id !== null,
  })
}

export function useDrugChart(admissionId: number | null, days = 7) {
  return useQuery({
    queryKey: ['drug-chart', admissionId, days],
    queryFn: () =>
      request<DrugChart>(`/scheduled-doses/chart/?admission=${admissionId}&days=${days}`),
    enabled: admissionId !== null,
  })
}

export function useBedsideWarnings(doseId: number | null) {
  return useQuery({
    queryKey: ['bedside-warnings', doseId],
    queryFn: () =>
      request<{
        dose: number
        medication: string
        patient: string
        warnings: BedsideWarning[]
      }>(`/scheduled-doses/${doseId}/warnings/`),
    enabled: doseId !== null,
  })
}

export function useNursingAssessments(admissionId: number | null) {
  return useQuery({
    queryKey: ['nursing-assessments', admissionId],
    queryFn: () =>
      request<Page<NursingAssessmentRow>>(`/nursing-assessments/${query({
        admission: String(admissionId),
      })}`),
    select: (page: Page<NursingAssessmentRow>) => page.results,
    enabled: admissionId !== null,
  })
}

export function useNursingNotes(admissionId: number | null) {
  return useQuery({
    queryKey: ['nursing-notes', admissionId],
    queryFn: () =>
      request<Page<NursingNoteRow>>(`/nursing-notes/${query({ admission: String(admissionId) })}`),
    select: (page: Page<NursingNoteRow>) => page.results,
    enabled: admissionId !== null,
  })
}

export function useFluidBalance(admissionId: number | null, hours = 24) {
  return useQuery({
    queryKey: ['fluid-balance', admissionId, hours],
    queryFn: () =>
      request<FluidBalance>(`/fluid-balance/balance/?admission=${admissionId}&hours=${hours}`),
    enabled: admissionId !== null,
  })
}

export function useEscalations(params: Record<string, string>) {
  return useQuery({
    queryKey: ['escalations', params],
    queryFn: () => request<Page<EscalationRow>>(`/escalations/${query(params)}`),
    select: (page: Page<EscalationRow>) => page.results,
  })
}

export function useOutstandingEscalations(wardId?: number) {
  return useQuery({
    queryKey: ['escalations', 'outstanding', wardId ?? null],
    queryFn: () =>
      request<EscalationRow[]>(
        `/escalations/outstanding/${wardId ? `?ward=${wardId}` : ''}`,
      ),
    refetchInterval: 60_000,
  })
}

export function useEscalationThresholds(wardId: number | null) {
  return useQuery({
    queryKey: ['escalation-thresholds', wardId],
    queryFn: () =>
      request<Page<EscalationThresholdRow>>(`/escalation-thresholds/${query({ ward: String(wardId) })}`),
    select: (page: Page<EscalationThresholdRow>) => page.results,
    enabled: wardId !== null,
  })
}

export function useDischargeBilling(admissionId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['discharge-billing', admissionId],
    queryFn: () => request<DischargeBilling>(`/admissions/${admissionId}/billing/`),
    enabled: admissionId !== null && enabled,
  })
}

export function useDischargeSummary(admissionId: number | null, enabled = true) {
  return useQuery({
    queryKey: ['discharge-summary', admissionId],
    queryFn: () => request<DischargeSummary>(`/admissions/${admissionId}/summary/`),
    enabled: admissionId !== null && enabled,
  })
}

/* --- writes -------------------------------------------------------------- */

export function useRequestAdmission() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      patient: number
      facility: number
      visit?: number | null
      ward: number
      reason: string
      working_diagnosis: string
      responsible_consultant: number
      priority: string
    }) => request<AdmissionRequestRow>('/admission-requests/', { method: 'POST', body }),
    onSettled: () => invalidateWard(client),
  })
}

export function useDeclineAdmissionRequest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<AdmissionRequestRow>(`/admission-requests/${id}/decline/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidateWard(client),
  })
}

export function useAdmit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      bed: number
      request?: number
      patient?: number
      facility?: number
      visit?: number | null
      reason?: string
      diagnosis?: string
      responsible_consultant?: number
    }) => request<AdmissionRow>('/admissions/admit/', { method: 'POST', body }),
    onSettled: () => invalidateWard(client),
  })
}

export function useTransfer() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, to_bed, reason }: { id: number; to_bed: number; reason: string }) =>
      request<unknown>(`/admissions/${id}/transfer/`, {
        method: 'POST',
        body: { to_bed, reason },
      }),
    onSettled: () => invalidateWard(client),
  })
}

export function usePlanDischarge() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      expected_date,
      destination,
      notes,
    }: {
      id: number
      expected_date: string | null
      destination: string
      notes: string
    }) =>
      request<AdmissionRow>(`/admissions/${id}/plan-discharge/`, {
        method: 'POST',
        body: { expected_date, destination, notes },
      }),
    onSettled: () => invalidateWard(client),
  })
}

export function useDischarge() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      diagnosis,
      destination,
      instructions,
      override_reason,
    }: {
      id: number
      diagnosis: string
      destination: string
      instructions: string
      override_reason?: string
    }) =>
      request<AdmissionRow>(`/admissions/${id}/discharge/`, {
        method: 'POST',
        body: { diagnosis, destination, instructions, override_reason: override_reason ?? '' },
      }),
    onSettled: (_data, _error, variables) => {
      invalidateWard(client)
      client.invalidateQueries({ queryKey: ['discharge-billing', variables.id] })
      client.invalidateQueries({ queryKey: ['discharge-summary', variables.id] })
    },
  })
}

export function useSetBedState() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      service_state,
      note,
    }: {
      id: number
      service_state: string
      note: string
    }) =>
      request<BedRow>(`/beds/${id}/state/`, {
        method: 'POST',
        body: { service_state, note },
      }),
    onSettled: () => invalidateWard(client),
  })
}

export function useScheduleDoses() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      prescription_item,
      admission,
    }: {
      prescription_item: number
      admission: number
    }) =>
      request<unknown>('/scheduled-doses/schedule/', {
        method: 'POST',
        body: { prescription_item, admission },
      }),
    onSettled: () => invalidateWard(client),
  })
}

export type RecordDosePayload = {
  id: number
  state: string
  batch?: number | null
  dose_given?: string | null
  reason?: string
  note?: string
  override_reason?: string
}

export function useRecordDose() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: RecordDosePayload) =>
      request<unknown>(`/scheduled-doses/${id}/record/`, { method: 'POST', body }),
    onSettled: () => invalidateWard(client),
  })
}

export function useDiscontinueMedication() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      prescription_item,
      reason,
    }: {
      prescription_item: number
      reason: string
    }) =>
      request<{ future_doses_cancelled: number; doses_already_given: number }>(
        '/scheduled-doses/discontinue/',
        { method: 'POST', body: { prescription_item, reason } },
      ),
    onSettled: () => invalidateWard(client),
  })
}

export function useRecordAssessment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request<NursingAssessmentRow>('/nursing-assessments/', { method: 'POST', body }),
    onSettled: (_d, _e, body) => {
      client.invalidateQueries({
        queryKey: ['nursing-assessments', (body as { admission: number }).admission],
      })
    },
  })
}

export function useWriteNursingNote() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      admission: number
      shift: string
      note: string
      supersedes?: number | null
      correction_reason?: string
    }) => request<NursingNoteRow>('/nursing-notes/', { method: 'POST', body }),
    onSettled: (_d, _e, body) => {
      client.invalidateQueries({ queryKey: ['nursing-notes', body.admission] })
    },
  })
}

export function useRecordFluid() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      admission: number
      direction: string
      route: string
      volume_ml: number
      note?: string
    }) => request<unknown>('/fluid-balance/', { method: 'POST', body }),
    onSettled: (_d, _e, body) => {
      client.invalidateQueries({ queryKey: ['fluid-balance', body.admission] })
    },
  })
}

export function useAcknowledgeEscalation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action_taken }: { id: number; action_taken: string }) =>
      request<EscalationRow>(`/escalations/${id}/acknowledge/`, {
        method: 'POST',
        body: { action_taken },
      }),
    onSettled: () => invalidateWard(client),
  })
}
