'use client'

import { useMemo, useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useMedications } from '@/lib/clinical'
import { useReceiveStock, useStockBatches } from '@/lib/pharmacy'
import { money } from '@/lib/workflow'

/**
 * Stock on hand, by batch.
 *
 * Quantities are not editable here. Stock moves because something happened —
 * goods received, medication dispensed — and every change is a recorded
 * movement, so a discrepancy can be traced to an act rather than to an edit.
 *
 * Expiry is ranked ahead of quantity in the sort, because expired stock on a
 * shelf is a safety problem while a low count is a purchasing one.
 */

const DAY = 24 * 60 * 60 * 1000

export default function StockPage() {
  const { can, facility } = useAuth()
  const batches = useStockBatches({})
  const medications = useMedications('')
  const receive = useReceiveStock()

  const [filter, setFilter] = useState('all')
  const [showReceive, setShowReceive] = useState(false)

  const rows = useMemo(() => {
    const all = batches.data ?? []
    const now = Date.now()
    const withMeta = all.map((batch) => {
      const days = Math.round((new Date(batch.expiry_date).getTime() - now) / DAY)
      return { ...batch, daysToExpiry: days }
    })
    const filtered =
      filter === 'expired'
        ? withMeta.filter((batch) => batch.is_expired)
        : filter === 'expiring'
          ? withMeta.filter((batch) => !batch.is_expired && batch.daysToExpiry <= 90)
          : filter === 'empty'
            ? withMeta.filter((batch) => batch.quantity_on_hand === 0)
            : withMeta
    return filtered.sort((a, b) => a.daysToExpiry - b.daysToExpiry)
  }, [batches.data, filter])

  const expired = (batches.data ?? []).filter((batch) => batch.is_expired)
  const expiring = (batches.data ?? []).filter(
    (batch) => !batch.is_expired && (new Date(batch.expiry_date).getTime() - Date.now()) / DAY <= 90,
  )
  const value = (batches.data ?? []).reduce(
    (total, batch) => total + batch.quantity_on_hand * Number(batch.unit_cost),
    0,
  )

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Pharmacy
      </div>
      <PageHeading
        title="Stock"
        subtitle="By batch, soonest expiry first."
        action={
          can('pharmacy.add_stockbatch') && (
            <Button onClick={() => setShowReceive((open) => !open)}>
              {showReceive ? 'Close' : 'Receive stock'}
            </Button>
          )
        }
      />

      {expired.length > 0 && (
        <p className="mt-5 flex items-start gap-2 rounded-lg border border-critical/40 bg-critical-muted px-4 py-3 text-[12.5px] font-medium text-critical">
          <AlertIcon className="mt-0.5 size-4 shrink-0" />
          {expired.length} batch{expired.length === 1 ? '' : 'es'} on the shelf {expired.length === 1 ? 'has' : 'have'} expired.
          Dispensing from them is refused, but they should be removed and written off.
        </p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Batches" value={String((batches.data ?? []).length)} />
        <Tile label="Expiring within 90 days" value={String(expiring.length)} tone="abnormal" />
        <Tile label="Expired" value={String(expired.length)} tone="critical" />
        <Tile label="Stock value" value={money(value)} />
      </div>

      {showReceive && (
        <ReceiveStockForm
          medications={medications.data ?? []}
          facilityId={facility?.id ?? null}
          onDone={() => {
            setShowReceive(false)
            batches.refetch()
          }}
          receive={receive}
        />
      )}

      <Panel className="mt-5">
        <PanelHeader
          title="Batches"
          hint={`${rows.length} shown`}
          action={
            <Select
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              aria-label="Filter batches"
              className="w-auto py-1 text-[12px]"
            >
              <option value="all">All</option>
              <option value="expiring">Expiring within 90 days</option>
              <option value="expired">Expired</option>
              <option value="empty">Empty</option>
            </Select>
          }
        />
        {batches.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>No batches match.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={880}>
            <thead>
              <tr>
                <Th>Medication</Th>
                <Th>Batch</Th>
                <Th>Expiry</Th>
                <Th className="text-right">On hand</Th>
                <Th className="text-right">Unit cost</Th>
                <Th className="text-right">Value</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((batch) => (
                <tr key={batch.id} className={batch.is_expired ? 'bg-critical-muted/30' : ''}>
                  <Td className="font-medium">{batch.medication_label}</Td>
                  <Td className="font-mono text-[11.5px]">{batch.batch_number}</Td>
                  <Td>
                    {batch.is_expired ? (
                      <Badge tone="critical">
                        <AlertIcon className="size-3" />
                        Expired {batch.expiry_date}
                      </Badge>
                    ) : batch.daysToExpiry <= 90 ? (
                      <Badge tone="abnormal">
                        {batch.expiry_date} · {batch.daysToExpiry}d
                      </Badge>
                    ) : (
                      <span className="text-ink-muted">{batch.expiry_date}</span>
                    )}
                  </Td>
                  <Td
                    className={`text-right font-semibold ${
                      batch.quantity_on_hand === 0 ? 'text-ink-faint' : ''
                    }`}
                  >
                    {batch.quantity_on_hand}
                  </Td>
                  <Td className="text-right text-ink-muted">{money(batch.unit_cost)}</Td>
                  <Td className="text-right">
                    {money(batch.quantity_on_hand * Number(batch.unit_cost))}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}

function Tile({
  label,
  value,
  tone = 'idle',
}: {
  label: string
  value: string
  tone?: 'idle' | 'abnormal' | 'critical'
}) {
  const colour =
    value === '0' ? 'text-ink' : tone === 'critical' ? 'text-critical' : tone === 'abnormal' ? 'text-abnormal' : 'text-ink'
  return (
    <Panel className="px-5 py-4">
      <p className="text-[11.5px] text-ink-muted">{label}</p>
      <p className={`mt-1.5 text-[22px] leading-none font-semibold ${colour}`}>{value}</p>
    </Panel>
  )
}

function ReceiveStockForm({
  medications,
  facilityId,
  onDone,
  receive,
}: {
  medications: { id: number; label: string }[]
  facilityId: number | null
  onDone: () => void
  receive: ReturnType<typeof useReceiveStock>
}) {
  const [medication, setMedication] = useState('')
  const [batchNumber, setBatchNumber] = useState('')
  const [expiry, setExpiry] = useState('')
  const [quantity, setQuantity] = useState('')
  const [cost, setCost] = useState('')
  const [error, setError] = useState<string | null>(null)

  const expiresInPast = expiry !== '' && new Date(expiry) < new Date()

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!facilityId) return
    setError(null)
    try {
      await receive.mutateAsync({
        medication: Number(medication),
        facility: facilityId,
        batch_number: batchNumber.trim(),
        expiry_date: expiry,
        quantity_on_hand: Number(quantity),
        unit_cost: cost || '0',
      })
      onDone()
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not record the goods received.',
      )
    }
  }

  return (
    <Panel className="mt-5">
      <PanelHeader
        title="Receive stock"
        hint="Recorded as a stock movement, so the balance is always explained by something."
      />
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Field label="Medication" required>
            <Select value={medication} onChange={(event) => setMedication(event.target.value)} required>
              <option value="">Select…</option>
              {medications.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Batch number" required>
          <Input value={batchNumber} onChange={(event) => setBatchNumber(event.target.value)} required />
        </Field>
        <Field
          label="Expiry date"
          required
          error={expiresInPast ? ['This date is in the past — the batch would be unusable.'] : undefined}
        >
          <Input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} required />
        </Field>
        <Field label="Quantity" required>
          <Input
            type="number"
            min={1}
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            className="text-right"
            required
          />
        </Field>
        <Field label="Unit cost">
          <Input
            type="number"
            step="0.01"
            min={0}
            value={cost}
            onChange={(event) => setCost(event.target.value)}
            className="text-right"
          />
        </Field>
        <div className="sm:col-span-2 lg:col-span-3">
          {error && <ErrorNotice>{error}</ErrorNotice>}
          <Button
            type="submit"
            disabled={receive.isPending || !medication || !batchNumber || !expiry || !quantity}
            className="px-4 py-2.5"
          >
            {receive.isPending ? 'Recording…' : 'Record goods received'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}
