'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from './api'
import type { CriticalRow, LabOrderItemRow, LabResultRow } from './queries'

function invalidateBench(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ['lab-worklist'] })
  client.invalidateQueries({ queryKey: ['lab-orders'] })
  client.invalidateQueries({ queryKey: ['lab-order-item'] })
  client.invalidateQueries({ queryKey: ['critical-results'] })
  client.invalidateQueries({ queryKey: ['notifications'] })
}

export function useLabOrderItem(id: number | null) {
  return useQuery({
    queryKey: ['lab-order-item', id],
    queryFn: () => request<LabOrderItemRow>(`/lab-order-items/${id}/`),
    enabled: id !== null,
  })
}

export type SpecimenLabel = {
  specimen_id: string
  patient_name: string
  hospital_number: string
  test: string
  collected_at: string
}

export function useCollectSpecimen() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, condition, note }: { id: number; condition: string; note?: string }) =>
      request<{ item: LabOrderItemRow; label: SpecimenLabel }>(
        `/lab-order-items/${id}/collect/`,
        { method: 'POST', body: { condition, note: note ?? '' } },
      ),
    onSettled: () => invalidateBench(client),
  })
}

export function useStartProcessing() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      request<LabOrderItemRow>(`/lab-order-items/${id}/start-processing/`, { method: 'POST' }),
    onSettled: () => invalidateBench(client),
  })
}

export type ResultEntry = {
  parameter: number
  value_numeric?: string
  value_text?: string
  comment?: string
}

export function useEnterResults() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, entries }: { id: number; entries: ResultEntry[] }) =>
      request<LabOrderItemRow>(`/lab-order-items/${id}/results/`, {
        method: 'POST',
        body: { entries },
      }),
    onSettled: () => invalidateBench(client),
  })
}

export function useVerifyResults() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) =>
      request<LabOrderItemRow>(`/lab-order-items/${id}/verify/`, {
        method: 'POST',
        body: { comment: comment ?? '' },
      }),
    onSettled: () => invalidateBench(client),
  })
}

export function useAmendResult() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, reason, value_numeric, value_text,
    }: {
      id: number
      reason: string
      value_numeric?: string
      value_text?: string
    }) =>
      request<LabResultRow>(`/lab-results/${id}/amend/`, {
        method: 'POST',
        body: { reason, value_numeric, value_text },
      }),
    onSettled: () => invalidateBench(client),
  })
}

export function useAcknowledgeCritical() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action_taken }: { id: number; action_taken: string }) =>
      request<LabResultRow>(`/lab-results/${id}/acknowledge/`, {
        method: 'POST',
        body: { action_taken },
      }),
    onSettled: () => invalidateBench(client),
  })
}

export type { CriticalRow }
