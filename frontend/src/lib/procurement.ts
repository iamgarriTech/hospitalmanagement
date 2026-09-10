'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type Supplier = {
  id: number
  name: string
  code: string
  contact_name: string
  phone: string
  email: string
  address: string
  payment_terms_days: number
  is_approved: boolean
  approval_note: string
}

export type PurchaseRequestLine = {
  id: number
  item: number
  item_name: string
  unit_of_issue: string
  quantity: number
  estimated_unit_cost: string
  note: string
}

export type PurchaseRequest = {
  id: number
  reference: string
  store: number
  store_name: string
  justification: string
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'ordered'
  status_display: string
  requested_by: number
  requested_by_email: string
  requested_at: string
  submitted_at: string | null
  decided_by: number | null
  decided_by_email: string | null
  decided_at: string | null
  decision_note: string
  lines: PurchaseRequestLine[]
  estimated_value: string
  needs_approval: boolean
}

export type PurchaseOrderLine = {
  id: number
  item: number
  item_name: string
  item_code: string
  unit_of_issue: string
  tracks_expiry: boolean
  quantity_ordered: number
  quantity_received: number
  unit_cost: string
  outstanding: number
  is_complete: boolean
}

export type PurchaseOrder = {
  id: number
  reference: string
  request: number
  request_reference: string
  supplier: number
  supplier_name: string
  store: number
  store_name: string
  expected_date: string | null
  status: 'open' | 'partially_received' | 'received' | 'cancelled'
  status_display: string
  note: string
  raised_by: number
  raised_by_email: string
  raised_at: string
  cancelled_at: string | null
  cancellation_reason: string
  lines: PurchaseOrderLine[]
  total_ordered: string
  total_received_value: string
}

export type GoodsReceiptLine = {
  id: number
  order_line: number
  item_name: string
  quantity: number
  lot_number: string
  expiry_date: string | null
  movement: number
  movement_balance: number
}

export type GoodsReceipt = {
  id: number
  reference: string
  order: number
  order_reference: string
  delivery_note: string
  received_by: number
  received_by_email: string
  received_at: string
  note: string
  lines: GoodsReceiptLine[]
  total_value: string
}

export type SupplierInvoice = {
  id: number
  order: number
  order_reference: string
  supplier_name: string
  supplier_reference: string
  invoice_date: string
  amount: string
  status: 'received' | 'matched' | 'queried' | 'approved' | 'paid'
  status_display: string
  matched_at: string | null
  matched_value: string | null
  discrepancies: string[]
  query_note: string
  approved_by: number | null
  approved_by_email: string | null
  approved_at: string | null
  recorded_by: number
  recorded_by_email: string
  recorded_at: string
  total_ordered: string
}

/** One line of a delivery as the storekeeper types it in. */
export type DeliveryLine = {
  order_line: number
  quantity: number
  lot_number: string
  expiry_date: string | null
}

export function useSuppliers(approvedOnly = false) {
  return useQuery({
    queryKey: ['suppliers', approvedOnly],
    queryFn: async () =>
      (await request<Page<Supplier>>(
        approvedOnly ? '/suppliers/?approved=true' : '/suppliers/',
      )).results,
    staleTime: 5 * 60_000,
  })
}

export function usePurchaseRequests(status?: string) {
  return useQuery({
    queryKey: ['purchase-requests', status ?? 'all'],
    queryFn: async () =>
      (await request<Page<PurchaseRequest>>(
        status ? `/purchase-requests/?status=${status}` : '/purchase-requests/',
      )).results,
  })
}

export function usePurchaseOrders(outstandingOnly = false) {
  return useQuery({
    queryKey: ['purchase-orders', outstandingOnly],
    queryFn: async () =>
      (await request<Page<PurchaseOrder>>(
        outstandingOnly ? '/purchase-orders/?outstanding=true' : '/purchase-orders/',
      )).results,
  })
}

export function useSupplierInvoices() {
  return useQuery({
    queryKey: ['supplier-invoices'],
    queryFn: async () =>
      (await request<Page<SupplierInvoice>>('/supplier-invoices/')).results,
  })
}

export function useGoodsReceipts(order: number | null) {
  return useQuery({
    queryKey: ['goods-receipts', order],
    queryFn: () => request<GoodsReceipt[]>(`/purchase-orders/${order}/receipts/`),
    enabled: order !== null,
  })
}

function invalidate(client: ReturnType<typeof useQueryClient>) {
  for (const key of [
    'purchase-requests', 'purchase-orders', 'supplier-invoices', 'goods-receipts',
    'stock-records', 'stock-alerts', 'stock-movements', 'suppliers',
  ]) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useCreateRequest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      store: number
      justification: string
      lines: { item: number; quantity: number; estimated_unit_cost: string }[]
    }) =>
      request<PurchaseRequest>('/purchase-requests/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}

export function useSubmitRequest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<PurchaseRequest>(`/purchase-requests/${id}/submit/`, { method: 'POST' }),
    onSettled: () => invalidate(client),
  })
}

export function useDecideRequest() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: number; approve: boolean; note: string }) =>
      request<PurchaseRequest>(`/purchase-requests/${id}/decide/`, {
        method: 'POST',
        body: { approve, note },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useRaiseOrder() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      request: number
      supplier: number
      expected_date: string | null
      note: string
      prices: Record<string, string>
    }) =>
      request<PurchaseOrder>('/raise-purchase-order/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}

export function useReceiveGoods() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      order, ...payload
    }: {
      order: number
      deliveries: DeliveryLine[]
      delivery_note: string
      note: string
    }) =>
      request<GoodsReceipt>(`/purchase-orders/${order}/receive/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useCancelOrder() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      request<PurchaseOrder>(`/purchase-orders/${id}/cancel/`, {
        method: 'POST',
        body: { reason },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useRecordInvoice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      order: number
      supplier_reference: string
      invoice_date: string
      amount: string
    }) =>
      request<SupplierInvoice>('/supplier-invoices/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}

export function useMatchInvoice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<SupplierInvoice>(`/supplier-invoices/${id}/match/`, { method: 'POST' }),
    onSettled: () => invalidate(client),
  })
}

export function useApproveInvoice() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      request<SupplierInvoice>(`/supplier-invoices/${id}/approve/`, {
        method: 'POST',
        body: { note },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useSaveSupplier() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: Partial<Supplier> & { id?: number }) =>
      id
        ? request<Supplier>(`/suppliers/${id}/`, { method: 'PATCH', body: payload })
        : request<Supplier>('/suppliers/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}
