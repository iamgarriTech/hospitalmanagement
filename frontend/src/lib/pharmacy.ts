'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'
import type { PrescriptionRow } from './queries'

export type StockBatch = {
  id: number
  medication: number
  medication_label: string
  facility: number
  batch_number: string
  expiry_date: string
  quantity_on_hand: number
  unit_cost: string
  is_expired: boolean
  received_at: string
}

export function useStockBatches(params: {
  medication?: number
  available?: boolean
  enabled?: boolean
}) {
  const { medication, available, enabled = true } = params
  return useQuery({
    queryKey: ['stock-batches', medication ?? null, available ?? null],
    queryFn: async () =>
      (
        await request<Page<StockBatch>>(
          `/stock-batches/${query({ medication, available: available ? 'true' : undefined })}`,
        )
      ).results,
    enabled,
  })
}

export function useDispense() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      itemId, batch, quantity, note,
    }: {
      itemId: number
      batch: number
      quantity: number
      note?: string
    }) =>
      request<PrescriptionRow['items'][number]>(`/prescription-items/${itemId}/dispense/`, {
        method: 'POST',
        body: { batch, quantity, note: note ?? '' },
      }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['pharmacy-queue'] })
      client.invalidateQueries({ queryKey: ['prescriptions'] })
      client.invalidateQueries({ queryKey: ['stock-batches'] })
      client.invalidateQueries({ queryKey: ['invoices'] })
      client.invalidateQueries({ queryKey: ['medications'] })
    },
  })
}

export type DispenseHistoryRow = {
  dispensed_at: string
  medication: string
  quantity: number
  batch_number: string
  expiry_date: string
  dispensed_by: string
  prescription_number: string
}

export function useDispenseHistory(patientId?: number, enabled = true) {
  return useQuery({
    queryKey: ['dispense-history', patientId ?? null],
    queryFn: () =>
      request<DispenseHistoryRow[]>(`/prescriptions/history/${query({ patient: patientId })}`),
    enabled,
  })
}

export function useReceiveStock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      medication: number
      facility: number
      batch_number: string
      expiry_date: string
      quantity_on_hand: number
      unit_cost: string
    }) => request<StockBatch>('/stock-batches/', { method: 'POST', body: payload }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['stock-batches'] })
      client.invalidateQueries({ queryKey: ['medications'] })
    },
  })
}
