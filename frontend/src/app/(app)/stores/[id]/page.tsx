'use client'

import { use, useMemo, useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type StockAdjustment, type StockRecord,
  useAdjustStock, useInventoryItems, useIssueStock, useReceiveStock,
  useStockMovements, useStockRecordCreate, useStockRecords, useStores,
  useTransferStock,
} from '@/lib/inventory'
import { useStaff } from '@/lib/config'
import { dateAndTime, fullDate, money } from '@/lib/workflow'

/**
 * One store: what it holds, and the four acts that change it.
 *
 * Receiving and issuing are actions rather than an editable quantity. A
 * writable number on this screen would be a read-then-write from the browser
 * — two storekeepers issuing the last box would both succeed — and it would
 * leave a balance nobody could trace back to an act.
 *
 * Lots are shown rather than a single total per item, because the expiry date
 * belongs to a delivery. "40 boxes of gloves" is not the same information as
 * "25 expiring next month and 15 next year", and only the second lets somebody
 * decide what to do.
 */
export default function StorePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const storeId = Number(id)
  const { can, user } = useAuth()

  const stores = useStores()
  const records = useStockRecords(storeId)
  const items = useInventoryItems(can('inventory.add_stockrecord'))

  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const store = (stores.data ?? []).find((entry) => entry.id === storeId)
  const rows = records.data ?? []
  const record = rows.find((entry) => entry.id === selected) ?? null

  const lowCount = rows.filter((entry) => entry.is_low).length

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

  if (stores.isPending || records.isPending) {
    return <PageShell><LoadingNotice /></PageShell>
  }
  if (!store) {
    return (
      <PageShell>
        <ErrorNotice>No such store, or not one you have access to.</ErrorNotice>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <Link
        href="/stores"
        className="mb-3 inline-block text-[12px] font-medium text-ink-muted hover:text-accent"
      >
        ← All stores
      </Link>
      <PageHeading
        title={store.name}
        subtitle={
          `${store.kind_display} at ${store.facility_name}. ` +
          `Adjustments above ${money(store.adjustment_authorisation_limit)} need a ` +
          `second signature; expiry warnings start ${store.expiry_horizon_days} days out.`
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Panel>
          <PanelHeader
            title="Stock on hand"
            hint={`${rows.length} lines carried`}
            action={
              lowCount > 0 ? (
                <Badge tone="critical">{lowCount} below level</Badge>
              ) : (
                <Badge tone="normal">all above level</Badge>
              )
            }
          />
          {rows.length === 0 ? (
            <div className="p-5">
              <EmptyState>This store does not carry anything yet.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={620}>
              <thead>
                <tr>
                  <Th>Item</Th>
                  <Th className="text-right">In date</Th>
                  <Th className="text-right">Level</Th>
                  <Th>Lots</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.id} className={entry.id === selected ? 'bg-accent/5' : ''}>
                    <Td>
                      <span className="font-medium text-ink">{entry.item_name}</span>
                      <div className="text-[11px] text-ink-faint">
                        {entry.item_code} · {entry.unit_of_issue}
                        {entry.is_controlled && ' · controlled'}
                      </div>
                    </Td>
                    <Td className="text-right">
                      <span
                        className={`font-semibold ${
                          entry.is_low ? 'text-critical' : 'text-ink'
                        }`}
                      >
                        {entry.usable_on_hand}
                      </span>
                      {entry.on_hand !== entry.usable_on_hand && (
                        <div className="text-[11px] text-ink-faint">
                          {entry.on_hand} on shelf
                        </div>
                      )}
                    </Td>
                    <Td className="text-right text-ink-muted">{entry.reorder_level}</Td>
                    <Td>
                      {entry.lots.length === 0 ? (
                        <span className="text-ink-faint">—</span>
                      ) : (
                        <div className="grid gap-0.5">
                          {entry.lots
                            .filter((lot) => lot.quantity_on_hand > 0)
                            .map((lot) => (
                              <span
                                key={lot.id}
                                className={`text-[11.5px] ${
                                  lot.is_expired ? 'text-critical' : 'text-ink-muted'
                                }`}
                              >
                                {lot.quantity_on_hand} × {lot.lot_number}
                                {lot.expiry_date && (
                                  <> · {lot.is_expired ? 'expired' : 'exp'}{' '}
                                    {fullDate(lot.expiry_date)}</>
                                )}
                              </span>
                            ))}
                        </div>
                      )}
                    </Td>
                    <Td>
                      <button
                        type="button"
                        onClick={() => setSelected(entry.id === selected ? null : entry.id)}
                        className="text-[12px] font-medium text-accent hover:underline"
                      >
                        {entry.id === selected ? 'Close' : 'Open'}
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <div className="grid gap-5">
          {record ? (
            <RecordActions
              record={record}
              storeLimit={store.adjustment_authorisation_limit}
              actorId={user?.id ?? null}
              onError={setError}
              run={run}
            />
          ) : (
            <Panel>
              <PanelHeader title="Movements" hint="Open a line to receive, issue or adjust." />
              <div className="p-5">
                <EmptyState>
                  Choose a line on the left to see its ledger and act on it.
                </EmptyState>
              </div>
            </Panel>
          )}

          {can('inventory.add_stockrecord') && (
            <AddLine
              storeId={storeId}
              carried={new Set(rows.map((entry) => entry.item))}
              items={items.data ?? []}
              run={run}
            />
          )}
        </div>
      </div>
    </PageShell>
  )
}

/** Receive, issue, adjust, transfer — and the ledger they all write to. */
function RecordActions({
  record, storeLimit, actorId, onError, run,
}: {
  record: StockRecord
  storeLimit: string
  actorId: number | null
  onError: (message: string | null) => void
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const { can } = useAuth()
  const [tab, setTab] = useState<'ledger' | 'receive' | 'issue' | 'adjust' | 'transfer'>(
    'ledger',
  )
  const movements = useStockMovements(record.id)

  const tabs = [
    { key: 'ledger' as const, label: 'Ledger', show: true },
    { key: 'receive' as const, label: 'Receive', show: can('inventory.receive_stock') },
    { key: 'issue' as const, label: 'Issue', show: can('inventory.issue_stock') },
    { key: 'transfer' as const, label: 'Transfer', show: can('inventory.transfer_stock') },
    { key: 'adjust' as const, label: 'Adjust', show: can('inventory.adjust_stock') },
  ].filter((entry) => entry.show)

  return (
    <Panel>
      <PanelHeader
        title={record.item_name}
        hint={`${record.usable_on_hand} in date · level ${record.reorder_level}`}
        action={record.is_controlled ? <Badge tone="abnormal">controlled</Badge> : null}
      />
      <div className="flex gap-1 border-b border-border px-3 pt-3">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={`rounded-t-md px-3 py-2 text-[12.5px] font-medium transition ${
              tab === entry.key
                ? 'bg-surface text-accent shadow-[inset_0_-2px_0_0_var(--color-accent)]'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="p-5">
        {tab === 'ledger' && (
          movements.isPending ? (
            <LoadingNotice />
          ) : (movements.data ?? []).length === 0 ? (
            <EmptyState>No movements yet.</EmptyState>
          ) : (
            <ul className="grid gap-2.5">
              {(movements.data ?? []).map((movement) => (
                <li
                  key={movement.id}
                  className="rounded-lg border border-border bg-surface-sunken/40 p-3"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[12.5px] font-semibold text-ink">
                      {movement.kind_display}
                    </span>
                    <span
                      className={`text-[13px] font-bold ${
                        movement.quantity_delta < 0 ? 'text-critical' : 'text-normal'
                      }`}
                    >
                      {movement.quantity_delta > 0 ? '+' : ''}
                      {movement.quantity_delta}
                      <span className="ml-1.5 text-[11px] font-medium text-ink-faint">
                        → {movement.quantity_after}
                      </span>
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">
                    lot {movement.lot_number}
                    {movement.issued_to && ` · to ${movement.issued_to}`}
                  </p>
                  {movement.reason && (
                    <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
                      {movement.reason}
                    </p>
                  )}
                  <p className="mt-1 text-[11px] text-ink-faint">
                    {movement.recorded_by_email} · {dateAndTime(movement.recorded_at)}
                  </p>
                </li>
              ))}
            </ul>
          )
        )}

        {tab === 'receive' && <ReceiveForm record={record} run={run} onDone={() => setTab('ledger')} />}
        {tab === 'issue' && <IssueForm record={record} run={run} onDone={() => setTab('ledger')} />}
        {tab === 'transfer' && (
          <TransferForm record={record} run={run} onDone={() => setTab('ledger')} />
        )}
        {tab === 'adjust' && (
          <AdjustForm
            record={record}
            storeLimit={storeLimit}
            actorId={actorId}
            onError={onError}
            run={run}
            onDone={() => setTab('ledger')}
          />
        )}
      </div>
    </Panel>
  )
}

function ReceiveForm({
  record, run, onDone,
}: {
  record: StockRecord
  run: (action: () => Promise<unknown>) => Promise<void>
  onDone: () => void
}) {
  const receive = useReceiveStock()
  const [quantity, setQuantity] = useState('')
  const [lot, setLot] = useState('')
  const [expiry, setExpiry] = useState('')
  const [cost, setCost] = useState('')
  const [reason, setReason] = useState('')

  const ready = quantity !== '' && Number(quantity) > 0 && (!record.tracks_expiry || expiry !== '')

  return (
    <div className="grid gap-4">
      <Field label={`Quantity (${record.unit_of_issue})`} required>
        <Input
          type="number"
          min={1}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="text-right"
          autoFocus
        />
      </Field>
      <Field
        label="Lot number"
        hint={
          record.tracks_expiry
            ? "The supplier's, so it can be traced back."
            : 'Optional — one is generated if you leave this blank.'
        }
      >
        <Input value={lot} maxLength={60} onChange={(event) => setLot(event.target.value)} />
      </Field>
      {record.tracks_expiry ? (
        <Field label="Expiry date" required>
          <Input type="date" value={expiry} onChange={(event) => setExpiry(event.target.value)} />
        </Field>
      ) : (
        <p className="text-[12px] leading-relaxed text-ink-muted">
          {record.item_name} is not tracked by expiry date, so none is asked for.
        </p>
      )}
      <Field label="Unit cost" hint="What one costs. Used to value write-offs.">
        <Input
          type="number"
          step="0.01"
          min={0}
          value={cost}
          onChange={(event) => setCost(event.target.value)}
          className="text-right"
        />
      </Field>
      <Field label="Reference" hint="Delivery note or invoice number.">
        <Input value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <div>
        <Button
          disabled={!ready || receive.isPending}
          onClick={async () => {
            await run(() =>
              receive.mutateAsync({
                record: record.id,
                quantity: Number(quantity),
                lot_number: lot,
                expiry_date: record.tracks_expiry ? expiry : null,
                unit_cost: cost === '' ? '0' : cost,
                reason,
              }),
            )
            onDone()
          }}
          className="px-4 py-2.5"
        >
          {receive.isPending ? 'Booking in…' : 'Book delivery in'}
        </Button>
      </div>
    </div>
  )
}

function IssueForm({
  record, run, onDone,
}: {
  record: StockRecord
  run: (action: () => Promise<unknown>) => Promise<void>
  onDone: () => void
}) {
  const issue = useIssueStock()
  const [quantity, setQuantity] = useState('')
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')

  const asked = quantity === '' ? 0 : Number(quantity)
  const tooMuch = asked > record.usable_on_hand
  const ready = asked > 0 && !tooMuch && (!record.is_controlled || to.trim() !== '')

  return (
    <div className="grid gap-4">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        Issued soonest-expiry-first, so stock does not go out of date on the shelf.
        {record.on_hand !== record.usable_on_hand && (
          <>
            {' '}
            <span className="font-medium text-critical">
              {record.on_hand - record.usable_on_hand} expired and cannot be issued.
            </span>
          </>
        )}
      </p>
      <Field
        label={`Quantity (${record.unit_of_issue})`}
        required
        hint={`${record.usable_on_hand} available`}
      >
        <Input
          type="number"
          min={1}
          max={record.usable_on_hand}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="text-right"
          autoFocus
        />
      </Field>
      {tooMuch && (
        <p className="flex items-start gap-2 text-[12px] font-medium text-critical">
          <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
          Only {record.usable_on_hand} {record.unit_of_issue} is in date.
        </p>
      )}
      <Field
        label="Issued to"
        required={record.is_controlled}
        hint={
          record.is_controlled
            ? 'A controlled item needs a named recipient, not just a ward.'
            : 'Ward, department or theatre.'
        }
      >
        <Input value={to} maxLength={160} onChange={(event) => setTo(event.target.value)} />
      </Field>
      <Field label="Reason" hint="Optional.">
        <Input value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <div>
        <Button
          disabled={!ready || issue.isPending}
          onClick={async () => {
            await run(() =>
              issue.mutateAsync({
                record: record.id,
                quantity: asked,
                issued_to: to,
                reason,
              }),
            )
            onDone()
          }}
          className="px-4 py-2.5"
        >
          {issue.isPending ? 'Issuing…' : 'Issue stock'}
        </Button>
      </div>
    </div>
  )
}

function TransferForm({
  record, run, onDone,
}: {
  record: StockRecord
  run: (action: () => Promise<unknown>) => Promise<void>
  onDone: () => void
}) {
  const stores = useStores()
  const move = useTransferStock()
  const [to, setTo] = useState('')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')

  const elsewhere = (stores.data ?? []).filter((entry) => entry.id !== record.store)
  const asked = quantity === '' ? 0 : Number(quantity)
  const ready = to !== '' && asked > 0 && asked <= record.usable_on_hand

  return (
    <div className="grid gap-4">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        The expiry date travels with the stock, so a ward cupboard cannot end up holding
        goods it thinks are fresh.
      </p>
      <Field label="To store" required>
        <Select value={to} onChange={(event) => setTo(event.target.value)}>
          <option value="">Choose a store…</option>
          {elsewhere.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name} — {entry.kind_display}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label={`Quantity (${record.unit_of_issue})`}
        required
        hint={`${record.usable_on_hand} available`}
      >
        <Input
          type="number"
          min={1}
          max={record.usable_on_hand}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="text-right"
        />
      </Field>
      <Field label="Reason" hint="Optional.">
        <Input value={reason} maxLength={255} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <div>
        <Button
          disabled={!ready || move.isPending}
          onClick={async () => {
            await run(() =>
              move.mutateAsync({
                item: record.item,
                from_store: record.store,
                to_store: Number(to),
                quantity: asked,
                reason,
              }),
            )
            onDone()
          }}
          className="px-4 py-2.5"
        >
          {move.isPending ? 'Moving…' : 'Move stock'}
        </Button>
      </div>
    </div>
  )
}

/**
 * Correcting what the record says a store holds.
 *
 * Above the store's limit this needs a second person, and the screen works out
 * the value as the figures are typed rather than refusing after the fact — a
 * storekeeper should know a signature is needed before they go looking for one.
 */
function AdjustForm({
  record, storeLimit, actorId, onError, run, onDone,
}: {
  record: StockRecord
  storeLimit: string
  actorId: number | null
  onError: (message: string | null) => void
  run: (action: () => Promise<unknown>) => Promise<void>
  onDone: () => void
}) {
  const adjust = useAdjustStock()
  const staff = useStaff()
  const [lot, setLot] = useState('')
  const [kind, setKind] = useState<StockAdjustment['kind']>('count')
  const [direction, setDirection] = useState<'down' | 'up'>('down')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [authoriser, setAuthoriser] = useState('')

  const chosen = record.lots.find((entry) => String(entry.id) === lot) ?? null
  const magnitude = quantity === '' ? 0 : Math.abs(Number(quantity))
  const delta = direction === 'down' ? -magnitude : magnitude

  const value = useMemo(() => {
    if (!chosen || magnitude === 0) return 0
    return magnitude * Number(chosen.unit_cost)
  }, [chosen, magnitude])

  const limit = Number(storeLimit)
  const needsSecond = value > limit
  const authorisers = (staff.data ?? []).filter((person) => person.id !== actorId)

  const ready =
    chosen !== null &&
    magnitude > 0 &&
    reason.trim() !== '' &&
    (!needsSecond || authoriser !== '') &&
    (direction === 'up' || magnitude <= chosen.quantity_on_hand)

  return (
    <div className="grid gap-4">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        Every other movement records something that happened to the stock. An adjustment
        records that the record was wrong, which is why it needs a reason.
      </p>

      <Field label="Lot" required>
        <Select
          value={lot}
          onChange={(event) => {
            setLot(event.target.value)
            onError(null)
          }}
        >
          <option value="">Choose a lot…</option>
          {record.lots.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.lot_number} — {entry.quantity_on_hand} on hand
              {entry.expiry_date ? ` · exp ${entry.expiry_date}` : ''}
              {entry.is_expired ? ' (expired)' : ''}
            </option>
          ))}
        </Select>
      </Field>

      <Field label="What happened" required>
        <Select
          value={kind}
          onChange={(event) => setKind(event.target.value as StockAdjustment['kind'])}
        >
          <option value="count">Count correction</option>
          <option value="damage">Damaged</option>
          <option value="loss">Lost or unaccounted</option>
          <option value="expiry">Written off, expired</option>
          <option value="return_to_supplier">Returned to supplier</option>
        </Select>
      </Field>

      <Field label="Direction" required>
        <Select
          value={direction}
          onChange={(event) => setDirection(event.target.value as 'down' | 'up')}
        >
          <option value="down">Take off the record</option>
          <option value="up">Add back to the record</option>
        </Select>
      </Field>

      <Field
        label={`Quantity (${record.unit_of_issue})`}
        required
        hint={chosen ? `${chosen.quantity_on_hand} on that lot` : undefined}
      >
        <Input
          type="number"
          min={1}
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          className="text-right"
        />
      </Field>

      {chosen && magnitude > 0 && (
        <div
          className={`rounded-lg border px-3 py-2.5 text-[12px] leading-relaxed ${
            needsSecond
              ? 'border-abnormal/30 bg-abnormal-muted text-abnormal'
              : 'border-border bg-surface-sunken/40 text-ink-muted'
          }`}
        >
          Worth {money(value)}.{' '}
          {needsSecond
            ? `Above this store's limit of ${money(limit)}, so a second person has to authorise it.`
            : `Within this store's limit of ${money(limit)}.`}
        </div>
      )}

      {needsSecond && (
        <Field
          label="Authorised by"
          required
          hint="Somebody who holds the authorising permission. Not you."
        >
          <Select value={authoriser} onChange={(event) => setAuthoriser(event.target.value)}>
            <option value="">Choose a colleague…</option>
            {authorisers.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name} — {person.email}
              </option>
            ))}
          </Select>
        </Field>
      )}

      <Field label="Reason" required>
        <Textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Ten boxes unaccounted for at the monthly count."
        />
      </Field>

      <div>
        <Button
          disabled={!ready || adjust.isPending}
          onClick={async () => {
            await run(() =>
              adjust.mutateAsync({
                lot: Number(lot),
                kind,
                quantity_delta: delta,
                reason,
                authorised_by: authoriser === '' ? null : Number(authoriser),
              }),
            )
            onDone()
          }}
          className="px-4 py-2.5"
        >
          {adjust.isPending ? 'Recording…' : 'Record adjustment'}
        </Button>
      </div>
    </div>
  )
}

