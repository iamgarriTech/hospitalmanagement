'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'

export type InsuranceProviderRow = {
  id: number
  name: string
  code: string
  provider_type: string
  provider_type_display: string
  contact_name: string
  contact_phone: string
  contact_email: string
  address: string
  claim_channel: string
  claim_channel_display: string
  claim_submission_note: string
  settlement_days: number
  is_accepting_claims: boolean
  is_active: boolean
  plan_count: number
}

export type CoverageRuleRow = {
  id: number
  plan: number
  service: number | null
  service_name: string | null
  category: number | null
  category_name: string | null
  basis: 'full' | 'percentage' | 'fixed_copay' | 'excluded'
  basis_display: string
  scheme_percent: string | null
  patient_copay: string | null
  requires_preauthorisation: boolean
  exclusion_reason: string
  note: string
}

export type PlanRow = {
  id: number
  provider: number
  provider_name: string
  provider_code: string
  name: string
  code: string
  unruled_services: 'covered' | 'excluded'
  unruled_display: string
  default_scheme_percent: string
  annual_limit: string | null
  per_visit_limit: string | null
  requires_preauthorisation_above: string | null
  is_active: boolean
  rules: CoverageRuleRow[]
}

export type EligibilitySummary = {
  outcome: string
  outcome_display: string
  checked_at: string
  checked_by: string
  reference: string
  valid_until: string | null
  is_current: boolean
}

export type PatientPolicyRow = {
  id: number
  patient: number
  patient_name: string
  plan: number
  plan_detail: PlanRow
  provider_name: string
  policy_number: string
  member_name: string
  is_dependant: boolean
  relationship: string
  starts_on: string
  ends_on: string | null
  precedence: number
  is_active: boolean
  is_current: boolean
  eligibility: EligibilitySummary | null
  recorded_by: number
  recorded_at: string
}

export type PreauthorisationRow = {
  id: number
  policy: number
  policy_number: string
  provider_name: string
  patient: number
  patient_name: string
  visit: number | null
  admission: number | null
  requested_for: string
  services: number[]
  service_names: string[]
  estimated_amount: string | null
  status: 'requested' | 'approved' | 'declined' | 'expired'
  status_display: string
  reference: string
  approved_amount: string | null
  valid_from: string | null
  valid_until: string | null
  decline_reason: string
  requested_by_name: string
  requested_at: string
  decided_at: string | null
}

export type ChargeCoverageRow = {
  id: number
  invoice_item: number
  invoice_number: string
  patient_name: string
  description: string
  policy: number | null
  policy_number: string | null
  provider_code: string | null
  scheme_amount: string
  patient_amount: string
  basis: string
  basis_display: string
  applied_percent: string | null
  applied_copay: string | null
  rule_description: string
  hold_reason: string
  hold_display: string
  is_claimable: boolean
  authorisation_reference: string
  service_date: string
  resolved_at: string
}

/**
 * What the patient owes and what the schemes owe, on one invoice.
 *
 * The whole reason this endpoint exists: a cashier must never ask a patient for
 * the scheme's money. `patient_share` is the figure to collect, not `total`.
 */
export type InvoiceSplit = {
  invoice: number
  invoice_number: string
  total: string
  scheme_share: string
  patient_share: string
  unresolved: string
  lines: ChargeCoverageRow[]
}

export type ClaimLineRow = {
  id: number
  claim: number
  coverage: number
  patient_name: string
  policy_number: string
  service_description: string
  service_code: string
  service_date: string
  diagnosis_codes: string
  clinician: string
  authorisation_reference: string
  claimed_amount: string
  paid_amount: string
  written_off_amount: string
  moved_to_patient_amount: string
  unsettled: string
  status: 'pending' | 'accepted' | 'rejected'
  status_display: string
  rejection_reason: string
  shortfall_reason: string
}

export type ClaimRow = {
  id: number
  claim_number: string
  provider: number
  provider_name: string
  provider_code: string
  facility: number
  period_start: string
  period_end: string
  status: 'draft' | 'submitted' | 'acknowledged' | 'part_paid' | 'paid' | 'rejected'
  status_display: string
  allowed_transitions: string[]
  resubmits: number | null
  resubmits_number: string | null
  resubmission_reason: string
  submitted_at: string | null
  provider_reference: string
  acknowledged_at: string | null
  rejection_reason: string
  claimed_total: string
  paid_total: string
  written_off_total: string
  outstanding: string
  days_outstanding: number | null
  is_overdue: boolean
  lines: ClaimLineRow[]
  created_at: string
  /** Charges another live claim already held, reported rather than swallowed. */
  skipped?: number
}

