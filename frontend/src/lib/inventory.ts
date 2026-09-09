'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type ItemCategory = { id: number; name: string; display_order: number }

export type InventoryItem = {
  id: number
  category: number
  category_name: string
  name: string
  code: string
  unit_of_issue: string
  default_reorder_level: number
  is_controlled: boolean
  tracks_expiry: boolean
  is_active: boolean
}

export type Store = {
  id: number
  facility: number
  facility_name: string
  name: string
  code: string
  kind: 'main' | 'pharmacy' | 'ward' | 'theatre' | 'laboratory' | 'imaging'
  kind_display: string
  ward: number | null
  ward_name: string | null
  adjustment_authorisation_limit: string
  expiry_horizon_days: number
  is_active: boolean
}

export type StockLot = {
  id: number
  record: number
  lot_number: string
  expiry_date: string | null
  quantity_on_hand: number
  unit_cost: string
  received_at: string
  is_expired: boolean
}

export type StockRecord = {
  id: number
  store: number
  store_name: string
  item: number
  item_name: string
  item_code: string
  unit_of_issue: string
  is_controlled: boolean
  tracks_expiry: boolean
  reorder_level: number
  is_active: boolean
  on_hand: number
  usable_on_hand: number
  is_low: boolean
  lots: StockLot[]
}

export type StockMovement = {
  id: number
  lot: number
  lot_number: string
  item_name: string
  store_name: string
  kind: 'receipt' | 'issue' | 'transfer_out' | 'transfer_in' | 'adjustment' | 'return'
  kind_display: string
  quantity_delta: number
  quantity_after: number
  issued_to: string
  reason: string
  transfer: number | null
  adjustment: number | null
  recorded_by: number
  recorded_by_email: string
  recorded_at: string
}

export type StockAdjustment = {
  id: number
  lot: number
  lot_number: string
  item_name: string
  store_name: string
  kind: 'count' | 'damage' | 'loss' | 'expiry' | 'return_to_supplier'
  kind_display: string
  quantity_delta: number
  value: string
  reason: string
  raised_by: number
  raised_by_email: string
  authorised_by: number | null
  authorised_by_email: string | null
  raised_at: string
}

export type StockTransfer = {
  id: number
  item: number
  item_name: string
  from_store: number
  from_store_name: string
  to_store: number
  to_store_name: string
  quantity: number
  reason: string
  moved_by: number
  moved_by_email: string
  moved_at: string
}

export type LowStockRow = {
  record: number
  store: number
  store_name: string
  item: number
  item_name: string
  unit_of_issue: string
  reorder_level: number
  usable_on_hand: number
  on_hand: number
}

export type ExpiringRow = {
  lot: number
  lot_number: string
  store: number
  store_name: string
  item_name: string
  quantity_on_hand: number
  expiry_date: string
  days_left: number
  is_expired: boolean
}

export function useStores(enabled = true) {
  return useQuery({
    queryKey: ['stores'],
    queryFn: async () => (await request<Page<Store>>('/stores/')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useInventoryItems(enabled = true) {
  return useQuery({
    queryKey: ['inventory-items'],
    queryFn: async () =>
      (await request<Page<InventoryItem>>('/inventory-items/?active=true')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useItemCategories(enabled = true) {
  return useQuery({
    queryKey: ['item-categories'],
    queryFn: async () => (await request<Page<ItemCategory>>('/item-categories/')).results,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export function useStockRecords(store: number | null, enabled = true) {
  return useQuery({
    queryKey: ['stock-records', store],
    queryFn: async () =>
      (await request<Page<StockRecord>>(`/stock-records/?store=${store}`)).results,
    enabled: enabled && store !== null,
  })
}

export function useStockAlerts(store: number | null = null) {
  return useQuery({
    queryKey: ['stock-alerts', store],
    queryFn: () =>
      request<{ low: LowStockRow[]; expiring: ExpiringRow[] }>(
        store === null ? '/stock-alerts/' : `/stock-alerts/?store=${store}`,
      ),
  })
}

export function useStockMovements(record: number | null) {
  return useQuery({
    queryKey: ['stock-movements', record],
    queryFn: () => request<StockMovement[]>(`/stock-records/${record}/movements/`),
    enabled: record !== null,
  })
}

export function useStockAdjustments(enabled = true) {
  return useQuery({
    queryKey: ['stock-adjustments'],
    queryFn: async () =>
      (await request<Page<StockAdjustment>>('/stock-adjustments/')).results,
    enabled,
  })
}

export function useStockTransfers(enabled = true) {
  return useQuery({
    queryKey: ['stock-transfers'],
    queryFn: async () =>
      (await request<Page<StockTransfer>>('/stock-transfers/')).results,
    enabled,
  })
}

function invalidateStock(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ['stock-records'] })
  client.invalidateQueries({ queryKey: ['stock-alerts'] })
  client.invalidateQueries({ queryKey: ['stock-movements'] })
  client.invalidateQueries({ queryKey: ['stock-adjustments'] })
  client.invalidateQueries({ queryKey: ['stock-transfers'] })
}

export function useReceiveStock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      record, ...payload
    }: {
      record: number
      quantity: number
      lot_number: string
      expiry_date: string | null
      unit_cost: string
      reason: string
    }) =>
      request<StockRecord>(`/stock-records/${record}/receive/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidateStock(client),
  })
}

export function useIssueStock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      record, ...payload
    }: {
      record: number
      quantity: number
      issued_to: string
      reason: string
    }) =>
      request<StockRecord>(`/stock-records/${record}/issue/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidateStock(client),
  })
}

export function useTransferStock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      item: number
      from_store: number
      to_store: number
      quantity: number
      reason: string
    }) => request<StockTransfer>('/stock-transfers/', { method: 'POST', body: payload }),
    onSettled: () => invalidateStock(client),
  })
}

export function useAdjustStock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      lot: number
      kind: StockAdjustment['kind']
      quantity_delta: number
      reason: string
      authorised_by: number | null
    }) =>
      request<StockAdjustment>('/stock-adjustments/', { method: 'POST', body: payload }),
    onSettled: () => invalidateStock(client),
  })
}

export function useStockRecordCreate() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { store: number; item: number; reorder_level: number }) =>
      request<StockRecord>('/stock-records/', { method: 'POST', body: payload }),
    onSettled: () => invalidateStock(client),
  })
}

export function useStockRecordUpdate() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number; reorder_level: number }) =>
      request<StockRecord>(`/stock-records/${id}/`, { method: 'PATCH', body: payload }),
    onSettled: () => invalidateStock(client),
  })
}
