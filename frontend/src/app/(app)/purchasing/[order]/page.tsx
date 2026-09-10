'use client'

import { use, useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  useCancelOrder, useGoodsReceipts, usePurchaseOrders, useReceiveGoods,
  useRecordInvoice,
} from '@/lib/procurement'
import { dateAndTime, fullDate, money } from '@/lib/workflow'

type LineDraft = { quantity: string; lot: string; expiry: string }

/**
 * One purchase order: what was ordered, what has arrived, and what is still
 * owed.
 *
 * Receiving is per line, with a batch number and an expiry, because a delivery
 * is rarely the whole order and the expiry belongs to the delivery rather than
 * to the item. Booking a line in creates the stock movement that puts it on
 * the shelf — the two are one act, so there is no way to record a delivery
 * here that never reaches a store.
 */
export default function PurchaseOrderPage({
  params,
}: {
  params: Promise<{ order: string }>
}) {
  const { order: orderParam } = use(params)
  const orderId = Number(orderParam)
  const { can } = useAuth()

  const orders = usePurchaseOrders()
  const receipts = useGoodsReceipts(orderId)
  const receive = useReceiveGoods()
  const cancel = useCancelOrder()
  const recordInvoice = useRecordInvoice()

  const [drafts, setDrafts] = useState<Record<number, LineDraft>>({})
  const [deliveryNote, setDeliveryNote] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [invoicing, setInvoicing] = useState(false)
  const [invoiceRef, setInvoiceRef] = useState('')
  const [invoiceAmount, setInvoiceAmount] = useState('')

  const order = (orders.data ?? []).find((o) => o.id === orderId)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      return true
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That action could not be completed.',
      )
      return false
    }
  }

  if (orders.isPending) return <PageShell><LoadingNotice /></PageShell>
  if (!order) {
    return (
      <PageShell>
        <ErrorNotice>No such order, or not one you have access to.</ErrorNotice>
      </PageShell>
    )
  }

  const outstanding = order.lines.filter((line) => !line.is_complete)
  const filled = outstanding.filter(
    (line) => Number(drafts[line.id]?.quantity ?? 0) > 0,
  )
  const readyToReceive =
    filled.length > 0 &&
    filled.every((line) => {
      const draft = drafts[line.id]
      const quantity = Number(draft.quantity)
      if (quantity <= 0 || quantity > line.outstanding) return false
      return !line.tracks_expiry || draft.expiry !== ''
    })

  const tone =
    order.status === 'received' ? 'normal'
      : order.status === 'cancelled' ? 'idle'
        : order.status === 'partially_received' ? 'progress' : 'abnormal'

  return (
    <PageShell>
      <Link
        href="/purchasing"
        className="mb-3 inline-block text-[12px] font-medium text-ink-muted hover:text-accent"
      >
        ← Purchasing
      </Link>
      <PageHeading
        title={order.reference}
        subtitle={
          `${order.supplier_name}, into ${order.store_name}. Raised from ` +
          `${order.request_reference} by ${order.raised_by_email}.`
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.3fr_1fr]">
        <Panel>
          <PanelHeader
            title="Ordered"
            hint={
              order.expected_date
                ? `Expected ${fullDate(order.expected_date)}`
                : 'No expected date given'
            }
            action={<Badge tone={tone}>{order.status_display}</Badge>}
          />
          <TableFrame minWidth={620}>
            <thead>
              <tr>
                <Th>Item</Th>
                <Th className="text-right">Ordered</Th>
                <Th className="text-right">Received</Th>
                <Th className="text-right">Outstanding</Th>
                <Th className="text-right">Unit</Th>
              </tr>
            </thead>
            <tbody>
              {order.lines.map((line) => (
                <tr key={line.id}>
                  <Td>
                    <span className="font-medium text-ink">{line.item_name}</span>
                    <div className="text-[11px] text-ink-faint">
                      {line.item_code} · {line.unit_of_issue}
                    </div>
                  </Td>
                  <Td className="text-right">{line.quantity_ordered}</Td>
                  <Td className="text-right">{line.quantity_received}</Td>
                  <Td className="text-right">
                    {line.is_complete ? (
                      <span className="font-medium text-normal">complete</span>
                    ) : (
                      <span className="font-semibold text-critical">{line.outstanding}</span>
                    )}
                  </Td>
                  <Td className="text-right text-ink-muted">{money(line.unit_cost)}</Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border p-5 text-[13px]">
            <dt className="text-ink-muted">Ordered</dt>
            <dd className="text-right font-semibold">{money(order.total_ordered)}</dd>
            <dt className="text-ink-muted">Received, at ordered prices</dt>
            <dd className="text-right font-semibold">
              {money(order.total_received_value)}
            </dd>
          </dl>

          {order.cancellation_reason && (
            <p className="border-t border-border p-5 text-[12.5px] leading-relaxed text-ink-muted">
              Cancelled: {order.cancellation_reason}
            </p>
          )}
        </Panel>

        <div className="grid gap-5">
          {outstanding.length > 0 && can('inventory.receive_goods') && (
            <Panel>
              <PanelHeader
                title="Book a delivery in"
                hint="Booking a line in puts it on the shelf. The two are one act."
              />
              <div className="grid gap-4 p-5">
                <p className="text-[12.5px] leading-relaxed text-ink-muted">
                  Leave a line blank if it did not come. A short delivery keeps the line
                  open so somebody carries on chasing it.
                </p>

                {outstanding.map((line) => {
                  const draft = drafts[line.id] ?? { quantity: '', lot: '', expiry: '' }
                  const tooMany = Number(draft.quantity) > line.outstanding
                  return (
                    <div
                      key={line.id}
                      className="rounded-lg border border-border bg-surface-sunken/40 p-4"
                    >
                      <div className="mb-3 flex items-baseline justify-between gap-3">
                        <span className="text-[13px] font-semibold text-ink">
                          {line.item_name}
                        </span>
                        <span className="text-[12px] text-ink-muted">
                          {line.outstanding} {line.unit_of_issue} outstanding
                        </span>
                      </div>
                      <div className="grid gap-3">
                        <Field label="Quantity arrived">
                          <Input
                            type="number"
                            min={0}
                            max={line.outstanding}
                            value={draft.quantity}
                            onChange={(e) =>
                              setDrafts({
                                ...drafts,
                                [line.id]: { ...draft, quantity: e.target.value },
                              })
                            }
                            className="text-right"
                          />
                        </Field>
                        {tooMany && (
                          <p className="flex items-start gap-1.5 text-[12px] font-medium text-critical">
                            <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
                            Only {line.outstanding} is outstanding. An over-delivery
                            changes what the hospital owes and needs a decision, not a
                            quiet acceptance.
                          </p>
                        )}
                        {Number(draft.quantity) > 0 && (
                          <>
                            <Field
                              label="Batch or lot number"
                              hint="The supplier's, so it can be traced back."
                            >
                              <Input
                                value={draft.lot}
                                maxLength={60}
                                onChange={(e) =>
                                  setDrafts({
                                    ...drafts,
                                    [line.id]: { ...draft, lot: e.target.value },
                                  })
                                }
                              />
                            </Field>
                            {line.tracks_expiry ? (
                              <Field label="Expiry date" required>
                                <Input
                                  type="date"
                                  value={draft.expiry}
                                  onChange={(e) =>
                                    setDrafts({
                                      ...drafts,
                                      [line.id]: { ...draft, expiry: e.target.value },
                                    })
                                  }
                                />
                              </Field>
                            ) : (
                              <p className="text-[12px] text-ink-muted">
                                {line.item_name} is not tracked by expiry date.
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}

                <Field label="Delivery note number">
                  <Input
                    value={deliveryNote}
                    maxLength={60}
                    onChange={(e) => setDeliveryNote(e.target.value)}
                  />
                </Field>
                <Field label="Note" hint="Optional.">
                  <Textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Balance to follow; driver said Thursday."
                  />
                </Field>

                <div>
                  <Button
                    disabled={!readyToReceive || receive.isPending}
                    onClick={async () => {
                      const ok = await run(() =>
                        receive.mutateAsync({
                          order: order.id,
                          deliveries: filled.map((line) => ({
                            order_line: line.id,
                            quantity: Number(drafts[line.id].quantity),
                            lot_number: drafts[line.id].lot,
                            expiry_date: line.tracks_expiry
                              ? drafts[line.id].expiry
                              : null,
                          })),
                          delivery_note: deliveryNote,
                          note,
                        }),
                      )
                      if (ok) {
                        setDrafts({})
                        setDeliveryNote('')
                        setNote('')
                      }
                    }}
                    className="px-4 py-2.5"
                  >
                    {receive.isPending ? 'Booking in…' : 'Book delivery in'}
                  </Button>
                </div>
              </div>
            </Panel>
          )}

          <Panel>
            <PanelHeader title="Deliveries" hint="Each line names the movement that shelved it." />
            {receipts.isPending ? (
              <div className="p-5"><LoadingNotice /></div>
            ) : (receipts.data ?? []).length === 0 ? (
              <div className="p-5"><EmptyState>Nothing has arrived yet.</EmptyState></div>
            ) : (
              <div className="grid gap-3 p-5">
                {(receipts.data ?? []).map((receipt) => (
                  <div
                    key={receipt.id}
                    className="rounded-lg border border-border bg-surface-sunken/40 p-4"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[13px] font-semibold text-ink">
                        {receipt.reference}
                      </span>
                      <span className="text-[13px] font-semibold">
                        {money(receipt.total_value)}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[11.5px] text-ink-faint">
                      {receipt.delivery_note && `${receipt.delivery_note} · `}
                      {receipt.received_by_email} · {dateAndTime(receipt.received_at)}
                    </p>
                    <ul className="mt-2 grid gap-0.5">
                      {receipt.lines.map((line) => (
                        <li key={line.id} className="text-[12px] text-ink-muted">
                          {line.quantity} × {line.item_name}
                          <span className="text-ink-faint">
                            {' '}· lot {line.lot_number}
                            {line.expiry_date && `, exp ${fullDate(line.expiry_date)}`}
                            {' '}· shelf balance {line.movement_balance}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {receipt.note && (
                      <p className="mt-1.5 text-[12px] leading-relaxed text-ink-muted">
                        {receipt.note}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {can('inventory.add_supplierinvoice') && order.status !== 'cancelled' && (
            <Panel>
              <PanelHeader
                title="Record the supplier's invoice"
                hint="It is matched against what arrived, not paid on trust."
              />
              <div className="p-5">
                {!invoicing ? (
                  <Button variant="secondary" onClick={() => setInvoicing(true)}>
                    Record an invoice
                  </Button>
                ) : (
                  <div className="grid gap-4">
                    <Field label="Their invoice number" required>
                      <Input
                        value={invoiceRef}
                        maxLength={60}
                        onChange={(e) => setInvoiceRef(e.target.value)}
                      />
                    </Field>
                    <Field label="Amount" required>
                      <Input
                        type="number"
                        step="0.01"
                        min={0}
                        value={invoiceAmount}
                        onChange={(e) => setInvoiceAmount(e.target.value)}
                        className="text-right"
                      />
                    </Field>
                    <div className="flex gap-2">
                      <Button
                        disabled={
                          recordInvoice.isPending ||
                          invoiceRef === '' ||
                          invoiceAmount === ''
                        }
                        onClick={async () => {
                          const ok = await run(() =>
                            recordInvoice.mutateAsync({
                              order: order.id,
                              supplier_reference: invoiceRef,
                              invoice_date: new Date().toISOString().slice(0, 10),
                              amount: invoiceAmount,
                            }),
                          )
                          if (ok) {
                            setInvoicing(false)
                            setInvoiceRef('')
                            setInvoiceAmount('')
                          }
                        }}
                      >
                        Record it
                      </Button>
                      <Button variant="ghost" onClick={() => setInvoicing(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Panel>
          )}

          {order.status === 'open' &&
            (receipts.data ?? []).length === 0 &&
            can('inventory.raise_purchase_order') && (
              <Panel>
                <PanelHeader
                  title="Cancel this order"
                  hint="Only while nothing has arrived against it."
                />
                <div className="p-5">
                  {!cancelling ? (
                    <Button variant="secondary" onClick={() => setCancelling(true)}>
                      Cancel order
                    </Button>
                  ) : (
                    <div className="grid gap-4">
                      <Field label="Why" required>
                        <Input
                          value={cancelReason}
                          maxLength={255}
                          onChange={(e) => setCancelReason(e.target.value)}
                          placeholder="Supplier out of stock."
                        />
                      </Field>
                      <div className="flex gap-2">
                        <Button
                          disabled={cancel.isPending || !cancelReason.trim()}
                          onClick={async () => {
                            const ok = await run(() =>
                              cancel.mutateAsync({ id: order.id, reason: cancelReason }),
                            )
                            if (ok) setCancelling(false)
                          }}
                        >
                          Cancel the order
                        </Button>
                        <Button variant="ghost" onClick={() => setCancelling(false)}>
                          Keep it
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </Panel>
            )}
        </div>
      </div>
    </PageShell>
  )
}
