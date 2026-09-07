'use client'

import { useMemo, useState } from 'react'
import { ErrorNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type RoleRecord, useAssignRole, useCreateRole, usePermissionCatalogue, useRoles, useStaff,
  useUpdateRole,
} from '@/lib/config'

/**
 * Roles and permissions.
 *
 * This screen is the reason the PRD's "do not hard-code permissions around
 * these roles" is actually true: a hospital invents a role here, ticks what it
 * may do, and the API enforces it immediately — no release, no migration.
 *
 * Permissions are grouped by the module they belong to rather than listed flat,
 * because a hundred checkboxes in one column is not a decision anyone can make
 * carefully. Every change is audited with the before and after sets.
 */
const MODULE_LABELS: Record<string, string> = {
  patients: 'Patients',
  visits: 'Queue and visits',
  clinical: 'Consultations and vitals',
  laboratory: 'Laboratory',
  pharmacy: 'Pharmacy',
  billing: 'Billing',
  facilities: 'Facilities',
  accounts: 'Roles and staff',
  audit: 'Audit log',
  notifications: 'Notifications',
}

export default function RolesPage() {
  const { can } = useAuth()
  const roles = useRoles()
  const catalogue = usePermissionCatalogue()
  const create = useCreateRole()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')

  const list = roles.data ?? []
  const selected = list.find((role) => role.id === selectedId) ?? null

  async function submitNew(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const role = await create.mutateAsync({
        name: newName.trim(),
        description: newDescription.trim(),
        permissions: [],
      })
      setCreating(false)
      setNewName('')
      setNewDescription('')
      setSelectedId(role.id)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not create the role.')
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Roles and permissions"
        subtitle="Roles are data. Create one, tick what it may do, and it takes effect immediately."
        action={
          can('accounts.add_role') && (
            <Button onClick={() => setCreating((open) => !open)}>
              {creating ? 'Close' : 'New role'}
            </Button>
          )
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {creating && (
        <Panel className="mt-5">
          <PanelHeader title="New role" hint="Permissions are set once it exists." />
          <form onSubmit={submitNew} className="grid gap-4 p-5 sm:grid-cols-2">
            <Field label="Name" required>
              <Input value={newName} onChange={(event) => setNewName(event.target.value)} required autoFocus />
            </Field>
            <Field label="Description">
              <Input
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
                placeholder="What this role is for"
              />
            </Field>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={create.isPending || !newName.trim()}>
                {create.isPending ? 'Creating…' : 'Create role'}
              </Button>
            </div>
          </form>
        </Panel>
      )}

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[320px_1fr]">
        <Panel>
          <PanelHeader title="Roles" hint={`${list.length} defined`} />
          {roles.isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
          ) : list.length === 0 ? (
            <div className="p-5">
              <EmptyState>No roles defined.</EmptyState>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {list.map((role) => (
                <li key={role.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(role.id)}
                    aria-current={role.id === selectedId}
                    className={`block w-full px-5 py-3 text-left transition-colors ${
                      role.id === selectedId ? 'bg-accent-muted' : 'hover:bg-surface-muted'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-semibold text-ink">{role.name}</span>
                      <span className="text-[11px] text-ink-faint">
                        {role.permission_codes.length}
                      </span>
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-faint">
                      {role.assignment_count} staff
                      {Number(role.discount_limit) > 0 &&
                        ` · discount limit ₦${Number(role.discount_limit).toLocaleString('en-NG')}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {selected ? (
          <RoleEditor
            role={selected}
            permissions={catalogue.data ?? []}
            editable={can('accounts.change_role')}
            onError={setError}
          />
        ) : (
          <Panel className="p-5">
            <EmptyState>Select a role to see and change what it may do.</EmptyState>
          </Panel>
        )}
      </div>
    </PageShell>
  )
}

function RoleEditor({
  role,
  permissions,
  editable,
  onError,
}: {
  role: RoleRecord
  permissions: { id: number; codename_full: string; name: string; app_label: string }[]
  editable: boolean
  onError: (message: string | null) => void
}) {
  const update = useUpdateRole()
  const assign = useAssignRole()
  const { facility } = useAuth()
  const [search, setSearch] = useState('')
  const staff = useStaff(search, search.length > 1)
  const [limit, setLimit] = useState(role.discount_limit)

  const grouped = useMemo(() => {
    const groups: Record<string, typeof permissions> = {}
    for (const permission of permissions) {
      if (!MODULE_LABELS[permission.app_label]) continue
      groups[permission.app_label] = [...(groups[permission.app_label] ?? []), permission]
    }
    return groups
  }, [permissions])

  const held = new Set(role.permissions)

  async function toggle(id: number) {
    onError(null)
    const next = held.has(id)
      ? role.permissions.filter((entry) => entry !== id)
      : [...role.permissions, id]
    try {
      await update.mutateAsync({ id: role.id, permissions: next })
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not change the permissions.')
    }
  }

  return (
    <div className="grid gap-5">
      <Panel>
        <PanelHeader
          title={role.name}
          hint={`${role.permission_codes.length} permissions · ${role.assignment_count} staff`}
        />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <Field
            label="Discount limit"
            hint="The largest discount this role may apply without approval."
          >
            <div className="flex gap-2">
              <Input
                type="number"
                step="0.01"
                min="0"
                value={limit}
                onChange={(event) => setLimit(event.target.value)}
                disabled={!editable}
                className="text-right"
              />
              {editable && (
                <Button
                  variant="secondary"
                  disabled={update.isPending || limit === role.discount_limit}
                  onClick={async () => {
                    onError(null)
                    try {
                      await update.mutateAsync({ id: role.id, discount_limit: limit })
                    } catch (caught) {
                      onError(
                        caught instanceof ApiError ? caught.message : 'Could not save the limit.',
                      )
                    }
                  }}
                >
                  Save
                </Button>
              )}
            </div>
          </Field>

          {editable && (
            <Field label="Grant this role to someone" hint="Search staff by name or email.">
              <Input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name or email"
              />
              {search.length > 1 && (
                <div className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-border">
                  {(staff.data ?? []).length === 0 ? (
                    <p className="px-3 py-3 text-center text-[12px] text-ink-faint">No match.</p>
                  ) : (
                    staff.data!.map((person) => (
                      <button
                        key={person.id}
                        type="button"
                        onClick={async () => {
                          onError(null)
                          try {
                            await assign.mutateAsync({
                              roleId: role.id,
                              user: person.id,
                              facility: facility?.id ?? null,
                            })
                            setSearch('')
                          } catch (caught) {
                            onError(
                              caught instanceof ApiError
                                ? caught.message
                                : 'Could not grant the role.',
                            )
                          }
                        }}
                        className="block w-full border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-surface-muted"
                      >
                        <span className="block text-[12.5px] font-medium text-ink">
                          {person.full_name}
                        </span>
                        <span className="block text-[11px] text-ink-faint">{person.email}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </Field>
          )}
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title="What this role may do"
          hint={editable ? 'Changes take effect immediately and are audited' : 'Read-only'}
        />
        <div className="grid gap-5 p-5 sm:grid-cols-2">
          {Object.entries(grouped).map(([module, entries]) => {
            const heldHere = entries.filter((entry) => held.has(entry.id)).length
            return (
              <fieldset key={module}>
                <legend className="mb-2 flex w-full items-center justify-between gap-2">
                  <span className="text-[10.5px] font-bold tracking-[0.09em] text-ink-faint uppercase">
                    {MODULE_LABELS[module]}
                  </span>
                  {heldHere > 0 && <Badge tone="accent">{heldHere}</Badge>}
                </legend>
                <div className="grid gap-0.5">
                  {entries.map((permission) => (
                    <label
                      key={permission.id}
                      className={`flex items-start gap-2 rounded-md px-2 py-1 text-[12px] ${
                        editable ? 'cursor-pointer hover:bg-surface-muted' : ''
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={held.has(permission.id)}
                        onChange={() => toggle(permission.id)}
                        disabled={!editable || update.isPending}
                        className="mt-0.5 size-3.5 rounded border-border"
                      />
                      <span className="min-w-0">
                        <span className="block text-ink">{permission.name}</span>
                        <span className="block font-mono text-[10.5px] text-ink-faint">
                          {permission.codename_full}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )
          })}
        </div>
      </Panel>
    </div>
  )
}
