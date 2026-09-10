'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, StatTile,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useInventoryItems, useStores } from '@/lib/inventory'
import {
  type PurchaseRequest, type SupplierInvoice,
  useApproveInvoice, useCreateRequest, useDecideRequest, useMatchInvoice,
  usePurchaseOrders, usePurchaseRequests, useRaiseOrder, useSubmitRequest,
  useSupplierInvoices, useSuppliers,
} from '@/lib/procurement'
import { fullDate, money } from '@/lib/workflow'

type Draft = { item: string; quantity: string; cost: string }

/**
 * The purchasing desk.
 *
 * Four columns of work, in the order money moves: what is being asked for,
 * what has been approved and needs ordering, what has been ordered and not
 * arrived, and what has been invoiced. Each is somebody's queue, and the
 * separations between them are the controls — the person who asks cannot
 * approve, the person who approves does not order, and whoever enters an
 * invoice does not release it for payment.
 *
 * Everything is filtered by what the signed-in user may actually do, so a
 * buyer never sees an Approve button they would only be refused for pressing.
 */
export default function PurchasingPage() {
  const { can } = useAuth()
  const requests = usePurchaseRequests()
  const orders = usePurchaseOrders()
  const invoices = useSupplierInvoices()
  const [error, setError] = useState<string | null>(null)

  const all = requests.data ?? []
  const awaitingDecision = all.filter((r) => r.status === 'submitted')
  const drafts = all.filter((r) => r.status === 'draft')
  const toOrder = all.filter(
    (r) => r.status === 'approved' || (r.status === 'submitted' && !r.needs_approval),
  )
  const outstanding = (orders.data ?? []).filter(
    (o) => o.status === 'open' || o.status === 'partially_received',
  )
  const queried = (invoices.data ?? []).filter((i) => i.status === 'queried')
  const toMatch = (invoices.data ?? []).filter((i) => i.status === 'received')

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That action could not be completed.',
      )
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Purchasing
      </div>
      <PageHeading
        title="Purchasing"
        subtitle="Ask, approve, order, receive, match. Each step belongs to somebody different — that separation is the control."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Awaiting a decision"
          value={awaitingDecision.length}
          tone={awaitingDecision.length ? 'abnormal' : 'normal'}
        />
        <StatTile label="Approved, not ordered" value={toOrder.length} tone={toOrder.length ? 'progress' : 'normal'} />
        <StatTile label="Ordered, not arrived" value={outstanding.length} tone={outstanding.length ? 'progress' : 'normal'} />
        <StatTile
          label="Invoices in query"
          value={queried.length}
          tone={queried.length ? 'critical' : 'normal'}
        />
      </div>

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
        <div className="grid gap-5">
          <RequestQueue
            title="Awaiting a decision"
            hint="An approver cannot approve their own request."
            requests={awaitingDecision}
            loading={requests.isPending}
            empty="Nothing waiting on an approver."
            canDecide={can('inventory.approve_purchase_request')}
            run={run}
          />

          {(drafts.length > 0 || can('inventory.add_purchaserequest')) && (
            <RequestQueue
              title="Drafts"
              hint="Not yet sent for a decision."
              requests={drafts}
              loading={requests.isPending}
              empty="No drafts."
              canDecide={false}
              canSubmit={can('inventory.change_purchaserequest')}
              run={run}
            />
          )}

          {can('inventory.raise_purchase_order') && (
            <ToOrder requests={toOrder} run={run} />
          )}

          {can('inventory.add_purchaserequest') && <NewRequest run={run} />}
        </div>

        <div className="grid gap-5">
          <Panel>
            <PanelHeader
              title="Orders outstanding"
              hint="A short delivery leaves the line open rather than closing it."
            />
            {orders.isPending ? (
              <div className="p-5"><LoadingNotice /></div>
            ) : outstanding.length === 0 ? (
              <div className="p-5"><EmptyState>Nothing on order.</EmptyState></div>
            ) : (
              <TableFrame minWidth={620}>
                <thead>
                  <tr>
                    <Th>Order</Th>
                    <Th>Supplier</Th>
                    <Th>Expected</Th>
                    <Th className="text-right">Outstanding</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {outstanding.map((order) => {
                    const short = order.lines.filter((l) => !l.is_complete)
                    const late =
                      order.expected_date !== null &&
                      new Date(order.expected_date) < new Date()
                    return (
                      <tr key={order.id}>
                        <Td>
                          <Link
                            href={`/purchasing/${order.id}`}
                            className="font-medium text-ink hover:text-accent"
                          >
                            {order.reference}
                          </Link>
                          <div className="text-[11px] text-ink-faint">
                            {order.store_name}
                          </div>
                        </Td>
                        <Td className="text-ink-muted">{order.supplier_name}</Td>
                        <Td>
                          {order.expected_date ? (
                            <>
                              {fullDate(order.expected_date)}
                              {late && (
                                <div className="flex items-center gap-1 text-[11px] font-semibold text-critical">
                                  <AlertIcon className="size-3" />
                                  overdue
                                </div>
                              )}
                            </>
                          ) : (
                            <span className="text-ink-faint">—</span>
                          )}
                        </Td>
                        <Td className="text-right">
                          <span className="font-semibold">{short.length}</span>
                          <span className="text-ink-faint"> of {order.lines.length}</span>
                          <div className="text-[11px] text-ink-faint">
                            {money(order.total_ordered)} ordered
                          </div>
                        </Td>
                        <Td>
                          <Link
                            href={`/purchasing/${order.id}`}
                            className="text-[12px] font-medium text-accent hover:underline"
                          >
                            {can('inventory.receive_goods') ? 'Receive' : 'Open'}
                          </Link>
                        </Td>
                      </tr>
                    )
                  })}
                </tbody>
              </TableFrame>
            )}
          </Panel>

          <Invoices
            invoices={invoices.data ?? []}
            loading={invoices.isPending}
            toMatch={toMatch}
            canMatch={can('inventory.add_supplierinvoice')}
            canApprove={can('inventory.approve_supplier_invoice')}
            run={run}
          />
        </div>
      </div>
    </PageShell>
  )
}

