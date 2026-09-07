'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'
import type { Encounter, LabOrderRow, PrescriptionRow } from './queries'

/* --- vitals -------------------------------------------------------------- */

export type VitalsPayload = {
  patient: number
  visit: number | null
  facility: number
  temperature_c?: string
  systolic_bp?: number
  diastolic_bp?: number
  pulse_bpm?: number
  respiratory_rate?: number
  oxygen_saturation?: number
  weight_kg?: string
  height_cm?: string
  blood_glucose_mmol?: string
  pain_score?: number
}

export type VitalsRecord = VitalsPayload & {
  id: number
  bmi: number | null
  blood_pressure: string | null
  recorded_by_email: string
  recorded_at: string
  is_erroneous: boolean
  error_reason: string
}

export function useRecordVitals() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: VitalsPayload) =>
      request<VitalsRecord>('/vitals/', { method: 'POST', body: payload }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['vitals-trend'] })
      client.invalidateQueries({ queryKey: ['vitals'] })
    },
  })
}

export function useVitals(params: { patient?: number; visit?: number; enabled?: boolean }) {
  const { patient, visit, enabled = true } = params
  return useQuery({
    queryKey: ['vitals', patient ?? null, visit ?? null],
    queryFn: () => request<Page<VitalsRecord>>(`/vitals/${query({ patient, visit })}`),
    enabled,
  })
}

/* --- encounters ---------------------------------------------------------- */

export type DiagnosisInput = {
  description: string
  certainty: string
  is_primary: boolean
}

export const NARRATIVE_FIELDS = [
  'presenting_complaint',
  'history_of_presenting_complaint',
  'past_medical_history',
  'surgical_history',
  'family_history',
  'social_history',
  'medication_history',
  'examination_findings',
  'clinical_notes',
  'treatment_plan',
  'follow_up_plan',
] as const

export type NarrativeField = (typeof NARRATIVE_FIELDS)[number]
export type Narrative = Record<NarrativeField, string>

export function useEncounter(id: number | null) {
  return useQuery({
    queryKey: ['encounter', id],
    queryFn: () => request<Encounter>(`/encounters/${id}/`),
    enabled: id !== null,
  })
}

export function useEncounterVersions(id: number | null, enabled = true) {
  return useQuery({
    queryKey: ['encounter-versions', id],
    queryFn: () =>
      request<Encounter['current'][]>(`/encounters/${id}/versions/`) as Promise<
        NonNullable<Encounter['current']>[]
      >,
    enabled: enabled && id !== null,
  })
}

export function useOpenEncounter() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { visit: number } & Partial<Narrative> & {
      diagnoses?: DiagnosisInput[]
    }) => request<Encounter>('/encounters/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['encounters'] }),
  })
}

export function useSaveDraft(id: number | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<Narrative> & { diagnoses?: DiagnosisInput[] }) =>
      request<Encounter>(`/encounters/${id}/`, { method: 'PATCH', body: payload }),
    onSuccess: (data) => client.setQueryData(['encounter', id], data),
  })
}

export function useFinaliseEncounter(id: number | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => request<Encounter>(`/encounters/${id}/finalise/`, { method: 'POST' }),
    onSuccess: (data) => {
      client.setQueryData(['encounter', id], data)
      client.invalidateQueries({ queryKey: ['encounters'] })
      client.invalidateQueries({ queryKey: ['invoices'] })
    },
  })
}

export function useAmendEncounter(id: number | null) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { reason: string } & Partial<Narrative> & {
      diagnoses?: DiagnosisInput[]
    }) => request<Encounter>(`/encounters/${id}/amend/`, { method: 'POST', body: payload }),
    onSuccess: (data) => {
      client.setQueryData(['encounter', id], data)
      client.invalidateQueries({ queryKey: ['encounter-versions', id] })
      client.invalidateQueries({ queryKey: ['encounters'] })
    },
  })
}

/* --- laboratory ordering -------------------------------------------------- */

export type LabTestOption = {
  id: number
  name: string
  short_code: string
  category_name: string
  specimen_type: string
  specimen_requirements: string
  is_panel: boolean
  turnaround_hours: number
  parameters: { id: number; name: string; unit: string; value_type: string; choices_csv: string }[]
}

export function useLabTests(enabled = true) {
  return useQuery({
    queryKey: ['lab-tests'],
    queryFn: async () => (await request<Page<LabTestOption>>('/lab-tests/')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useOrderLabTests() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      visit: number
      tests: number[]
      priority: string
      clinical_details: string
    }) => request<LabOrderRow>('/lab-orders/', { method: 'POST', body: payload }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['lab-orders'] })
      client.invalidateQueries({ queryKey: ['lab-worklist'] })
      client.invalidateQueries({ queryKey: ['invoices'] })
    },
  })
}

/* --- prescribing ---------------------------------------------------------- */

export type MedicationOption = {
  id: number
  label: string
  generic_name: string
  brand_name: string
  strength: string
  dosage_form: string
  default_route: string
  dispensing_unit: string
  category_name: string
  stock_on_hand: number
  paediatric_caution: boolean
  avoid_in_renal_impairment: boolean
  caution_note: string
  dose_ranges: {
    id: number
    route: string
    min_single_dose: string
    max_single_dose: string
    dose_unit: string
    max_daily_dose: string | null
  }[]
}

export function useMedications(search = '', enabled = true) {
  return useQuery({
    queryKey: ['medications', search],
    queryFn: async () =>
      (await request<Page<MedicationOption>>(`/medications/${query({ search })}`)).results,
    enabled,
    staleTime: 60_000,
  })
}

export type SafetyWarning = {
  kind: string
  severity: 'critical' | 'warning' | 'advisory'
  detail: string
  requires_reason: boolean
  evidence: Record<string, unknown>
}

export type SafetyCapability = {
  active: boolean
  detail: string
  provider?: string | null
}

/**
 * Which checks are running — and which are not. Read on the prescribing screen
 * so it can state plainly that drug–drug interaction checking is absent unless
 * a licensed provider is configured. A clinician who assumes a check happened
 * prescribes as though it did.
 */
export function useSafetyCapabilities(enabled = true) {
  return useQuery({
    queryKey: ['safety-capabilities'],
    queryFn: () => request<Record<string, SafetyCapability>>('/prescriptions/safety-capabilities/'),
    enabled,
    staleTime: 10 * 60_000,
  })
}

export function useScreenMedication() {
  return useMutation({
    mutationFn: (payload: {
      patient: number
      medication: number
      dose?: string
      route?: string
      frequency_per_day?: number
    }) =>
      request<{ warnings: SafetyWarning[]; capabilities: Record<string, SafetyCapability> }>(
        '/prescriptions/screen/',
        { method: 'POST', body: payload },
      ),
  })
}

export type PrescriptionItemInput = {
  medication: number
  dose: string
  dose_unit: string
  route: string
  frequency_per_day: number
  duration_days: number
  quantity_prescribed: number
  instructions: string
}

export function useWritePrescription() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      visit: number
      encounter?: number | null
      items: PrescriptionItemInput[]
      notes?: string
      acknowledge_warnings?: boolean
      override_reason?: string
    }) => request<PrescriptionRow>('/prescriptions/', { method: 'POST', body: payload }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['prescriptions'] })
      client.invalidateQueries({ queryKey: ['pharmacy-queue'] })
    },
  })
}
