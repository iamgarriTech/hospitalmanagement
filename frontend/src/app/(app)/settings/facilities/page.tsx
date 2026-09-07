'use client'

import { useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type FacilityRecord, useCreateDepartment, useDepartments, useFacilities, useUpdateFacility,
} from '@/lib/config'

/**
 * Facilities, their departments and clinics.
 *
 * Facilities are deactivated, never deleted: patients, invoices and clinical
 * records all reference the site they happened at, and removing one would break
 * the history rather than tidy it.
 */
export default function FacilitiesPage() {
  const { can } = useAuth()
  const facilities = useFacilities()
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const rows = facilities.data ?? []
  const current = rows.find((row) => row.id === selected) ?? rows[0] ?? null

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Facilities"
        subtitle="Sites, their departments, and the clinics patients are sent to."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <Panel className="mt-6">
        <PanelHeader title="Sites" hint={`${rows.length} configured`} />
        {facilities.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>No facilities configured.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={760}>
            <thead>
              <tr>
                <Th>Facility</Th>
                <Th>Code</Th>
                <Th>Time zone</Th>
                <Th>Status</Th>
                {can('facilities.change_facility') && <Th className="text-right">Change</Th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((facility) => (
                <FacilityRow
                  key={facility.id}
                  facility={facility}
                  editable={can('facilities.change_facility')}
                  onError={setError}
                  onSelect={() => setSelected(facility.id)}
                  isSelected={current?.id === facility.id}
                />
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      {current && (
        <DepartmentsPanel
          facility={current}
          canAdd={can('facilities.add_department')}
          onError={setError}
        />
      )}
    </PageShell>
  )
}

function FacilityRow({
  facility,
  editable,
  onError,
  onSelect,
  isSelected,
}: {
  facility: FacilityRecord
  editable: boolean
  onError: (message: string | null) => void
  onSelect: () => void
  isSelected: boolean
}) {
  const update = useUpdateFacility()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(facility.name)
  const [timezone, setTimezone] = useState(facility.timezone)

  async function save() {
    onError(null)
    try {
      await update.mutateAsync({ id: facility.id, name, timezone })
      setOpen(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not save the facility.')
    }
  }

  return (
    <tr className={isSelected ? 'bg-accent-muted/40' : 'hover:bg-surface-muted/50'}>
      <Td>
        {open ? (
          <Input value={name} onChange={(event) => setName(event.target.value)} aria-label="Facility name" />
        ) : (
          <button
            type="button"
            onClick={onSelect}
            aria-pressed={isSelected}
            className="text-left font-semibold text-ink hover:text-accent hover:underline"
          >
            {facility.name}
            <span className="sr-only">
              {isSelected ? ' — showing departments' : ' — show departments'}
            </span>
          </button>
        )}
      </Td>
      <Td className="font-mono text-[11.5px]">{facility.code}</Td>
      <Td>
        {open ? (
          <Input value={timezone} onChange={(event) => setTimezone(event.target.value)} aria-label="Time zone" />
        ) : (
          <span className="text-ink-muted">{facility.timezone}</span>
        )}
      </Td>
      <Td>
        {facility.is_active ? <Badge tone="normal">Active</Badge> : <Badge tone="idle">Inactive</Badge>}
      </Td>
      {editable && (
        <Td className="text-right">
          {open ? (
            <div className="flex justify-end gap-1.5">
              <Button onClick={save} disabled={update.isPending}>Save</Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          ) : (
            <div className="flex justify-end gap-1.5">
              <Button variant="ghost" onClick={() => setOpen(true)}>Change</Button>
              <Button
                variant="ghost"
                onClick={() => update.mutate({ id: facility.id, is_active: !facility.is_active })}
              >
                {facility.is_active ? 'Deactivate' : 'Reactivate'}
              </Button>
            </div>
          )}
        </Td>
      )}
    </tr>
  )
}

function DepartmentsPanel({
  facility,
  canAdd,
  onError,
}: {
  facility: FacilityRecord
  canAdd: boolean
  onError: (message: string | null) => void
}) {
  const departments = useDepartments(facility.id)
  const create = useCreateDepartment()
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [adding, setAdding] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    onError(null)
    try {
      await create.mutateAsync({ facility: facility.id, name: name.trim(), code: code.trim().toUpperCase() })
      setName('')
      setCode('')
      setAdding(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not add the department.')
    }
  }

  return (
    <Panel className="mt-5">
      <PanelHeader
        title={`Departments at ${facility.name}`}
        hint={`${(departments.data ?? []).length} configured`}
        action={
          canAdd && (
            <Button variant="secondary" onClick={() => setAdding((open) => !open)}>
              {adding ? 'Close' : 'Add department'}
            </Button>
          )
        }
      />
      {adding && (
        <form onSubmit={submit} className="grid gap-4 border-b border-border p-5 sm:grid-cols-3">
          <Field label="Name" required>
            <Input value={name} onChange={(event) => setName(event.target.value)} required autoFocus />
          </Field>
          <Field label="Code" required hint="Unique within this facility.">
            <Input value={code} onChange={(event) => setCode(event.target.value)} required />
          </Field>
          <div className="flex items-end">
            <Button type="submit" disabled={create.isPending || !name.trim() || !code.trim()}>
              {create.isPending ? 'Adding…' : 'Add'}
            </Button>
          </div>
        </form>
      )}
      {departments.isLoading ? (
        <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
      ) : (departments.data ?? []).length === 0 ? (
        <div className="p-5">
          <EmptyState>No departments at this facility yet.</EmptyState>
        </div>
      ) : (
        <TableFrame minWidth={560}>
          <thead>
            <tr>
              <Th>Department</Th>
              <Th>Code</Th>
              <Th className="text-right">Clinics</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {departments.data!.map((department) => (
              <tr key={department.id}>
                <Td className="font-medium">{department.name}</Td>
                <Td className="font-mono text-[11.5px]">{department.code}</Td>
                <Td className="text-right">{department.clinic_count}</Td>
                <Td>
                  {department.is_active ? (
                    <Badge tone="normal">Active</Badge>
                  ) : (
                    <Badge tone="idle">Inactive</Badge>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableFrame>
      )}
    </Panel>
  )
}
