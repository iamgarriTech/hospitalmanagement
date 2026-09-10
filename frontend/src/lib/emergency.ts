'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, request } from './api'

export type TriageLevel = {
  id: number
  scale: number
  rank: number
  name: string
  colour: string
  target_minutes: number | null
  description: string
}

export type TriageScale = {
  id: number
  facility: number
  facility_name: string
  name: string
  is_active: boolean
  levels: TriageLevel[]
}

export type TriageAssessment = {
  id: number
  episode: number
  level: number
  level_name: string
  level_rank: number
  level_colour: string
  target_minutes: number | null
  sequence: number
  complaint: string
  observations: string
  reason_for_retriage: string
  assessed_by: number
  assessed_by_name: string
  assessed_at: string
}

export type EmergencyEpisode = {
  id: number
  visit: number
  patient: number
  patient_name: string
  hospital_number: string
  is_unidentified: boolean
  facility: number
  arrived_at: string
  visit_status: string
  arrival_mode: string
  arrival_mode_display: string
  presenting_complaint: string
  brought_in_by: string
  circumstances: string
  outcome: string
  outcome_display: string
  outcome_at: string | null
  outcome_note: string
  outcome_recorded_by: number | null
  outcome_recorded_by_email: string | null
  opened_at: string
  triage_assessments: TriageAssessment[]
  current_triage: TriageAssessment | null
  waiting_minutes: number
  is_open: boolean
}

export type BoardRow = {
  episode: EmergencyEpisode
  rank: number
  level: TriageLevel | null
  waited: number
  breaching: boolean
}

export type UnidentifiedRow = {
  id: number
  hospital_number: string
  name: string
  sex: string
  registered_at: string
}

export function useTriageScales() {
  return useQuery({
    queryKey: ['triage-scales'],
    queryFn: async () => (await request<Page<TriageScale>>('/triage-scales/')).results,
    staleTime: 5 * 60_000,
  })
}

export function useEmergencyBoard(facility: number | null) {
  return useQuery({
    queryKey: ['emergency-board', facility],
    queryFn: () =>
      request<BoardRow[]>(`/emergency-episodes/board/?facility=${facility}`),
    enabled: facility !== null,
    refetchInterval: 60_000,
  })
}

export function useUnidentified(facility: number | null) {
  return useQuery({
    queryKey: ['unidentified', facility],
    queryFn: () =>
      request<UnidentifiedRow[]>(
        `/emergency-episodes/unidentified/?facility=${facility}`,
      ),
    enabled: facility !== null,
  })
}

export function useEmergencyEpisodes(params = '') {
  return useQuery({
    queryKey: ['emergency-episodes', params],
    queryFn: async () =>
      (await request<Page<EmergencyEpisode>>(`/emergency-episodes/${params}`)).results,
  })
}

function invalidate(client: ReturnType<typeof useQueryClient>) {
  for (const key of ['emergency-board', 'emergency-episodes', 'unidentified',
                     'queue', 'patients']) {
    client.invalidateQueries({ queryKey: [key] })
  }
}

export function useRegisterArrival() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      facility: number
      presenting_complaint: string
      patient?: number | null
      unidentified?: boolean
      sex?: string
      estimated_age_years?: number | null
      arrival_mode?: string
      brought_in_by?: string
      circumstances?: string
    }) =>
      request<EmergencyEpisode>('/emergency-episodes/', {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useTriage() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({
      id, ...payload
    }: {
      id: number
      level: number
      complaint: string
      observations: string
      reason_for_retriage: string
    }) =>
      request<EmergencyEpisode>(`/emergency-episodes/${id}/triage/`, {
        method: 'POST',
        body: payload,
      }),
    onSettled: () => invalidate(client),
  })
}

export function useCloseEpisode() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, outcome, note }: { id: number; outcome: string; note: string }) =>
      request<EmergencyEpisode>(`/emergency-episodes/${id}/close/`, {
        method: 'POST',
        body: { outcome, note },
      }),
    onSettled: () => invalidate(client),
  })
}

export function useSeedTriageScale() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (facility: number) =>
      request<TriageScale>('/triage-scales/seed-default/', {
        method: 'POST',
        body: { facility },
      }),
    onSettled: () => client.invalidateQueries({ queryKey: ['triage-scales'] }),
  })
}
