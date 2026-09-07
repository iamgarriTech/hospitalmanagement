'use client'

import { useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { usePaymentMethods } from '@/lib/billing'
import { useCreatePaymentMethod, useUpdatePaymentMethod } from '@/lib/config'

/**
 * Payment methods.
 *
 * "Needs a reference" is the field that matters: a transfer or card payment
 * without one cannot be matched to a bank statement, so the server refuses it
 * at the point of payment. Marking it here is what turns that on.
 *
 * Methods are deactivated rather than deleted — receipts already issued name
 * them.
 */
export default function PaymentMethodsPage() {
  const { can } = useAuth()
  const methods = usePaymentMethods()
  const create = useCreatePaymentMethod()
  const update = useUpdatePaymentMethod()

  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [needsReference, setNeedsReference] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const editable = can('billing.change_paymentmethod')

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await create.mutateAsync({
        name: name.trim(),
        code: code.trim().toUpperCase(),
        requires_reference: needsReference,
      })
      setName('')
      setCode('')
      setNeedsReference(false)
      setAdding(false)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not add the method.')
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Payment methods"
        subtitle="How the cash desk can take money."
        action={
          can('billing.add_paymentmethod') && (
            <Button onClick={() => setAdding((open) => !open)}>
              {adding ? 'Close' : 'Add a method'}
            </Button>
          )
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {adding && (
        <Panel className="mt-5">
          <PanelHeader title="New method" />
          <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-3">
            <Field label="Name" required>
              <Input value={name} onChange={(event) => setName(event.target.value)} required />
            </Field>
            <Field label="Code" required hint="Short, uppercase.">
              <Input value={code} onChange={(event) => setCode(event.target.value)} required />
            </Field>
            <div className="flex items-end">
              <label className="flex items-center gap-2 pb-2 text-[12.5px] text-ink">
                <input
                  type="checkbox"
                  checked={needsReference}
                  onChange={(event) => setNeedsReference(event.target.checked)}
                  className="size-4 rounded border-border"
                />
                Requires a reference
              </label>
            </div>
            <div className="sm:col-span-3">
              <Button type="submit" disabled={create.isPending || !name.trim() || !code.trim()}>
                {create.isPending ? 'Adding…' : 'Add method'}
              </Button>
            </div>
          </form>
        </Panel>
      )}

      <Panel className="mt-5">
        <PanelHeader title="Methods" />
        {methods.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : (methods.data ?? []).length === 0 ? (
          <div className="p-5">
            <EmptyState>None configured — the cash desk cannot take payment yet.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={620}>
            <thead>
              <tr>
                <Th>Method</Th>
                <Th>Code</Th>
                <Th>Reference</Th>
                <Th>Status</Th>
                {editable && <Th className="text-right">Change</Th>}
              </tr>
            </thead>
            <tbody>
              {methods.data!.map((method) => (
                <tr key={method.id}>
                  <Td className="font-medium">{method.name}</Td>
                  <Td className="font-mono text-[11.5px]">{method.code}</Td>
                  <Td>
                    {method.requires_reference ? (
                      <Badge tone="abnormal">Required</Badge>
                    ) : (
                      <span className="text-ink-faint">Not needed</span>
                    )}
                  </Td>
                  <Td>
                    {method.is_active ? (
                      <Badge tone="normal">Active</Badge>
                    ) : (
                      <Badge tone="idle">Inactive</Badge>
                    )}
                  </Td>
                  {editable && (
                    <Td className="text-right">
                      <div className="flex justify-end gap-1.5">
                        <Button
                          variant="ghost"
                          onClick={() =>
                            update.mutate({
                              id: method.id,
                              requires_reference: !method.requires_reference,
                            })
                          }
                        >
                          {method.requires_reference ? 'Reference optional' : 'Require reference'}
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => update.mutate({ id: method.id, is_active: !method.is_active })}
                        >
                          {method.is_active ? 'Deactivate' : 'Reactivate'}
                        </Button>
                      </div>
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}