export type ProviderPaymentRow = {
  id: number
  provider: number
  provider_name: string
  facility: number
  reference: string
  amount: string
  received_on: string
  method: number
  method_name: string
  recorded_by_name: string
  recorded_at: string
  note: string
  allocated: string
  unallocated: string
  reconciled_at: string | null
  is_frozen: boolean
}

export type AgeingRow = {
  provider: string
  code: string
  current: string
  '31-60': string
  '61-90': string
  'over 90': string
  total: string
  claims: number
  oldest_days: number
}

function invalidateInsurance(client: ReturnType<typeof useQueryClient>) {
  for (const key of [
    'insurance-providers',
    'insurance-plans',
    'coverage-rules',
    'patient-policies',
    'patient-coverage',
    'preauthorisations',
    'charge-coverage',
    'invoice-split',
    'claims',
    'claim',
    'held-coverage',
    'provider-payments',
    'ageing',
    'invoices',
    'invoice',
  ]) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

/* --- reads --------------------------------------------------------------- */

export function useInsuranceProviders(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['insurance-providers', params],
    queryFn: () =>
      request<Page<InsuranceProviderRow>>(`/insurance-providers/${query(params)}`),
    select: (page: Page<InsuranceProviderRow>) => page.results,
  })
}

export function useInsurancePlans(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['insurance-plans', params],
    queryFn: () => request<Page<PlanRow>>(`/insurance-plans/${query(params)}`),
    select: (page: Page<PlanRow>) => page.results,
  })
}

export function usePatientPolicies(patientId: number | null) {
  return useQuery({
    queryKey: ['patient-policies', patientId],
    queryFn: () =>
      request<Page<PatientPolicyRow>>(
        `/patient-policies/${query({ patient: patientId })}`,
      ),
    select: (page: Page<PatientPolicyRow>) => page.results,
    enabled: patientId !== null,
  })
}

/**
 * What cover a patient has *today*, for the point-of-service screens.
 *
 * Returns `has_cover: false` for a self-paying patient rather than erroring —
 * most patients here pay for themselves, so that is a normal answer.
 */
export function usePatientCoverage(patientId: number | null) {
  return useQuery({
    queryKey: ['patient-coverage', patientId],
    queryFn: () =>
      request<{
        patient: number
        patient_name: string
        has_cover: boolean
        policies: PatientPolicyRow[]
      }>(`/patient-policies/for-patient/${query({ patient: patientId })}`),
    enabled: patientId !== null,
  })
}

export function useInvoiceSplit(invoiceId: number | null) {
  return useQuery({
    queryKey: ['invoice-split', invoiceId],
    queryFn: () =>
      request<InvoiceSplit>(
        `/charge-coverage/invoice-split/${query({ invoice: invoiceId })}`,
      ),
    enabled: invoiceId !== null,
    // A patient with no cover has no coverage rows and the endpoint still
    // answers, so a 403 here means the caller may not read scheme money — not
    // that something is broken.
    retry: false,
  })
}

export function useHeldCoverage() {
  return useQuery({
    queryKey: ['held-coverage'],
    queryFn: () => request<ChargeCoverageRow[]>('/charge-coverage/held/'),
    refetchInterval: 120_000,
  })
}

export function usePreauthorisations(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['preauthorisations', params],
    queryFn: () =>
      request<Page<PreauthorisationRow>>(`/preauthorisations/${query(params)}`),
    select: (page: Page<PreauthorisationRow>) => page.results,
  })
}

export function useOutstandingPreauthorisations() {
  return useQuery({
    queryKey: ['preauthorisations', 'outstanding'],
    queryFn: () => request<PreauthorisationRow[]>('/preauthorisations/outstanding/'),
    refetchInterval: 120_000,
  })
}

export function useClaims(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['claims', params],
    queryFn: () => request<Page<ClaimRow>>(`/claims/${query(params)}`),
    select: (page: Page<ClaimRow>) => page.results,
  })
}

export function useClaim(id: number | null) {
  return useQuery({
    queryKey: ['claim', id],
    queryFn: () => request<ClaimRow>(`/claims/${id}/`),
    enabled: id !== null,
  })
}

