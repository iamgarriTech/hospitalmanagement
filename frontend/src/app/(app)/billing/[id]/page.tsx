'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type Receipt, fetchReceipt, newIdempotencyKey, useApplyDiscount, useCashierSessions,
  useFinaliseInvoice, useInvoice, usePaymentMethods, useRecordPayment, useRefund,
} from '@/lib/billing'
import { dateAndTime, invoiceLabel, invoiceTone, money } from '@/lib/workflow'

/**
 * One invoice: what was charged, what has been paid, what is left.
 *
 * Line items are not editable. Every charge names the clinical event that
 * produced it, so a bill can be explained rather than argued about — and
 * removing a charge would mean the event never happened.
 *
 * Once any payment on this invoice belongs to a reconciled session the whole
 * thing is frozen, and the screen says so instead of offering buttons that will
 * be refused.
 */
export default function InvoicePage() {
  const params = useParams<{ id: string }>()
  const invoiceId = Number(params.id)
  const { can, user } = useAuth()

  const invoice = useInvoice(Number.isFinite(invoiceId) ? invoiceId : null)
  const methods = usePaymentMethods()
  const sessions = useCashierSessions(can('billing.view_cashiersession'))
  const finalise = useFinaliseInvoice()
  const discount = useApplyDiscount()
  const pay = useRecordPayment()
  const refund = useRefund()

  const [error, setError] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<Receipt | null>(null)

  const record = invoice.data
  const openSession = (sessions.data ?? []).find(
    (session) => session.status === 'open' && session.cashier === user?.id,
  )

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That action could not be completed.')
    }
  }

  if (invoice.isLoading) {
    return (
      <PageShell>
        <p role="status" className="py-10 text-[13px] text-ink-muted">Loading the invoice…</p>
      </PageShell>
    )
  }
  if (invoice.isError || !record) {
    return (
      <PageShell>
        <Panel className="p-5">
          <p role="alert" className="text-[13px] text-ink-muted">
            This invoice is not available to you.
          </p>
          <Link href="/billing" className="mt-3 inline-block text-[13px] font-semibold text-accent">
            Back to the cash desk
          </Link>
        </Panel>
      </PageShell>
    )
  }

  const balance = Number(record.balance)

  return (
    <PageShell>
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
          Invoice
        </span>
        <Link href="/billing" className="text-[12px] font-semibold text-accent hover:underline">
          Back to the cash desk
        </Link>
      </div>

      {error && <ErrorNotice>{error}</ErrorNotice>}

      {record.is_frozen && (
        <p className="mb-4 flex items-start gap-2 rounded-lg border border-border bg-surface-sunken px-4 py-3 text-[12.5px] font-medium text-ink-muted">
          <AlertIcon className="mt-0.5 size-4 shrink-0" />
          This invoice includes payments from a reconciled cashier session and is frozen. Any
          correction has to be a new adjusting entry.
        </p>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[1.4fr_1fr]">
        <div className="grid gap-5">
          <Panel>
            <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
              <div>
                <p className="font-mono text-[15px] font-bold text-ink">{record.invoice_number}</p>
                <p className="mt-1 text-[12.5px] text-ink-muted">
                  <Link
                    href={`/patients/${record.patient}`}
                    className="font-semibold text-accent hover:underline"
                  >
                    {record.patient_name}
                  </Link>
                  <span className="ml-2 font-mono text-[11.5px]">{record.hospital_number}</span>
                </p>
                <p className="mt-0.5 text-[11.5px] text-ink-faint">
                  Raised {dateAndTime(record.created_at)}
                </p>
              </div>
              <Badge tone={invoiceTone(record.status)}>{invoiceLabel(record.status)}</Badge>
            </div>

            <TableFrame minWidth={620}>
              <thead>
                <tr>
                  <Th>Charge</Th>
                  <Th>From</Th>
                  <Th className="text-right">Qty</Th>
                  <Th className="text-right">Unit</Th>
                  <Th className="text-right">Amount</Th>
                </tr>
              </thead>
              <tbody>
                {record.items.length === 0 && (
                  <tr>
                    <Td className="text-ink-faint" >Nothing charged yet.</Td>
                    <Td /><Td /><Td /><Td />
                  </tr>
                )}
                {record.items.map((item) => (
                  <tr key={item.id} className={item.is_cancelled ? 'opacity-50' : ''}>
                    <Td className={item.is_cancelled ? 'line-through' : ''}>{item.description}</Td>
                    <Td className="text-[11px] text-ink-faint">
                      {/* Where the charge came from, so it can be explained. */}
                      {item.source_type.split('.').pop() ?? '—'}
                    </Td>
                    <Td className="text-right">{item.quantity}</Td>
                    <Td className="text-right text-ink-muted">{money(item.unit_price)}</Td>
                    <Td className="text-right font-semibold">{money(item.amount)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border px-5 py-4 text-[13px]">
              <dt className="text-ink-muted">Subtotal</dt>
              <dd className="text-right">{money(record.subtotal)}</dd>
              {Number(record.discount_amount) > 0 && (
                <>
                  <dt className="text-ink-muted">
                    Discount
                    {record.discount_reason && (
                      <span className="block text-[11px] text-ink-faint">
                        {record.discount_reason}
                      </span>
                    )}
                  </dt>
                  <dd className="text-right text-normal">−{money(record.discount_amount)}</dd>
                </>
              )}
              {Number(record.tax_amount) > 0 && (
                <>
                  <dt className="text-ink-muted">Tax</dt>
                  <dd className="text-right">{money(record.tax_amount)}</dd>
                </>
              )}
              <dt className="border-t border-border pt-2 font-semibold text-ink">Total</dt>
              <dd className="border-t border-border pt-2 text-right text-[15px] font-bold text-ink">
                {money(record.total)}
              </dd>
              <dt className="text-ink-muted">Paid</dt>
              <dd className="text-right">{money(record.amount_paid)}</dd>
              {Number(record.amount_refunded) > 0 && (
                <>
                  <dt className="text-ink-muted">Refunded</dt>
                  <dd className="text-right text-critical">{money(record.amount_refunded)}</dd>
                </>
              )}
              <dt className="border-t border-border pt-2 font-semibold text-ink">Balance</dt>
              <dd
                className={`border-t border-border pt-2 text-right text-[16px] font-bold ${
                  balance > 0 ? 'text-abnormal' : 'text-normal'
                }`}
              >
                {money(record.balance)}
              </dd>
            </dl>

            {record.status === 'draft' && !record.is_frozen && can('billing.change_invoice') && (
              <div className="border-t border-border p-5">
                <p className="mb-3 text-[12.5px] text-ink-muted">
                  This bill is still a draft — charges may still be added as the visit
                  continues. Finalising stops that.
                </p>
                <Button
                  disabled={finalise.isPending || record.items.length === 0}
                  onClick={() => run(() => finalise.mutateAsync(record.id))}
                >
                  {finalise.isPending ? 'Finalising…' : 'Finalise invoice'}
                </Button>
              </div>
            )}
          </Panel>

          {record.payments.length > 0 && (
            <Panel>
              <PanelHeader title="Payments" />
              <ul className="divide-y divide-border">
                {record.payments.map((payment) => (
                  <li key={payment.id} className="flex flex-wrap items-start justify-between gap-3 p-5">
                    <div className="min-w-0">
                      <p className="font-mono text-[12.5px] font-semibold text-ink">
                        {payment.receipt_number}
                      </p>
                      <p className="mt-0.5 text-[12px] text-ink-muted">
                        {money(payment.amount)} · {payment.method_name}
                        {payment.reference && ` · ${payment.reference}`}
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-faint">
                        {dateAndTime(payment.received_at)} · {payment.received_by_email}
                        {payment.reprint_count > 0 &&
                          ` · reprinted ${payment.reprint_count}×`}
                      </p>
                      {payment.refunds.map((entry) => (
                        <p key={entry.id} className="mt-1 text-[11.5px] font-medium text-critical">
                          Refunded {money(entry.amount)} ({entry.reference}) — {entry.reason}
                        </p>
                      ))}
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-1.5">
                      <Button
                        variant="secondary"
                        onClick={() =>
                          run(async () => setReceipt(await fetchReceipt(payment.id, false)))
                        }
                      >
                        Receipt
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() =>
                          run(async () => setReceipt(await fetchReceipt(payment.id, true)))
                        }
                      >
                        Reprint
                      </Button>
                      {can('billing.issue_refund') && !record.is_frozen &&
                        Number(payment.amount) - Number(payment.amount_refunded) > 0 && (
                          <RefundControl
                            paymentId={payment.id}
                            refundable={
                              Number(payment.amount) - Number(payment.amount_refunded)
                            }
                            refund={refund}
                            onError={setError}
                          />
                        )}
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="grid gap-5">
          {balance > 0 && !record.is_frozen && can('billing.add_payment') && (
            <TakePayment
              invoiceId={record.id}
              balance={balance}
              methods={methods.data ?? []}
              hasSession={Boolean(openSession)}
              pay={pay}
              onError={setError}
              onPaid={async (paymentId) => setReceipt(await fetchReceipt(paymentId, false))}
            />
          )}

          {!record.is_frozen && can('billing.change_invoice') && (
            <DiscountPanel
              invoiceId={record.id}
              subtotal={Number(record.subtotal)}
              current={record.discount_amount}
              discount={discount}
              onError={setError}
            />
          )}

          {receipt && <ReceiptPanel receipt={receipt} onClose={() => setReceipt(null)} />}
        </div>
      </div>
    </PageShell>
  )
}

function TakePayment({
  invoiceId,
  balance,
  methods,
  hasSession,
  pay,
  onError,
  onPaid,
}: {
  invoiceId: number
  balance: number
  methods: { id: number; name: string; requires_reference: boolean }[]
  hasSession: boolean
  pay: ReturnType<typeof useRecordPayment>
  onError: (message: string | null) => void
  onPaid: (paymentId: number) => void
}) {
  const [methodId, setMethodId] = useState('')
  const [amount, setAmount] = useState(balance.toFixed(2))
  const [reference, setReference] = useState('')
  // One key per attempt: a retry after a dropped response must return the same
  // receipt rather than take the money a second time.
  const [key, setKey] = useState(newIdempotencyKey)

  useEffect(() => setAmount(balance.toFixed(2)), [balance])

  const method = methods.find((entry) => String(entry.id) === methodId)
  const needsReference = method?.requires_reference ?? false
  const tooMuch = Number(amount) > balance

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    onError(null)
    try {
      const payment = await pay.mutateAsync({
        invoice: invoiceId,
        method: Number(methodId),
        amount,
        reference,
        idempotency_key: key,
      })
      setKey(newIdempotencyKey())
      setReference('')
      onPaid(payment.id)
    } catch (caught) {
      onError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not reach the hospital server. Check whether the payment was taken before retrying.',
      )
    }
  }

  return (
    <Panel>
      <PanelHeader title="Take payment" hint={`${money(balance)} outstanding`} />
      {!hasSession ? (
        <div className="p-5">
          <p className="text-[12.5px] leading-relaxed text-abnormal">
            You have no open till. Payments have to land in a cashier session so the day can
            be reconciled.
          </p>
          <Link
            href="/billing/till"
            className="mt-3 inline-flex items-center rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white hover:bg-accent-hover"
          >
            Open a till
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-4 p-5">
          <Field label="Method" required>
            <Select value={methodId} onChange={(event) => setMethodId(event.target.value)} required>
              <option value="">Select…</option>
              {methods.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Amount"
            required
            error={tooMuch ? [`More than the ${money(balance)} outstanding.`] : undefined}
          >
            <Input
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="text-right"
              required
            />
          </Field>
          {needsReference && (
            <Field label="Reference" required hint={`${method?.name} payments need a reference.`}>
              <Input value={reference} onChange={(event) => setReference(event.target.value)} required />
            </Field>
          )}
          <div>
            <Button
              type="submit"
              disabled={pay.isPending || !methodId || tooMuch || (needsReference && !reference)}
              className="px-4 py-2.5"
            >
              {pay.isPending ? 'Recording…' : `Take ${money(Number(amount) || 0)}`}
            </Button>
            {Number(amount) < balance && Number(amount) > 0 && (
              <p className="mt-2 text-[11.5px] text-ink-muted">
                Part payment — {money(balance - Number(amount))} will remain outstanding.
              </p>
            )}
          </div>
        </form>
      )}
    </Panel>
  )
}

function DiscountPanel({
  invoiceId,
  subtotal,
  current,
  discount,
  onError,
}: {
  invoiceId: number
  subtotal: number
  current: string
  discount: ReturnType<typeof useApplyDiscount>
  onError: (message: string | null) => void
}) {
  const [amount, setAmount] = useState(current)
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    onError(null)
    try {
      await discount.mutateAsync({ id: invoiceId, amount, reason: reason.trim() })
      setOpen(false)
      setReason('')
    } catch (caught) {
      // A refusal here is a limit, not a failure — the message names the limit
      // and who can approve beyond it.
      onError(caught instanceof ApiError ? caught.message : 'Could not apply the discount.')
    }
  }

  if (!open) {
    return (
      <Panel className="p-5">
        <Button variant="secondary" onClick={() => setOpen(true)}>
          {Number(current) > 0 ? 'Change discount' : 'Apply a discount'}
        </Button>
      </Panel>
    )
  }

  return (
    <Panel>
      <PanelHeader
        title="Discount"
        hint="Beyond your own limit this needs approval from someone who holds it."
      />
      <form onSubmit={submit} className="grid gap-4 p-5">
        <Field
          label="Amount"
          required
          error={Number(amount) > subtotal ? ['A discount cannot exceed the subtotal.'] : undefined}
        >
          <Input
            type="number"
            step="0.01"
            min="0"
            max={subtotal}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="text-right"
            autoFocus
            required
          />
        </Field>
        <Field label="Reason" required>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Approved by the medical social worker"
            required
          />
        </Field>
        <div className="flex gap-2">
          <Button
            type="submit"
            disabled={discount.isPending || !reason.trim() || Number(amount) > subtotal}
          >
            {discount.isPending ? 'Applying…' : 'Apply discount'}
          </Button>
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </form>
    </Panel>
  )
}

function RefundControl({
  paymentId,
  refundable,
  refund,
  onError,
}: {
  paymentId: number
  refundable: number
  refund: ReturnType<typeof useRefund>
  onError: (message: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState(refundable.toFixed(2))
  const [reason, setReason] = useState('')

  if (!open) {
    return (
      <Button variant="danger" onClick={() => setOpen(true)}>
        Refund
      </Button>
    )
  }

  return (
    <div className="grid w-56 gap-2">
      <Input
        type="number"
        step="0.01"
        max={refundable}
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        className="text-right"
        aria-label="Refund amount"
      />
      <Input
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Reason (required)"
        aria-label="Refund reason"
      />
      <div className="flex gap-1.5">
        <Button
          variant="danger"
          disabled={!reason.trim() || refund.isPending}
          onClick={async () => {
            onError(null)
            try {
              await refund.mutateAsync({ id: paymentId, amount, reason: reason.trim() })
              setOpen(false)
            } catch (caught) {
              onError(caught instanceof ApiError ? caught.message : 'Could not issue the refund.')
            }
          }}
        >
          Refund
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

/** A reprint is identical to the original, and is marked as a reprint. */
function ReceiptPanel({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  return (
    <Panel>
      <PanelHeader
        title="Receipt"
        action={
          <div className="flex gap-1.5 no-print">
            <Button variant="secondary" onClick={() => window.print()}>Print</Button>
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        }
      />
      <div className="p-5 text-[12.5px]">
        {receipt.is_reprint && (
          <p className="mb-3 text-center text-[11px] font-bold tracking-[0.12em] text-abnormal uppercase">
            Reprint
          </p>
        )}
        <p className="text-center text-[14px] font-bold text-ink">{receipt.facility}</p>
        <p className="mt-0.5 text-center font-mono text-[11.5px] text-ink-muted">
          {receipt.receipt_number}
        </p>
        <p className="text-center text-[11px] text-ink-faint">{dateAndTime(receipt.issued_at)}</p>

        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          <dt className="text-ink-muted">Patient</dt>
          <dd className="text-right font-semibold">{receipt.patient_name}</dd>
          <dt className="text-ink-muted">Hospital number</dt>
          <dd className="text-right font-mono text-[11.5px]">{receipt.hospital_number}</dd>
          <dt className="text-ink-muted">Invoice</dt>
          <dd className="text-right font-mono text-[11.5px]">{receipt.invoice_number}</dd>
        </dl>

        <ul className="mt-4 border-t border-border pt-3">
          {receipt.items.map((item, index) => (
            <li key={index} className="flex justify-between gap-3 py-0.5">
              <span className="min-w-0">
                {item.description}
                {item.quantity > 1 && <span className="text-ink-faint"> ×{item.quantity}</span>}
              </span>
              <span className="shrink-0">{money(item.amount)}</span>
            </li>
          ))}
        </ul>

        <dl className="mt-3 grid grid-cols-2 gap-y-1 border-t border-border pt-3">
          <dt className="text-ink-muted">Subtotal</dt>
          <dd className="text-right">{money(receipt.subtotal)}</dd>
          {Number(receipt.discount) > 0 && (
            <>
              <dt className="text-ink-muted">Discount</dt>
              <dd className="text-right">−{money(receipt.discount)}</dd>
            </>
          )}
          <dt className="font-semibold text-ink">Total</dt>
          <dd className="text-right font-bold">{money(receipt.total)}</dd>
          <dt className="text-ink-muted">Paid ({receipt.method})</dt>
          <dd className="text-right font-semibold">{money(receipt.amount_paid)}</dd>
          <dt className="text-ink-muted">Balance</dt>
          <dd className="text-right">{money(receipt.balance_after)}</dd>
        </dl>

        <p className="mt-4 text-center text-[11px] text-ink-faint">
          Received by {receipt.received_by}
        </p>
      </div>
    </Panel>
  )
}
