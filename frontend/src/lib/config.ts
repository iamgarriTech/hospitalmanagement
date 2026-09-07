'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type Page, query, request } from './api'

export type PermissionOption = {
  id: number
  name: string
  codename: string
  app_label: string
  codename_full: string
}

export function usePermissionCatalogue(enabled = true) {
  return useQuery({
    queryKey: ['permission-catalogue'],
    queryFn: () => request<PermissionOption[]>('/permissions/'),
    enabled,
    staleTime: 10 * 60_000,
  })
}

export type RoleRecord = {
  id: number
  name: string
  description: string
  discount_limit: string
  permissions: number[]
  permission_codes: string[]
  assignment_count: number
  created_at: string
}

export function useRoles(enabled = true) {
  return useQuery({
    queryKey: ['roles'],
    queryFn: async () => (await request<Page<RoleRecord>>('/roles/')).results,
    enabled,
  })
}

export function useCreateRole() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { name: string; description: string; permissions: number[] }) =>
      request<RoleRecord>('/roles/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['roles'] }),
  })
}

export function useUpdateRole() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number } & Partial<{
      name: string
      description: string
      permissions: number[]
      discount_limit: string
    }>) => request<RoleRecord>(`/roles/${id}/`, { method: 'PATCH', body: payload }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['roles'] })
      client.invalidateQueries({ queryKey: ['staff'] })
    },
  })
}

export type StaffRecord = {
  id: number
  email: string
  full_name: string
  staff_id: string | null
  is_active: boolean
  is_superuser: boolean
  roles: { role: string; facility: string | null }[]
  permissions: string[]
  facilities: { id: number; code: string; name: string }[]
}

export function useStaff(search = '', enabled = true) {
  return useQuery({
    queryKey: ['staff', search],
    queryFn: async () => (await request<Page<StaffRecord>>(`/staff/${query({ search })}`)).results,
    enabled,
  })
}

export function useAssignRole() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, user, facility }: { roleId: number; user: number; facility: number | null }) =>
      request(`/roles/${roleId}/assign/`, { method: 'POST', body: { user, facility } }),
    onSettled: () => {
      client.invalidateQueries({ queryKey: ['staff'] })
      client.invalidateQueries({ queryKey: ['roles'] })
    },
  })
}

export type FacilityRecord = {
  id: number
  organization: number
  name: string
  code: string
  timezone: string
  is_active: boolean
  created_at: string
}

export function useFacilities(enabled = true) {
  return useQuery({
    queryKey: ['facilities'],
    queryFn: async () => (await request<Page<FacilityRecord>>('/facilities/')).results,
    enabled,
  })
}

export function useUpdateFacility() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number } & Partial<FacilityRecord>) =>
      request<FacilityRecord>(`/facilities/${id}/`, { method: 'PATCH', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['facilities'] }),
  })
}

export type DepartmentRecord = {
  id: number
  facility: number
  facility_code: string
  name: string
  code: string
  is_active: boolean
  clinic_count: number
}

export function useDepartments(facilityId?: number, enabled = true) {
  return useQuery({
    queryKey: ['departments', facilityId ?? null],
    queryFn: async () =>
      (await request<Page<DepartmentRecord>>(`/departments/${query({ facility: facilityId })}`))
        .results,
    enabled,
  })
}

export function useCreateDepartment() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { facility: number; name: string; code: string }) =>
      request<DepartmentRecord>('/departments/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['departments'] }),
  })
}

export type NumberSequenceRecord = {
  id: number
  key: string
  prefix: string
  include_year: boolean
  width: number
  separator: string
  next_value: number
  preview: string
}

export function useNumbering(enabled = true) {
  return useQuery({
    queryKey: ['numbering'],
    queryFn: () => request<NumberSequenceRecord[]>('/numbering/'),
    enabled,
  })
}

export function useUpdateNumbering() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number } & Partial<NumberSequenceRecord>) =>
      request<NumberSequenceRecord>(`/numbering/${id}/`, { method: 'PATCH', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['numbering'] }),
  })
}

export type AuditEventRecord = {
  id: number
  occurred_at: string
  action: string
  outcome: 'allowed' | 'denied'
  actor_email: string
  facility_code: string | null
  patient: number | null
  patient_name: string | null
  hospital_number: string | null
  resource_type: string
  resource_id: string
  changes: { before?: Record<string, unknown>; after?: Record<string, unknown> }
  reason: string
  ip_address: string | null
  request_id: string
}

export function useAuditEvents(
  filters: { action?: string; actor?: string; outcome?: string },
  enabled = true,
) {
  return useQuery({
    queryKey: ['audit-events', filters],
    queryFn: () => request<Page<AuditEventRecord>>(`/audit-events/${query(filters)}`),
    enabled,
  })
}

export function useVerifyChain() {
  return useMutation({
    mutationFn: () =>
      request<{ intact: boolean; events: number; problems: string[] }>('/audit-events/verify/'),
  })
}

export function useUpdatePaymentMethod() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: number } & Partial<{
      name: string
      requires_reference: boolean
      is_active: boolean
    }>) => request(`/payment-methods/${id}/`, { method: 'PATCH', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['payment-methods'] }),
  })
}

export function useCreatePaymentMethod() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (payload: { name: string; code: string; requires_reference: boolean }) =>
      request('/payment-methods/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['payment-methods'] }),
  })
}