export function useClaimable(params: {
  provider: number | null
  facility: number | null
  period_start: string
  period_end: string
}) {
  const ready =
    params.provider !== null &&
    params.facility !== null &&
    Boolean(params.period_start) &&
    Boolean(params.period_end)
  return useQuery({
    queryKey: ['claims', 'claimable', params],
    queryFn: () =>
      request<{ provider: string; total: string; lines: ChargeCoverageRow[] }>(
        `/claims/claimable/${query({
          provider: params.provider,
          facility: params.facility,
          period_start: params.period_start,
          period_end: params.period_end,
        })}`,
      ),
    enabled: ready,
  })
}

export function useAgeing(facilityId: number | null) {
  return useQuery({
    queryKey: ['ageing', facilityId],
    queryFn: () =>
      request<AgeingRow[]>(
        `/insurance-providers/ageing/${query({ facility: facilityId })}`,
      ),
  })
}

export function useProviderPayments(params: Record<string, string> = {}) {
  return useQuery({
    queryKey: ['provider-payments', params],
    queryFn: () =>
      request<Page<ProviderPaymentRow>>(`/provider-payments/${query(params)}`),
    select: (page: Page<ProviderPaymentRow>) => page.results,
  })
}

/* --- writes -------------------------------------------------------------- */

export function useSaveProvider() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id?: number } & Record<string, unknown>) =>
      id
        ? request<InsuranceProviderRow>(`/insurance-providers/${id}/`, {
            method: 'PATCH',
            body,
          })
        : request<InsuranceProviderRow>('/insurance-providers/', {
            method: 'POST',
            body,
          }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useSavePlan() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id?: number } & Record<string, unknown>) =>
      id
        ? request<PlanRow>(`/insurance-plans/${id}/`, { method: 'PATCH', body })
        : request<PlanRow>('/insurance-plans/', { method: 'POST', body }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useSaveCoverageRule() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request<CoverageRuleRow>('/coverage-rules/', { method: 'POST', body }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useDeleteCoverageRule() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<void>(`/coverage-rules/${id}/`, { method: 'DELETE' }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useRecordPolicy() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request<PatientPolicyRow>('/patient-policies/', { method: 'POST', body }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useCheckEligibility() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      request<PatientPolicyRow>(`/patient-policies/${id}/eligibility/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useRequestPreauthorisation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request<PreauthorisationRow>('/preauthorisations/', { method: 'POST', body }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useDecidePreauthorisation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      request<PreauthorisationRow>(`/preauthorisations/${id}/decide/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useAssembleClaim() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      provider: number
      facility: number
      period_start: string
      period_end: string
    }) => request<ClaimRow>('/claims/assemble/', { method: 'POST', body }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useSubmitClaim() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, provider_reference }: { id: number; provider_reference: string }) =>
      request<ClaimRow>(`/claims/${id}/submit/`, {
        method: 'POST',
        body: { provider_reference },
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useAcknowledgeClaim() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, provider_reference }: { id: number; provider_reference?: string }) =>
      request<ClaimRow>(`/claims/${id}/acknowledge/`, {
        method: 'POST',
        body: { provider_reference: provider_reference ?? '' },
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useRejectClaim() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      reason,
      line_reasons,
    }: {
      id: number
      reason: string
      line_reasons?: Record<string, string>
    }) =>
      request<ClaimRow>(`/claims/${id}/reject/`, {
        method: 'POST',
        body: { reason, line_reasons: line_reasons ?? {} },
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useResubmitClaim() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<ClaimRow>(`/claims/${id}/resubmit/`, { method: 'POST', body: { reason } }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useRecordProviderPayment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      provider: number
      facility: number
      reference: string
      amount: string
      received_on: string
      method: number
      note?: string
      allocations: { line: number; amount: string }[]
    }) =>
      request<ProviderPaymentRow>('/provider-payments/record/', {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidateInsurance(client),
  })
}

export function useResolveShortfall() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      write_off,
      move_to_patient,
      reason,
    }: {
      id: number
      write_off?: string
      move_to_patient?: string
      reason: string
    }) =>
      request<ClaimLineRow>(`/claim-lines/${id}/shortfall/`, {
        method: 'POST',
        body: {
          write_off: write_off ?? '0',
          move_to_patient: move_to_patient ?? '0',
          reason,
        },
      }),
    onSettled: () => invalidateInsurance(client),
  })
}
