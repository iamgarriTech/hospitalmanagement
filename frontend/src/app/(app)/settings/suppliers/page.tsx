'use client'

import { useState } from 'react'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type Supplier, useSaveSupplier, useSuppliers } from '@/lib/procurement'

/**
 * Suppliers.
 *
 * A configuration screen, so it uses the shared list-and-form shape.
 *
 * Suspending a supplier is a state rather than a deletion: one who supplied
 * for three years and is now under review still has to appear on the orders
 * they fulfilled. Suspension stops new orders and leaves the history alone,
 * and the change is audited because it takes effect across every branch.
 */
export default function SuppliersPage() {
  const { can } = useAuth()
  const suppliers = useSuppliers()
  const save = useSaveSupplier()

  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    name: '', code: '', contact_name: '', phone: '', email: '', address: '',
    payment_terms_days: '30', is_approved: true, approval_note: '',
  })

  const canEdit = can('inventory.change_supplier')
  const canAdd = can('inventory.add_supplier')

  function open(supplier: Supplier | null) {
    setError(null)
    if (supplier) {
      setEditing(supplier.id)
      setForm({
        name: supplier.name,
        code: supplier.code,
        contact_name: supplier.contact_name,
        phone: supplier.phone,
        email: supplier.email,
        address: supplier.address,
        payment_terms_days: String(supplier.payment_terms_days),
        is_approved: supplier.is_approved,
        approval_note: supplier.approval_note,
      })
    } else {
      setEditing('new')
      setForm({
        name: '', code: '', contact_name: '', phone: '', email: '', address: '',
        payment_terms_days: '30', is_approved: true, approval_note: '',
      })
    }
  }

  async function submit() {
    setError(null)
    try {
      await save.mutateAsync({
        id: editing === 'new' ? undefined : (editing ?? undefined),
        name: form.name,
        code: form.code,
        contact_name: form.contact_name,
        phone: form.phone,
        email: form.email,
        address: form.address,
        payment_terms_days: Number(form.payment_terms_days),
        is_approved: form.is_approved,
        approval_note: form.approval_note,
      })
      setEditing(null)
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That supplier could not be saved.',
      )
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Suppliers"
        subtitle="Who the hospital buys from, on what terms, and whether they may still be ordered from."
      />

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.3fr_1fr]">
        <Panel>
          <PanelHeader
            title="Suppliers"
            hint="Suspending one stops new orders and leaves past orders untouched."
            action={
              canAdd ? (
                <Button variant="secondary" onClick={() => open(null)}>Add supplier</Button>
              ) : null
            }
          />
          {suppliers.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : (suppliers.data ?? []).length === 0 ? (
            <div className="p-5"><EmptyState>No suppliers yet.</EmptyState></div>
          ) : (
            <TableFrame minWidth={640}>
              <thead>
                <tr>
                  <Th>Supplier</Th>
                  <Th>Contact</Th>
                  <Th className="text-right">Terms</Th>
                  <Th>Status</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {(suppliers.data ?? []).map((supplier) => (
                  <tr key={supplier.id}>
                    <Td>
                      <span className="font-medium text-ink">{supplier.name}</span>
                      <div className="text-[11px] text-ink-faint">{supplier.code}</div>
                    </Td>
                    <Td className="text-ink-muted">
                      {supplier.contact_name || <span className="text-ink-faint">—</span>}
                      {supplier.phone && (
                        <div className="text-[11px] text-ink-faint">{supplier.phone}</div>
                      )}
                    </Td>
                    <Td className="text-right text-ink-muted">
                      {supplier.payment_terms_days} days
                    </Td>
                    <Td>
                      {supplier.is_approved ? (
                        <Badge tone="normal">approved</Badge>
                      ) : (
                        <>
                          <Badge tone="critical">suspended</Badge>
                          {supplier.approval_note && (
                            <div className="mt-1 max-w-[24ch] text-[11px] leading-relaxed text-ink-muted">
                              {supplier.approval_note}
                            </div>
                          )}
                        </>
                      )}
                    </Td>
                    <Td>
                      {canEdit && (
                        <button
                          type="button"
                          onClick={() => open(supplier)}
                          className="text-[12px] font-medium text-accent hover:underline"
                        >
                          Edit
                        </button>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        {editing !== null && (
          <Panel>
            <PanelHeader title={editing === 'new' ? 'New supplier' : 'Edit supplier'} />
            <div className="grid gap-4 p-5">
              {error && <ErrorNotice>{error}</ErrorNotice>}
              <Field label="Name" required>
                <Input
                  value={form.name}
                  maxLength={200}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </Field>
              <Field label="Code" required hint="Short, unique. Appears on orders.">
                <Input
                  value={form.code}
                  maxLength={20}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                />
              </Field>
              <Field label="Contact name">
                <Input
                  value={form.contact_name}
                  maxLength={160}
                  onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                />
              </Field>
              <Field label="Phone">
                <Input
                  value={form.phone}
                  maxLength={40}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </Field>
              <Field label="Email">
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </Field>
              <Field label="Address">
                <Textarea
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </Field>
              <Field
                label="Payment terms"
                required
                hint="Days from invoice to payment, as agreed."
              >
                <Input
                  type="number"
                  min={0}
                  value={form.payment_terms_days}
                  onChange={(e) =>
                    setForm({ ...form, payment_terms_days: e.target.value })
                  }
                  className="text-right"
                />
              </Field>

              <div>
                <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
                  <input
                    type="checkbox"
                    checked={form.is_approved}
                    onChange={(e) => setForm({ ...form, is_approved: e.target.checked })}
                    className="size-4 rounded border-border"
                  />
                  Approved to supply
                </label>
                <p className="mt-1 pl-6.5 text-[12px] leading-relaxed text-ink-muted">
                  Turning this off stops new orders across every branch. Orders they
                  already fulfilled are untouched.
                </p>
              </div>

              {!form.is_approved && (
                <Field
                  label="Why they are suspended"
                  required
                  hint="Shown to anyone who tries to order from them."
                >
                  <Textarea
                    value={form.approval_note}
                    onChange={(e) => setForm({ ...form, approval_note: e.target.value })}
                    placeholder="Two deliveries of expired stock in 2026. Suspended pending review."
                  />
                </Field>
              )}

              <div className="flex gap-2">
                <Button
                  disabled={
                    save.isPending ||
                    form.name === '' ||
                    form.code === '' ||
                    (!form.is_approved && !form.approval_note.trim())
                  }
                  onClick={submit}
                >
                  {save.isPending ? 'Saving…' : 'Save supplier'}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            </div>
          </Panel>
        )}
      </div>
    </PageShell>
  )
}
