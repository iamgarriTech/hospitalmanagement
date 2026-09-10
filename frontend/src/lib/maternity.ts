'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type AntenatalVisit = {
  id: number
  pregnancy: number
  visit: number | null
  sequence: number
  seen_at: string
  gestation_weeks: number | null
  weight_kg: string | null
  systolic_bp: number | null
  diastolic_bp: number | null
  fundal_height_cm: number | null
  fetal_heart_rate: number | null
  presentation: string
  urine_protein: string
  urine_glucose: string
  haemoglobin: string | null
  notes: string
  next_appointment: string | null
  seen_by: number
  seen_by_name: string
}

export type Baby = {
  id: number
  delivery: number
  patient: number
  name: string
  hospital_number: string
  sex: string
  birth_order: number
  outcome: 'live' | 'stillbirth_fresh' | 'stillbirth_macerated'
  outcome_display: string
  birth_weight_grams: number | null
  apgar_one_minute: number | null
  apgar_five_minutes: number | null
  resuscitation: string
  congenital_abnormality: string
}

export type Delivery = {
  id: number
  pregnancy: number
  mother: number
  mother_name: string
  admission: number | null
  procedure: number | null
  delivered_at: string
  mode: string
  mode_display: string
  onset_of_labour: string
  duration_of_labour_minutes: number | null
  estimated_blood_loss_ml: number | null
  perineal_tear: string
  complications: string
  placenta_complete: boolean | null
  delivered_by: number
  delivered_by_name: string
  recorded_by: number
  recorded_at: string
  babies: Baby[]
}

export type Pregnancy = {
  id: number
  patient: number
  patient_name: string
  hospital_number: string
  facility: number
  last_menstrual_period: string | null
  estimated_delivery_date: string
  edd_basis: string
  edd_basis_display: string
  edd_basis_note: string
  gravida: number
  parity: number
  previous_losses: number
  risk_factors: string
  status: 'ongoing' | 'delivered' | 'ended' | 'transferred'
  status_display: string
  ended_at: string | null
  ended_reason: string
  booked_by: number
  booked_by_name: string
  booked_at: string
  antenatal_visits: AntenatalVisit[]
  delivery: Delivery | null
  gestation: { weeks: number; days: number; total_days: number } | null
  is_open: boolean
}

export function usePregnancies(params = '') {
  return useQuery({
    queryKey: ['pregnancies', params],
    queryFn: async () =>
      (await request<Page<Pregnancy>>(`/pregnancies/${params}`)).results,
  })
}

export function useDueSoon(facility: number | null, withinDays = 28) {
  return useQuery({
    queryKey: ['pregnancies-due', facility, withinDays],
    queryFn: () =>
      request<{ due: Pregnancy[]; overdue: Pregnancy[]; as_at: string }>(
        `/pregnancies/due/?facility=${facility}&within_days=${withinDays}`,
      ),
    enabled: facility !== null,
  })
}

function invalidate(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: ['pregnancies'] })
  client.invalidateQueries({ queryKey: ['pregnancies-due'] })
  client.invalidateQueries({ queryKey: ['patients'] })
}

export function useBookPregnancy() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      patient: number
      facility: number
      last_menstrual_period?: string | null
      estimated_delivery_date?: string | null
      edd_basis: string
      edd_basis_note?: string
      gravida: number
      parity: number
      previous_losses: number
      risk_factors?: string
    }) => request<Pregnancy>('/pregnancies/', { method: 'POST', body: payload }),
    onSettled: () => invalidate(client),
  })
}

export function useAntenatalVisit() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      request<AntenatalVisit>(`/pregnancies/${id}/antenatal/`, {
        method: 'POST',
        body,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useReviseEdd() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, ...body
    }: {
      id: number
      estimated_delivery_date: string
      basis: string
      note: string
    }) =>
      request<Pregnancy>(`/pregnancies/${id}/revise-edd/`, { method: 'POST', body }),
    onSettled: () => invalidate(client),
  })
}

export function useRecordDelivery() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      request<Delivery>(`/pregnancies/${id}/deliver/`, { method: 'POST', body }),
    onSettled: () => invalidate(client),
  })
}

export function useEndPregnancy() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason, status }: { id: number; reason: string; status: string }) =>
      request<Pregnancy>(`/pregnancies/${id}/end/`, {
        method: 'POST',
        body: { reason, status },
      }),
    onSettled: () => invalidate(client),
  })
}