/** Adding an item to what this store carries. */
function AddLine({
  storeId, carried, items, run,
}: {
  storeId: number
  carried: Set<number>
  items: { id: number; name: string; code: string; default_reorder_level: number }[]
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const create = useStockRecordCreate()
  const [item, setItem] = useState('')
  const [level, setLevel] = useState('')

  const available = items.filter((entry) => !carried.has(entry.id))
  const chosen = available.find((entry) => String(entry.id) === item) ?? null

  return (
    <Panel>
      <PanelHeader
        title="Carry another item"
        hint="A store carrying nothing of an item is different from one that does not stock it."
      />
      <div className="grid gap-4 p-5">
        {available.length === 0 ? (
          <EmptyState>This store already carries every active item.</EmptyState>
        ) : (
          <>
            <Field label="Item" required>
              <Select
                value={item}
                onChange={(event) => {
                  setItem(event.target.value)
                  const picked = available.find(
                    (entry) => String(entry.id) === event.target.value,
                  )
                  setLevel(picked ? String(picked.default_reorder_level) : '')
                }}
              >
                <option value="">Choose an item…</option>
                {available.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name} ({entry.code})
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Reorder level for this store"
              required
              hint={
                chosen
                  ? `Catalogue default is ${chosen.default_reorder_level}. A ward cupboard needs a different number from the main store.`
                  : undefined
              }
            >
              <Input
                type="number"
                min={0}
                value={level}
                onChange={(event) => setLevel(event.target.value)}
                className="text-right"
              />
            </Field>
            <div>
              <Button
                variant="secondary"
                disabled={item === '' || level === '' || create.isPending}
                onClick={async () => {
                  await run(() =>
                    create.mutateAsync({
                      store: storeId,
                      item: Number(item),
                      reorder_level: Number(level),
                    }),
                  )
                  setItem('')
                  setLevel('')
                }}
              >
                {create.isPending ? 'Adding…' : 'Carry this item'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}