function RequestQueue({
  title, hint, requests, loading, empty, canDecide, canSubmit = false, run,
}: {
  title: string
  hint: string
  requests: PurchaseRequest[]
  loading: boolean
  empty: string
  canDecide: boolean
  canSubmit?: boolean
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const decide = useDecideRequest()
  const submit = useSubmitRequest()
  const [open, setOpen] = useState<number | null>(null)
  const [note, setNote] = useState('')

  return (
    <Panel>
      <PanelHeader title={title} hint={hint} />
      {loading ? (
        <div className="p-5"><LoadingNotice /></div>
      ) : requests.length === 0 ? (
        <div className="p-5"><EmptyState>{empty}</EmptyState></div>
      ) : (
        <div className="grid gap-4 p-5">
          {requests.map((record) => (
            <div
              key={record.id}
              className="rounded-lg border border-border bg-surface-sunken/40 p-4"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-ink">
                  {record.reference}
                </span>
                <span className="text-[13px] font-bold text-ink">
                  {money(record.estimated_value)}
                </span>
              </div>
              <p className="mt-0.5 text-[11.5px] text-ink-faint">
                {record.store_name} · {record.requested_by_email}
                {record.needs_approval ? ' · needs approval' : ' · below the store’s limit'}
              </p>
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
                {record.justification}
              </p>
              <ul className="mt-2 grid gap-0.5">
                {record.lines.map((line) => (
                  <li key={line.id} className="text-[12px] text-ink-muted">
                    {line.quantity} × {line.item_name}{' '}
                    <span className="text-ink-faint">
                      ({line.unit_of_issue}, est. {money(line.estimated_unit_cost)})
                    </span>
                  </li>
                ))}
              </ul>

              {canSubmit && (
                <div className="mt-3">
                  <Button
                    variant="secondary"
                    disabled={submit.isPending || record.lines.length === 0}
                    onClick={() => run(() => submit.mutateAsync(record.id))}
                  >
                    Send for a decision
                  </Button>
                  {record.lines.length === 0 && (
                    <p className="mt-1.5 text-[12px] text-ink-muted">
                      Add an item first — an approver cannot approve a blank.
                    </p>
                  )}
                </div>
              )}

              {canDecide && (
                open === record.id ? (
                  <div className="mt-3 grid gap-3">
                    <Field
                      label="Note"
                      hint="Required to reject — a rejection with no reason leaves the requester with nothing to change."
                    >
                      <Textarea
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="Approved against the monthly consumables budget."
                      />
                    </Field>
                    <div className="flex gap-2">
                      <Button
                        disabled={decide.isPending}
                        onClick={async () => {
                          await run(() =>
                            decide.mutateAsync({ id: record.id, approve: true, note }),
                          )
                          setOpen(null)
                          setNote('')
                        }}
                      >
                        Approve
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={decide.isPending || !note.trim()}
                        onClick={async () => {
                          await run(() =>
                            decide.mutateAsync({ id: record.id, approve: false, note }),
                          )
                          setOpen(null)
                          setNote('')
                        }}
                      >
                        Reject
                      </Button>
                      <Button variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
                    </div>
                  </div>
                ) : (
                  <div className="mt-3">
                    <Button variant="secondary" onClick={() => { setOpen(record.id); setNote('') }}>
                      Decide
                    </Button>
                  </div>
                )
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

/** Approved requests waiting for a supplier and agreed prices. AC-154. */
function ToOrder({
  requests, run,
}: {
  requests: PurchaseRequest[]
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const suppliers = useSuppliers(true)
  const raise = useRaiseOrder()
  const [open, setOpen] = useState<number | null>(null)
  const [supplier, setSupplier] = useState('')
  const [expected, setExpected] = useState('')
  const [prices, setPrices] = useState<Record<number, string>>({})

  const record = requests.find((r) => r.id === open) ?? null
  const priced = record?.lines.every((line) => (prices[line.item] ?? '') !== '') ?? false

  return (
    <Panel>
      <PanelHeader
        title="Approved, ready to order"
        hint="The agreed price, not the requester's estimate."
      />
      {requests.length === 0 ? (
        <div className="p-5"><EmptyState>Nothing waiting to be ordered.</EmptyState></div>
      ) : (
        <div className="grid gap-4 p-5">
          {requests.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-border bg-surface-sunken/40 p-4"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-ink">{entry.reference}</span>
                <span className="text-[12px] text-ink-muted">
                  est. {money(entry.estimated_value)}
                </span>
              </div>
              <p className="mt-0.5 text-[11.5px] text-ink-faint">
                {entry.store_name}
                {entry.decided_by_email ? ` · approved by ${entry.decided_by_email}` : ''}
              </p>

              {open === entry.id ? (
                <div className="mt-3 grid gap-3">
                  <Field label="Supplier" required>
                    <Select value={supplier} onChange={(e) => setSupplier(e.target.value)}>
                      <option value="">Choose a supplier…</option>
                      {(suppliers.data ?? []).map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name} — {s.payment_terms_days} day terms
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Expected date">
                    <Input
                      type="date"
                      value={expected}
                      onChange={(e) => setExpected(e.target.value)}
                    />
                  </Field>
                  <div className="grid gap-2.5">
                    <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                      Agreed unit prices
                    </p>
                    {entry.lines.map((line) => (
                      <Field
                        key={line.id}
                        label={`${line.item_name} — ${line.quantity} ${line.unit_of_issue}`}
                        required
                        hint={`Requester estimated ${money(line.estimated_unit_cost)}`}
                      >
                        <Input
                          type="number"
                          step="0.01"
                          min={0}
                          value={prices[line.item] ?? ''}
                          onChange={(e) =>
                            setPrices({ ...prices, [line.item]: e.target.value })
                          }
                          className="text-right"
                        />
                      </Field>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      disabled={raise.isPending || supplier === '' || !priced}
                      onClick={async () => {
                        await run(() =>
                          raise.mutateAsync({
                            request: entry.id,
                            supplier: Number(supplier),
                            expected_date: expected === '' ? null : expected,
                            note: '',
                            prices: Object.fromEntries(
                              entry.lines.map((l) => [String(l.item), prices[l.item]]),
                            ),
                          }),
                        )
                        setOpen(null)
                        setPrices({})
                        setSupplier('')
                        setExpected('')
                      }}
                    >
                      {raise.isPending ? 'Raising…' : 'Raise order'}
                    </Button>
                    <Button variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="mt-3">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setOpen(entry.id)
                      setPrices(
                        Object.fromEntries(
                          entry.lines.map((l) => [l.item, l.estimated_unit_cost]),
                        ),
                      )
                    }}
                  >
                    Raise an order
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}

function NewRequest({ run }: { run: (a: () => Promise<unknown>) => Promise<void> }) {
  const stores = useStores()
  const items = useInventoryItems()
  const create = useCreateRequest()
  const [open, setOpen] = useState(false)
  const [store, setStore] = useState('')
  const [why, setWhy] = useState('')
  const [lines, setLines] = useState<Draft[]>([{ item: '', quantity: '', cost: '' }])

  const complete =
    store !== '' &&
    why.trim() !== '' &&
    lines.some((l) => l.item !== '' && Number(l.quantity) > 0)

  const chosenStore = (stores.data ?? []).find((s) => String(s.id) === store)
  const estimate = useMemo(
    () =>
      lines.reduce(
        (total, l) => total + (Number(l.quantity) || 0) * (Number(l.cost) || 0),
        0,
      ),
    [lines],
  )
  const willNeedApproval =
    chosenStore !== undefined &&
    estimate > Number(chosenStore.adjustment_authorisation_limit)

  return (
    <Panel>
      <PanelHeader title="Ask for something" hint="Where it goes, what, and why." />
      <div className="p-5">
        {!open ? (
          <Button variant="secondary" onClick={() => setOpen(true)}>New request</Button>
        ) : (
          <div className="grid gap-4">
            <Field label="Store it lands in" required>
              <Select value={store} onChange={(e) => setStore(e.target.value)}>
                <option value="">Choose a store…</option>
                {(stores.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </Select>
            </Field>
            <Field
              label="Why it is needed"
              required
              hint="An approver cannot approve a blank."
            >
              <Textarea
                value={why}
                onChange={(e) => setWhy(e.target.value)}
                placeholder="Theatre list is heavy next week and the ward store is drawing on the main store daily."
              />
            </Field>

            <div className="grid gap-3">
              <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                Items
              </p>
              {lines.map((line, index) => (
                <div key={index} className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr]">
                  <Select
                    value={line.item}
                    onChange={(e) => {
                      const next = [...lines]
                      next[index] = { ...line, item: e.target.value }
                      setLines(next)
                    }}
                  >
                    <option value="">Choose an item…</option>
                    {(items.data ?? []).map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </Select>
                  <Input
                    type="number"
                    min={1}
                    placeholder="Qty"
                    value={line.quantity}
                    onChange={(e) => {
                      const next = [...lines]
                      next[index] = { ...line, quantity: e.target.value }
                      setLines(next)
                    }}
                    className="text-right"
                  />
                  <Input
                    type="number"
                    step="0.01"
                    min={0}
                    placeholder="Est. cost"
                    value={line.cost}
                    onChange={(e) => {
                      const next = [...lines]
                      next[index] = { ...line, cost: e.target.value }
                      setLines(next)
                    }}
                    className="text-right"
                  />
                </div>
              ))}
              <div>
                <Button
                  variant="ghost"
                  onClick={() => setLines([...lines, { item: '', quantity: '', cost: '' }])}
                >
                  Add another item
                </Button>
              </div>
            </div>

            {estimate > 0 && chosenStore && (
              <div
                className={`rounded-lg border px-3 py-2.5 text-[12px] leading-relaxed ${
                  willNeedApproval
                    ? 'border-abnormal/30 bg-abnormal-muted text-abnormal'
                    : 'border-border bg-surface-sunken/40 text-ink-muted'
                }`}
              >
                Roughly {money(estimate)}.{' '}
                {willNeedApproval
                  ? `Above ${chosenStore.name}'s limit of ${money(chosenStore.adjustment_authorisation_limit)}, so somebody else will have to approve it.`
                  : `Within ${chosenStore.name}'s limit, so it can be ordered without a decision.`}
              </div>
            )}

            <div className="flex gap-2">
              <Button
                disabled={!complete || create.isPending}
                onClick={async () => {
                  await run(() =>
                    create.mutateAsync({
                      store: Number(store),
                      justification: why,
                      lines: lines
                        .filter((l) => l.item !== '' && Number(l.quantity) > 0)
                        .map((l) => ({
                          item: Number(l.item),
                          quantity: Number(l.quantity),
                          estimated_unit_cost: l.cost === '' ? '0' : l.cost,
                        })),
                    }),
                  )
                  setOpen(false)
                  setStore('')
                  setWhy('')
                  setLines([{ item: '', quantity: '', cost: '' }])
                }}
              >
                {create.isPending ? 'Saving…' : 'Save as draft'}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

/**
 * Supplier invoices, and the three-way match.
 *
 * The discrepancies are shown in full and stay visible after approval. A
 * mismatch reaching payment because nobody saw it is the failure this screen
 * exists to prevent, so the figures are never folded into a single "approved".
 */
function Invoices({
  invoices, loading, toMatch, canMatch, canApprove, run,
}: {
  invoices: SupplierInvoice[]
  loading: boolean
  toMatch: SupplierInvoice[]
  canMatch: boolean
  canApprove: boolean
  run: (a: () => Promise<unknown>) => Promise<void>
}) {
  const match = useMatchInvoice()
  const approve = useApproveInvoice()
  const [open, setOpen] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const tone = (status: SupplierInvoice['status']) =>
    status === 'queried' ? 'critical'
      : status === 'approved' || status === 'paid' ? 'normal'
        : status === 'matched' ? 'progress' : 'idle'

  return (
    <Panel>
      <PanelHeader
        title="Supplier invoices"
        hint="Matched against what was ordered and what actually arrived."
        action={toMatch.length ? <Badge tone="abnormal">{toMatch.length} to match</Badge> : null}
      />
      {loading ? (
        <div className="p-5"><LoadingNotice /></div>
      ) : invoices.length === 0 ? (
        <div className="p-5"><EmptyState>No invoices yet.</EmptyState></div>
      ) : (
        <div className="grid gap-4 p-5">
          {invoices.map((invoice) => (
            <div
              key={invoice.id}
              className="rounded-lg border border-border bg-surface-sunken/40 p-4"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-ink">
                  {invoice.supplier_reference}
                </span>
                <Badge tone={tone(invoice.status)}>{invoice.status_display}</Badge>
              </div>
              <p className="mt-0.5 text-[11.5px] text-ink-faint">
                {invoice.supplier_name} · against {invoice.order_reference} ·{' '}
                {fullDate(invoice.invoice_date)}
              </p>

              <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px]">
                <dt className="text-ink-muted">Invoiced</dt>
                <dd className="text-right font-semibold">{money(invoice.amount)}</dd>
                {invoice.matched_value !== null && (
                  <>
                    <dt className="text-ink-muted">Actually received</dt>
                    <dd
                      className={`text-right font-semibold ${
                        invoice.matched_value !== invoice.amount ? 'text-critical' : ''
                      }`}
                    >
                      {money(invoice.matched_value)}
                    </dd>
                  </>
                )}
              </dl>

              {invoice.discrepancies.length > 0 && (
                <ul className="mt-2.5 grid gap-1 rounded-md border border-critical/30 bg-critical/5 p-2.5">
                  {invoice.discrepancies.map((problem) => (
                    <li
                      key={problem}
                      className="flex items-start gap-1.5 text-[12px] leading-relaxed text-critical"
                    >
                      <AlertIcon className="mt-0.5 size-3 shrink-0" />
                      {problem}
                    </li>
                  ))}
                </ul>
              )}

              {invoice.query_note && (
                <p className="mt-2 text-[12px] leading-relaxed text-ink-muted">
                  {invoice.query_note}
                </p>
              )}
              {invoice.approved_by_email && (
                <p className="mt-1.5 text-[11px] text-ink-faint">
                  Approved by {invoice.approved_by_email}
                </p>
              )}

              <div className="mt-3 flex gap-2">
                {invoice.status === 'received' && canMatch && (
                  <Button
                    variant="secondary"
                    disabled={match.isPending}
                    onClick={() => run(() => match.mutateAsync(invoice.id))}
                  >
                    Match it
                  </Button>
                )}
                {(invoice.status === 'matched' || invoice.status === 'queried') &&
                  canApprove && (
                    open === invoice.id ? (
                      <div className="grid w-full gap-3">
                        <Field
                          label="Note"
                          required={invoice.status === 'queried'}
                          hint={
                            invoice.status === 'queried'
                              ? 'This does not match what arrived. Say why it is being approved anyway.'
                              : 'Optional.'
                          }
                        >
                          <Textarea
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder="Short delivery agreed with the supplier; they will credit the difference."
                          />
                        </Field>
                        <div className="flex gap-2">
                          <Button
                            disabled={
                              approve.isPending ||
                              (invoice.status === 'queried' && !note.trim())
                            }
                            onClick={async () => {
                              await run(() =>
                                approve.mutateAsync({ id: invoice.id, note }),
                              )
                              setOpen(null)
                              setNote('')
                            }}
                          >
                            Approve for payment
                          </Button>
                          <Button variant="ghost" onClick={() => setOpen(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <Button
                        variant="secondary"
                        onClick={() => { setOpen(invoice.id); setNote('') }}
                      >
                        Approve for payment
                      </Button>
                    )
                  )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
