'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'
import type { InvoiceRow } from './queries'

export type PaymentMethod = {
  id: number
  name: string
  code: string
  requires_reference: boolean
  is_active: boolean
}

export function usePaymentMethods(enabled = true) {
  return useQuery({
    queryKey: ['payment-methods'],
    queryFn: async () => (await request<Page<PaymentMethod>>('/payment-methods/')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export type MethodVariance = {
  method: number
  method_name: string
  expected: string
  counted: string | null
  variance: string | null
  note: string
  counted_at_all: boolean
}

export type SessionAdjustment = {
  id: number
  session: number
  method: number | null
  method_name: string | null
  kind: 'shortage' | 'overage' | 'misposted'
  kind_display: string
  amount: string
  reason: string
  raised_by: number
  raised_by_email: string
  raised_at: string
}

export type CashierSession = {
  id: number
  cashier: number
  cashier_email: string
  facility: number
  status: 'open' | 'closed' | 'reconciled'
  opened_at: string
  closed_at: string | null
  reconciled_at: string | null
  opening_float: string
  counted_total: string | null
  variance_note: string
  expected_total: string
  is_frozen: boolean
  variance_by_method: MethodVariance[]
  unexplained: string[]
  net_variance: string
  adjustments: SessionAdjustment[]
  adjustment_total: string
}

export type TillHandover = {
  id: number
  from_session: number
  to_session: number
  float_handed: string
  handed_by: number
  handed_by_email: string
  received_by: number
  received_by_email: string
  handed_at: string
  note: string
}

/** One line of the count sheet as the cashier fills it in. */
export type CountEntry = { method: number; counted: string; note: string }

export function useCashierSessions(enabled = true) {
  return useQuery({
    queryKey: ['cashier-sessions'],
    queryFn: async () => (await request<Page<CashierSession>>('/cashier-sessions/')).results,
    enabled,
  })
}

function invalidateMoney(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ['invoices'] })
  client.invalidateQueries({ queryKey: ['invoice'] })
  client.invalidateQueries({ queryKey: ['outstanding-invoices'] })
  client.invalidateQueries({ queryKey: ['cashier-sessions'] })
}

export function useOpenSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { facility: number; opening_float: string }) =>
      request<CashierSession>('/cashier-sessions/', { method: 'POST', body: payload }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useCloseSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<CashierSession>(`/cashier-sessions/${id}/close/`, { method: 'POST' }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useReconcileSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, counts, variance_note,
    }: {
      id: number
      counts: CountEntry[]
      variance_note: string
    }) =>
      request<CashierSession>(`/cashier-sessions/${id}/reconcile/`, {
        method: 'POST',
        body: { counts, variance_note },
      }),
    onSettled: () => invalidateMoney(client),
  })
}

/** A correction to a session already signed off. Never an edit to it. */
export function useAdjustSession() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, kind, method, amount, reason,
    }: {
      id: number
      kind: SessionAdjustment['kind']
      method: number | null
      amount: string
      reason: string
    }) =>
      request<SessionAdjustment>(`/cashier-sessions/${id}/adjust/`, {
        method: 'POST',
        body: { kind, method, amount, reason },
      }),
    onSettled: () => invalidateMoney(client),
  })
}

/**
 * Taking over a colleague's till. Called by whoever is receiving it, which is
 * what makes the second signature real.
 */
export function useReceiveTill() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, counts, float_handed, note,
    }: {
      id: number
      counts: CountEntry[]
      float_handed: string
      note: string
    }) =>
      request<TillHandover>(`/cashier-sessions/${id}/handover/`, {
        method: 'POST',
        body: { counts, float_handed, note },
      }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useInvoice(id: number | null) {
  return useQuery({
    queryKey: ['invoice', id],
    queryFn: () => request<InvoiceRow>(`/invoices/${id}/`),
    enabled: id !== null,
  })
}

export function useFinaliseInvoice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<InvoiceRow>(`/invoices/${id}/finalise/`, { method: 'POST' }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useApplyDiscount() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, amount, reason }: { id: number; amount: string; reason: string }) =>
      request<InvoiceRow>(`/invoices/${id}/discount/`, {
        method: 'POST',
        body: { amount, reason },
      }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useVoidInvoice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<InvoiceRow>(`/invoices/${id}/void/`, { method: 'POST', body: { reason } }),
    onSettled: () => invalidateMoney(client),
  })
}

export type PaymentRecord = InvoiceRow['payments'][number]

/**
 * Payments carry an idempotency key generated by the caller.
 *
 * The key belongs to the *attempt*, not the request: if the network drops after
 * the server has taken the money but before the response arrives, the retry
 * must reuse the same key and get the same receipt back. A key regenerated per
 * request would charge the patient twice.
 */
export function useRecordPayment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      invoice: number
      method: number
      amount: string
      reference: string
      idempotency_key: string
    }) => request<PaymentRecord>('/payments/', { method: 'POST', body: payload }),
    onSettled: () => invalidateMoney(client),
  })
}

export function useRefund() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, amount, reason }: { id: number; amount: string; reason: string }) =>
      request<PaymentRecord>(`/payments/${id}/refund/`, {
        method: 'POST',
        body: { amount, reason },
      }),
    onSettled: () => invalidateMoney(client),
  })
}

export type Receipt = {
  receipt_number: string
  issued_at: string
  patient_name: string
  hospital_number: string
  invoice_number: string
  facility: string
  items: { description: string; quantity: number; unit_price: string; amount: string }[]
  subtotal: string
  discount: string
  tax: string
  total: string
  amount_paid: string
  method: string
  reference: string
  received_by: string
  balance_after: string
  is_reprint: boolean
}

export function fetchReceipt(paymentId: number, reprint: boolean) {
  return request<Receipt>(`/payments/${paymentId}/receipt/${reprint ? '?reprint=true' : ''}`)
}

export type Service = {
  id: number
  category: number
  category_name: string
  name: string
  code: string
  is_active: boolean
  prices: { id: number; facility: number; amount: string; is_active: boolean; updated_at: string }[]
}

export function useServices(enabled = true) {
  return useQuery({
    queryKey: ['services'],
    queryFn: async () => (await request<Page<Service>>('/services/')).results,
    enabled,
  })
}

export function useSetServicePrice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, facility, amount }: { id: number; facility: number; amount: string }) =>
      request(`/services/${id}/price/`, { method: 'POST', body: { facility, amount } }),
    onSettled: () => client.invalidateQueries({ queryKey: ['services'] }),
  })
}

/** A key per attempt. Falls back where crypto.randomUUID is unavailable. */
export function newIdempotencyKey() {
  try {
    return crypto.randomUUID()
  } catch {
    return `k-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  }
}
