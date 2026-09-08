'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'
import type { PatientSummary } from './queries'

export type ImagingModalityRow = {
  id: number
  name: string
  code: string
  display_order: number
  is_active: boolean
}

export type ImagingProcedureRow = {
  id: number
  modality: number
  modality_name: string
  modality_code: string
  name: string
  code_short: string
  body_part: string
  preparation_instructions: string
  service: number | null
  price: string | null
  typical_minutes: number
  requires_contrast: boolean
  contraindications: string
  is_active: boolean
  code_system: string
  code: string
}

export type ImagingReportRow = {
  id: number
  order_item: number
  findings: string
  conclusion: string
  comparison: string
  is_critical: boolean
  critical_finding: string
  version: number
  is_current: boolean
  amends: number | null
  amendment_reason: string
  reported_by_name: string
  reported_at: string
  verified_by_name: string | null
  verified_at: string | null
  is_verified: boolean
  is_amended: boolean
  status_label: string
  needs_acknowledgement: boolean
  acknowledgements: {
    id: number
    acknowledged_by_name: string
    acknowledged_at: string
    action_taken: string
    minutes_to_acknowledge: number
  }[]
}

/**
 * What a caller who may not read drafts gets back instead of the report. The
 * shape is deliberately different from a report rather than a report with the
 * text blanked: a screen cannot accidentally render a conclusion that is not
 * there.
 */
export type WithheldReport = {
  id: number
  status_label: string
  is_verified: false
  reported_at: string
  awaiting_verification: true
}

export function isWithheld(
  report: ImagingReportRow | WithheldReport | null,
): report is WithheldReport {
  return report !== null && 'awaiting_verification' in report
}

export type ImagingOrderItemRow = {
  id: number
  order: number
  procedure: number
  procedure_name: string
  procedure_code: string
  modality: string
  body_part: string
  preparation_instructions: string
  status: string
  status_display: string
  allowed_transitions: string[]
  cancelled_reason: string
  scheduled_for: string | null
  performed_at: string | null
  performed_by_name: string | null
  accession_number: string
  views_taken: string
  technique_note: string
  contrast_given: string
  report: ImagingReportRow | WithheldReport | null
  report_history: {
    id: number
    version: number
    findings: string
    conclusion: string
    amendment_reason: string
    reported_by: string
    reported_at: string
    status_label: string
  }[]
}

export type ImagingOrderRow = {
  id: number
  order_number: string
  visit: number | null
  admission: number | null
  patient: number
  patient_detail: PatientSummary
  facility: number
  ordered_by: number
  ordered_by_name: string
  ordered_at: string
  priority: 'routine' | 'urgent'
  clinical_question: string
  relevant_history: string
  is_pregnant: boolean
  items: ImagingOrderItemRow[]
  preparation: { procedure: string; instructions: string }[]
}

export type ImagingWorklistRow = {
  item: number
  order: number
  order_number: string
  patient: string
  hospital_number: string
  procedure: string
  modality: string
  body_part: string
  priority: 'routine' | 'urgent'
  status: string
  status_display: string
  allowed_transitions: string[]
  ordered_at: string
  scheduled_for: string | null
  clinical_question: string
  is_pregnant: boolean
  requires_contrast: boolean
  contraindications: string
}

export type CriticalFindingRow = {
  report: number
  order: number
  patient: string
  hospital_number: string
  procedure: string
  finding: string
  conclusion: string
  reported_by: string
  verified_at: string
  requesting_clinician: string
}

function invalidateImaging(client: ReturnType<typeof useQueryClient>) {
  for (const key of [
    'imaging-worklist',
    'imaging-orders',
    'imaging-order',
    'imaging-critical',
    'notifications',
  ]) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useImagingWorklist(status?: string) {
  return useQuery({
    queryKey: ['imaging-worklist', status ?? null],
    queryFn: () =>
      request<ImagingWorklistRow[]>(
        `/imaging-orders/worklist/${status ? `?status=${status}` : ''}`,
      ),
    refetchInterval: 60_000,
  })
}

export function useImagingOrders(params: Record<string, string>) {
  return useQuery({
    queryKey: ['imaging-orders', params],
    queryFn: () => request<Page<ImagingOrderRow>>(`/imaging-orders/${query(params)}`),
    select: (page: Page<ImagingOrderRow>) => page.results,
  })
}

export function useImagingOrder(id: number | null) {
  return useQuery({
    queryKey: ['imaging-order', id],
    queryFn: () => request<ImagingOrderRow>(`/imaging-orders/${id}/`),
    enabled: id !== null,
  })
}

export function useCriticalFindings() {
  return useQuery({
    queryKey: ['imaging-critical'],
    queryFn: () => request<CriticalFindingRow[]>('/imaging-orders/critical/'),
    refetchInterval: 60_000,
  })
}

export function useImagingProcedures(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['imaging-procedures', params],
    queryFn: () => request<Page<ImagingProcedureRow>>(`/imaging-procedures/${query(params)}`),
    select: (page: Page<ImagingProcedureRow>) => page.results,
  })
}

export function useImagingModalities() {
  return useQuery({
    queryKey: ['imaging-modalities'],
    queryFn: () => request<Page<ImagingModalityRow>>(`/imaging-modalities/${query({})}`),
    select: (page: Page<ImagingModalityRow>) => page.results,
  })
}

/* --- writes -------------------------------------------------------------- */

export function useOrderImaging() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      visit?: number | null
      admission?: number | null
      procedures: number[]
      clinical_question: string
      relevant_history?: string
      priority?: string
      is_pregnant?: boolean
    }) => request<ImagingOrderRow>('/imaging-orders/', { method: 'POST', body }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useScheduleImaging() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      scheduled_for,
      note,
    }: {
      id: number
      scheduled_for: string
      note?: string
    }) =>
      request<ImagingOrderItemRow>(`/imaging-order-items/${id}/schedule/`, {
        method: 'POST',
        body: { scheduled_for, note: note ?? '' },
      }),
    onSettled: () => invalidateImaging(client),
  })
}

export function usePerformImaging() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      accession_number?: string
      views_taken?: string
      technique_note?: string
      contrast_given?: string
    }) =>
      request<ImagingOrderItemRow>(`/imaging-order-items/${id}/perform/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useWriteImagingReport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      findings: string
      conclusion: string
      comparison?: string
      is_critical?: boolean
      critical_finding?: string
    }) =>
      request<ImagingReportRow>(`/imaging-order-items/${id}/report/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useVerifyImagingReport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<ImagingReportRow>(`/imaging-reports/${id}/verify/`, { method: 'POST' }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useAmendImagingReport() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      reason: string
      findings?: string
      conclusion?: string
      is_critical?: boolean | null
      critical_finding?: string
    }) =>
      request<ImagingReportRow>(`/imaging-reports/${id}/amend/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useAcknowledgeFinding() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action_taken }: { id: number; action_taken: string }) =>
      request<ImagingReportRow>(`/imaging-reports/${id}/acknowledge/`, {
        method: 'POST',
        body: { action_taken },
      }),
    onSettled: () => invalidateImaging(client),
  })
}

export function useCancelImagingItem() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<ImagingOrderItemRow>(`/imaging-order-items/${id}/cancel/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidateImaging(client),
  })
}
