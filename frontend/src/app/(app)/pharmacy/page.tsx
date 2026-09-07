'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useDispense, useStockBatches } from '@/lib/pharmacy'
import { type PharmacyQueueRow, usePharmacyQueue, useMoveVisit } from '@/lib/queries'
import { dateAndTime, dispenseLabel, dispenseTone, timeOfDay } from '@/lib/workflow'

/**
 * The dispensing queue.
 *
 * Two things are placed where they cannot be missed. The patient's allergies
 * sit on the row — a pharmacist is the last check before a drug reaches someone.
 * And where a prescriber overrode a safety warning, that is shown with their
 * reason, because the pharmacist is the person best placed to question it.
 *
 * Batches are chosen explicitly rather than picked automatically: the batch
 * number and expiry go on the record, and an expired one is refused by the
 * server, not merely hidden here.
 */
export default function PharmacyPage() {
  const { can } = useAuth()
  const queue = usePharmacyQueue()
  const [openId, setOpenId] = useState<number | null>(null)

  const rows = queue.data ?? []
  const outstanding = rows.reduce(
    (total, row) => total + row.items.reduce((sum, item) => sum + item.outstanding, 0),
    0,
  )

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Pharmacy
      </div>
      <PageHeading
        title="Dispensing queue"
        subtitle={
          queue.isLoading
            ? 'Loading…'
            : `${rows.length} prescription${rows.length === 1 ? '' : 's'} · ${outstanding} item${
                outstanding === 1 ? '' : 's'
              } outstanding`
        }
        action={
          <div className="flex gap-2">
            {can('pharmacy.view_stockbatch') && (
              <Link
                href="/pharmacy/stock"
                className="inline-flex items-center rounded-lg border border-border px-3 py-2 text-[13px] font-medium text-ink hover:bg-surface-muted"
              >
                Stock
              </Link>
            )}
            <Button variant="secondary" onClick={() => queue.refetch()} disabled={queue.isFetching}>
              {queue.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      <div className="mt-6 grid gap-5">
        {queue.isLoading ? (
          <Panel className="p-5">
            <p role="status" className="text-[13px] text-ink-muted">Loading…</p>
          </Panel>
        ) : rows.length === 0 ? (
          <Panel className="p-5">
            <EmptyState>Nothing waiting to be dispensed.</EmptyState>
          </Panel>
        ) : (
          rows.map((row) => (
            <PrescriptionCard
              key={row.id}
              row={row}
              expanded={openId === row.id}
              onToggle={() => setOpenId(openId === row.id ? null : row.id)}
              canDispense={can('pharmacy.dispense_medication')}
            />
          ))
        )}
      </div>
    </PageShell>
  )
}

function PrescriptionCard({
  row,
  expanded,
  onToggle,
  canDispense,
}: {
  row: PharmacyQueueRow
  expanded: boolean
  onToggle: () => void
  canDispense: boolean
}) {
  const move = useMoveVisit()
  const overridden = row.items.some((item) => item.overridden_warnings.length > 0)

  return (
    <Panel className={overridden ? 'border-critical/40' : ''}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[15px] font-semibold text-ink">{row.patient_name}</h2>
            <Badge tone={dispenseTone(row.status)}>{dispenseLabel(row.status)}</Badge>
          </div>
          <p className="mt-1 text-[11.5px] text-ink-muted">
            <span className="font-mono">{row.hospital_number}</span> ·{' '}
            <span className="font-mono">{row.prescription_number}</span> ·{' '}
            {dateAndTime(row.prescribed_at)} · {row.prescribed_by}
          </p>
          {row.allergies.length > 0 && (
            <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-critical-muted px-2 py-1 text-[11.5px] font-bold text-critical">
              <AlertIcon className="size-3.5" />
              Allergic to {row.allergies.join(', ')}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={onToggle}>
          {expanded ? 'Close' : 'Dispense'}
        </Button>
      </div>

      {overridden && (
        <p className="flex items-start gap-2 border-y border-critical/25 bg-critical-muted px-5 py-2.5 text-[12px] leading-relaxed text-critical">
          <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            The prescriber overrode a safety warning on this prescription. Their reason is on
            the item below — check it before dispensing.
          </span>
        </p>
      )}

      {expanded && (
        <div className="border-t border-border">
          <ul className="divide-y divide-border">
            {row.items.map((item) => (
              <DispenseRow
                key={item.item_id}
                item={item}
                canDispense={canDispense}
                patientName={row.patient_name}
              />
            ))}
          </ul>
          {row.items.every((item) => item.outstanding === 0) && (
            <div className="border-t border-border p-5">
              <Button
                variant="secondary"
                onClick={() => move.mutate({ id: row.id, to: 'sent_for_billing' })}
              >
                Send patient to the cash desk
              </Button>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

function DispenseRow({
  item,
  canDispense,
  patientName,
}: {
  item: PharmacyQueueRow['items'][number]
  canDispense: boolean
  patientName: string
}) {
  const dispense = useDispense()
  const [batchId, setBatchId] = useState<string>('')
  const [quantity, setQuantity] = useState(String(item.outstanding))
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  // Batches for this exact presentation, matched on the medication id rather
  // than its label. Expired ones are listed too, so the pharmacist can see what
  // is actually on the shelf — the server refuses them, this screen does not
  // pretend they are absent.
  const batches = useStockBatches({ medication: item.medication_id, enabled: canDispense })
  const forThis = batches.data ?? []
  const usable = forThis.filter((batch) => !batch.is_expired && batch.quantity_on_hand > 0)
  const expired = forThis.filter((batch) => batch.is_expired)

  async function submit() {
    setError(null)
    try {
      await dispense.mutateAsync({
        itemId: item.item_id,
        batch: Number(batchId),
        quantity: Number(quantity),
      })
      setDone(`Dispensed to ${patientName}.`)
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not dispense. Nothing was issued.',
      )
    }
  }

  return (
    <li className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-ink">{item.medication}</p>
          {item.instructions && (
            <p className="mt-0.5 text-[12px] text-ink-muted">{item.instructions}</p>
          )}
          {item.overridden_warnings.length > 0 && (
            <p className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-critical-muted px-2 py-0.5 text-[11px] font-bold text-critical">
              <AlertIcon className="size-3" />
              Overridden: {item.overridden_warnings.join(', ').replace(/_/g, ' ')}
            </p>
          )}
        </div>
        <p className="shrink-0 text-[12.5px]">
          <span className="text-ink-muted">Outstanding </span>
          <span className="font-semibold text-ink">{item.outstanding}</span>
        </p>
      </div>

      {item.outstanding === 0 ? (
        <p className="mt-3 text-[12.5px] text-normal">Fully dispensed.</p>
      ) : !canDispense ? (
        <p className="mt-3 text-[12.5px] text-ink-muted">
          You do not hold the dispensing permission.
        </p>
      ) : done ? (
        <p role="status" className="mt-3 text-[12.5px] font-medium text-normal">{done}</p>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_120px_auto] sm:items-end">
          <Field label="Batch" hint={usable.length === 0 ? 'No usable stock on the shelf' : undefined}>
            <Select value={batchId} onChange={(event) => setBatchId(event.target.value)}>
              <option value="">Select a batch…</option>
              {usable.map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {batch.batch_number} · expires {batch.expiry_date} · {batch.quantity_on_hand} left
                </option>
              ))}
              {expired.map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {batch.batch_number} · EXPIRED {batch.expiry_date}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Quantity">
            <div className="relative">
              <Input
                type="number"
                min={1}
                max={item.outstanding}
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="pr-16 text-right"
              />
              <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-[11px] text-ink-faint">
                {item.dispensing_unit}
              </span>
            </div>
          </Field>
          <div>
            <Button
              onClick={submit}
              disabled={dispense.isPending || !batchId || !quantity}
              className="px-4 py-2.5"
            >
              {dispense.isPending ? 'Dispensing…' : 'Dispense'}
            </Button>
          </div>
        </div>
      )}

      {error && <div className="mt-3"><ErrorNotice>{error}</ErrorNotice></div>}
    </li>
  )
}
