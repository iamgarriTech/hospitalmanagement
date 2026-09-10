'use client'

import { useQuery } from '@tanstack/react-query'
import { request } from './api'

export type ReportSummary = {
  key: string
  title: string
  group: string
  description: string
  notes: string
  is_snapshot: boolean
}

export type ReportColumn = {
  key: string
  label: string
  numeric: boolean
  money: boolean
}

export type ReportResult = {
  key: string
  title: string
  group: string
  description: string
  notes: string
  is_snapshot: boolean
  columns: ReportColumn[]
  rows: Record<string, string | number | null>[]
  row_count: number
  run_at: string
  run_by: string
  filters: {
    date_from: string | null
    date_to: string | null
    facilities: number[] | null
    facility_scope: string
  }
}

export function useReportCatalogue() {
  return useQuery({
    queryKey: ['report-catalogue'],
    queryFn: () => request<ReportSummary[]>('/reports/'),
    staleTime: 5 * 60_000,
  })
}

export function useReport(
  key: string | null,
  filters: { from: string; to: string; facility: string },
) {
  const query = new URLSearchParams()
  if (filters.from) query.set('date_from', filters.from)
  if (filters.to) query.set('date_to', filters.to)
  if (filters.facility) query.set('facility', filters.facility)

  return useQuery({
    queryKey: ['report', key, filters.from, filters.to, filters.facility],
    queryFn: () => request<ReportResult>(`/reports/${key}/?${query}`),
    enabled: key !== null,
  })
}

/**
 * The CSV export URL.
 *
 * A plain link rather than a fetch: the browser handles the download, the
 * session cookie goes with it, and the server names the file. Fetching it
 * into memory to re-offer it as a blob would break on a large export and
 * gains nothing.
 */
export function exportUrl(
  key: string,
  filters: { from: string; to: string; facility: string },
) {
  const query = new URLSearchParams()
  if (filters.from) query.set('date_from', filters.from)
  if (filters.to) query.set('date_to', filters.to)
  if (filters.facility) query.set('facility', filters.facility)
  return `/api/reports/${key}/export/?${query}`
}
