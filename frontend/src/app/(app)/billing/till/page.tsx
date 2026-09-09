'use client'

import { useMemo, useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { CountSheet, countPayload, countSheetComplete } from '@/components/till/CountSheet'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type CashierSession, type MethodVariance, type SessionAdjustment,
  useAdjustSession, useCashierSessions, useCloseSession, useOpenSession,
  useReceiveTill, useReconcileSession,
} from '@/lib/billing'
import { dateAndTime, money } from '@/lib/workflow'

type CountState = Record<number, { counted: string; note: string }>

/**
 * The cashier's till.
 *
 * Three things happen here, and they are deliberately different acts:
 *
 * - **Counting and reconciling.** A count per payment method, not one figure
 *   for the drawer, and every discrepancy explained on its own row.
 *   Reconciling freezes everything taken during the session, so the screen
 *   says so before the button is pressed rather than after.
 * - **Correcting.** Once reconciled, nothing about the session changes. A
 *   correction found the next morning is a new adjusting entry naming the
 *   session, which is why the reconciled figures stay on screen beside it.
 * - **Handing over.** A till passed mid-shift is counted, closed, and reopened
 *   under the incoming cashier — and it is the incoming cashier who confirms
 *   it, because a signature one person supplies for two is one signature.
 */
export default function TillPage() {
  const { can, facility, user } = useAuth()
  const sessions = useCashierSessions()
  const openSession = useOpenSession()
  const closeSession = useCloseSession()
  const reconcile = useReconcileSession()
  const adjust = useAdjustSession()
  const receive = useReceiveTill()

  const [float, setFloat] = useState('0.00')
  // Keyed by session, then by method. An accountant signing off three tills in
  // a row must not see a figure typed on one appear on the next.
  const [sheets, setSheets] = useState<Record<number, CountState>>({})
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [refusals, setRefusals] = useState<string[]>([])

  const all = sessions.data ?? []
  const mine = all.filter((session) => session.cashier === user?.id)
  const current = mine.find((session) => session.status !== 'reconciled')

  // Somebody else's open till at this facility is one this cashier could be
  // taking over. Their own is excluded — a handover has two people in it.
  const takeable = all.filter(
    (session) => session.status === 'open' && session.cashier !== user?.id,
  )

  // Tills somebody has counted and closed, waiting for a signature. Not the
  // caller's own: a cashier does not sign off the money they counted, which is
  // enforced on the server and is the reason this list exists at all.
  const awaiting = all.filter(
    (session) => session.status === 'closed' && session.cashier !== user?.id,
  )

  const rows = current?.variance_by_method ?? []
  const expected = current ? Number(current.expected_total) : 0
  const drawer = current ? Number(current.opening_float) + expected : 0

  const sheetFor = (id: number) => sheets[id] ?? {}
  const noteFor = (id: number) => notes[id] ?? ''

  const setCountFor =
    (id: number) => (method: number, value: { counted: string; note: string }) =>
      setSheets((previous) => ({
        ...previous,
        [id]: { ...(previous[id] ?? {}), [method]: value },
      }))

  const setNoteFor = (id: number) => (value: string) =>
    setNotes((previous) => ({ ...previous, [id]: value }))

  async function run(action: () => Promise<unknown>, clear?: number) {
    setError(null)
    setRefusals([])
    try {
      await action()
      if (clear !== undefined) {
        setSheets((previous) => {
          const { [clear]: _discarded, ...rest } = previous
          return rest
        })
        setNotes((previous) => {
          const { [clear]: _discarded, ...rest } = previous
          return rest
        })
      }
    } catch (caught) {
      // The server lists each method that does not balance. Showing them as
      // one line per problem is the whole point — a single "does not balance"
      // sends the cashier back to recount everything.
      if (caught instanceof ApiError && caught.fields.unexplained?.length) {
        setRefusals(caught.fields.unexplained)
      } else {
        setError(
          caught instanceof ApiError ? caught.message : 'That action could not be completed.',
        )
      }
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Cash desk
      </div>
      <PageHeading
        title="My till"
        subtitle="Payments land in a session so the day can be counted, signed off and accounted for."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}
      {refusals.length > 0 && (
        <div className="mt-4">
          <ErrorNotice>
            <span className="font-semibold">This till does not balance yet.</span>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
              {refusals.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </ErrorNotice>
        </div>
      )}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
        {!current ? (
          <Panel>
            <PanelHeader title="Open a till" hint="Count your opening float first." />
            <div className="grid gap-4 p-5">
              <Field label="Opening float" required>
                <Input
                  type="number"
                  step="0.01"
                  min={0}
                  value={float}
                  onChange={(event) => setFloat(event.target.value)}
                  className="text-right"
                />
              </Field>
              <div>
                <Button
                  disabled={!facility || openSession.isPending || !can('billing.add_cashiersession')}
                  onClick={() =>
                    run(() =>
                      openSession.mutateAsync({ facility: facility!.id, opening_float: float }),
                    )
                  }
                  className="px-4 py-2.5"
                >
                  {openSession.isPending ? 'Opening…' : 'Open till'}
                </Button>
              </div>
            </div>
          </Panel>
        ) : (
          <Panel>
            <PanelHeader
              title={current.status === 'open' ? 'Till open' : 'Till closed, awaiting sign-off'}
              hint={`Opened ${dateAndTime(current.opened_at)}`}
              action={
                <Badge tone={current.status === 'open' ? 'normal' : 'abnormal'}>
                  {current.status}
                </Badge>
              }
            />
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 p-5 text-[13px]">
              <dt className="text-ink-muted">Opening float</dt>
              <dd className="text-right font-semibold">{money(current.opening_float)}</dd>
              <dt className="text-ink-muted">Taken this session</dt>
              <dd className="text-right font-semibold">{money(current.expected_total)}</dd>
              <dt className="border-t border-border pt-3 text-ink">Expected in the drawer</dt>
              <dd className="border-t border-border pt-3 text-right text-[16px] font-bold text-ink">
                {money(drawer)}
              </dd>
            </dl>

            {rows.length > 0 && (
              <div className="border-t border-border px-5 py-4">
                <p className="mb-2.5 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                  Taken by method
                </p>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12.5px]">
                  {rows.map((row) => (
                    <div key={row.method} className="col-span-2 flex justify-between gap-4">
                      <dt className="text-ink-muted">{row.method_name}</dt>
                      <dd className="font-semibold">{money(row.expected)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            <div className="border-t border-border p-5">
              {current.status === 'open' ? (
                <>
                  <p className="mb-3 text-[12.5px] leading-relaxed text-ink-muted">
                    Closing stops further payments landing in this session. Counting and
                    sign-off happen afterwards.
                  </p>
                  <Button
                    variant="secondary"
                    disabled={closeSession.isPending}
                    onClick={() => run(() => closeSession.mutateAsync(current.id))}
                  >
                    {closeSession.isPending ? 'Closing…' : 'Close till'}
                  </Button>
                </>
              ) : (
                <SignOff
                  rows={rows}
                  counts={sheetFor(current.id)}
                  onCount={setCountFor(current.id)}
                  note={noteFor(current.id)}
                  onNote={setNoteFor(current.id)}
                  complete={countSheetComplete(rows, sheetFor(current.id))}
                  busy={reconcile.isPending}
                  canSignOff={can('billing.reconcile_cashiersession')}
                  ownTill
                  onSignOff={() =>
                    run(
                      () =>
                        reconcile.mutateAsync({
                          id: current.id,
                          counts: countPayload(rows, sheetFor(current.id)),
                          variance_note: noteFor(current.id),
                        }),
                      current.id,
                    )
                  }
                />
              )}
            </div>
          </Panel>
        )}

        <div className="grid gap-5">
          {can('billing.reconcile_cashiersession') && awaiting.length > 0 && (
            <Panel>
              <PanelHeader
                title="Tills awaiting sign-off"
                hint="Closed, counted by the cashier, not yet frozen."
              />
              <div className="grid gap-5 p-5">
                {awaiting.map((session) => (
                  <div key={session.id} className="border-b border-border pb-5 last:border-0 last:pb-0">
                    <div className="mb-3 flex items-baseline justify-between gap-4">
                      <span className="text-[13px] font-semibold text-ink">
                        {session.cashier_email}
                      </span>
                      <span className="text-[12px] text-ink-muted">
                        {money(session.expected_total)} taken · closed{' '}
                        {dateAndTime(session.closed_at ?? session.opened_at)}
                      </span>
                    </div>
                    <SignOff
                      rows={session.variance_by_method}
                      counts={sheetFor(session.id)}
                      onCount={setCountFor(session.id)}
                      note={noteFor(session.id)}
                      onNote={setNoteFor(session.id)}
                      complete={countSheetComplete(
                        session.variance_by_method, sheetFor(session.id),
                      )}
                      busy={reconcile.isPending}
                      canSignOff
                      onSignOff={() =>
                        run(
                          () =>
                            reconcile.mutateAsync({
                              id: session.id,
                              counts: countPayload(
                                session.variance_by_method, sheetFor(session.id),
                              ),
                              variance_note: noteFor(session.id),
                            }),
                          session.id,
                        )
                      }
                    />
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {takeable.length > 0 && can('billing.receive_till') && !current && (
            <HandoverPanel
              sessions={takeable}
              busy={receive.isPending}
              onReceive={(payload) => run(() => receive.mutateAsync(payload))}
            />
          )}

          <Panel>
            <PanelHeader title="Earlier sessions" hint="Most recent first" />
            {mine.length === 0 ? (
              <div className="p-5">
                <EmptyState>No sessions yet.</EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={560}>
                <thead>
                  <tr>
                    <Th>Opened</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Taken</Th>
                    <Th className="text-right">Counted</Th>
                  </tr>
                </thead>
                <tbody>
                  {mine.map((session) => (
                    <tr key={session.id}>
                      <Td className="text-ink-muted">{dateAndTime(session.opened_at)}</Td>
                      <Td>
                        <Badge
                          tone={
                            session.status === 'reconciled'
                              ? 'normal'
                              : session.status === 'open'
                                ? 'progress'
                                : 'abnormal'
                          }
                        >
                          {session.status}
                        </Badge>
                      </Td>
                      <Td className="text-right">{money(session.expected_total)}</Td>
                      <Td className="text-right">
                        {session.counted_total === null ? (
                          <span className="text-ink-faint">—</span>
                        ) : (
                          <>
                            {money(session.counted_total)}
                            {Number(session.net_variance) !== 0 && (
                              <div className="text-[11px] font-semibold text-critical">
                                {Number(session.net_variance) > 0 ? '+' : ''}
                                {money(session.net_variance)}
                              </div>
                            )}
                          </>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
          </Panel>

          {mine
            .filter((session) => session.status === 'reconciled')
            .slice(0, 3)
            .map((session) => (
              <SignedOffPanel
                key={session.id}
                session={session}
                canAdjust={can('billing.adjust_cashiersession')}
                busy={adjust.isPending}
                onAdjust={(payload) => run(() => adjust.mutateAsync(payload))}
              />
            ))}
        </div>
      </div>
    </PageShell>
  )
}

/**
 * Counting a closed till and signing it off.
 *
 * The same block serves a cashier counting their own drawer and an accountant
 * signing off somebody else's, because it is the same count sheet either way —
 * only the signature differs, and the server decides who may give it.
 */
function SignOff({
  rows, counts, onCount, note, onNote, complete, busy, canSignOff, onSignOff,
  ownTill = false,
}: {
  rows: MethodVariance[]
  counts: CountState
  onCount: (method: number, value: { counted: string; note: string }) => void
  note: string
  onNote: (value: string) => void
  complete: boolean
  busy: boolean
  canSignOff: boolean
  onSignOff: () => void
  ownTill?: boolean
}) {
  return (
    <>
      <p className="mb-4 flex items-start gap-2 rounded-lg border border-abnormal/30 bg-abnormal-muted px-3 py-2.5 text-[12px] leading-relaxed text-abnormal">
        <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
        Signing off freezes every invoice and payment in this session. Nobody can edit
        them afterwards — a correction has to be a new adjusting entry.
      </p>

      <CountSheet rows={rows} counts={counts} onChange={onCount} />

      <div className="mt-4 grid gap-4">
        <Field label="Anything else worth recording" hint="Optional.">
          <Textarea
            value={note}
            onChange={(event) => onNote(event.target.value)}
            placeholder="Two card terminals were down between 11:00 and 12:30."
          />
        </Field>
        <div>
          <Button
            disabled={busy || !complete || !canSignOff}
            onClick={onSignOff}
            className="px-4 py-2.5"
          >
            {busy ? 'Signing off…' : 'Sign off and freeze'}
          </Button>
          {ownTill && !canSignOff && (
            <p className="mt-2 text-[12px] text-ink-muted">
              A cashier does not sign off their own till. Count it, then ask an accountant
              to sign it off.
            </p>
          )}
        </div>
      </div>
    </>
  )
}

/**
 * A signed-off session: what was counted, and any corrections since.
 *
 * The reconciled figures stay exactly as they were signed off. That is the
 * point of showing them next to the adjustments rather than folding the two
 * together into a single current figure — somebody has to be able to see what
 * was originally counted and what changed afterwards.
 */
function SignedOffPanel({
  session, canAdjust, busy, onAdjust,
}: {
  session: CashierSession
  canAdjust: boolean
  busy: boolean
  onAdjust: (payload: {
    id: number
    kind: SessionAdjustment['kind']
    method: number | null
    amount: string
    reason: string
  }) => void
}) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<SessionAdjustment['kind']>('shortage')
  const [method, setMethod] = useState('')
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')

  // A shortage is money that is not there, so the entry is negative. Deriving
  // the sign from the kind means a cashier never has to remember to type a
  // minus, and never accidentally records a shortage as a surplus.
  const signed = useMemo(() => {
    if (amount === '') return ''
    const magnitude = Math.abs(Number(amount))
    return (kind === 'shortage' ? -magnitude : magnitude).toFixed(2)
  }, [amount, kind])

  return (
    <Panel>
      <PanelHeader
        title={`Signed off ${dateAndTime(session.reconciled_at ?? session.closed_at ?? session.opened_at)}`}
        hint={`Counted ${money(session.counted_total)} against ${money(session.expected_total)} taken`}
        action={<Badge tone="normal">frozen</Badge>}
      />

      <TableFrame minWidth={520}>
        <thead>
          <tr>
            <Th>Method</Th>
            <Th className="text-right">Taken</Th>
            <Th className="text-right">Counted</Th>
            <Th>Explanation</Th>
          </tr>
        </thead>
        <tbody>
          {session.variance_by_method.map((row) => (
            <tr key={row.method}>
              <Td>{row.method_name}</Td>
              <Td className="text-right">{money(row.expected)}</Td>
              <Td className="text-right">
                {money(row.counted)}
                {row.variance !== null && Number(row.variance) !== 0 && (
                  <div className="text-[11px] font-semibold text-critical">
                    {Number(row.variance) > 0 ? '+' : ''}
                    {money(row.variance)}
                  </div>
                )}
              </Td>
              <Td className="text-ink-muted">{row.note || <span className="text-ink-faint">—</span>}</Td>
            </tr>
          ))}
        </tbody>
      </TableFrame>

      {session.variance_note && (
        <p className="border-t border-border px-4 py-3 text-[12.5px] leading-relaxed text-ink-muted">
          {session.variance_note}
        </p>
      )}

      {session.adjustments.length > 0 && (
        <div className="border-t border-border p-4">
          <p className="mb-2.5 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Corrections since sign-off — {money(session.adjustment_total)}
          </p>
          <ul className="grid gap-2.5">
            {session.adjustments.map((entry) => (
              <li key={entry.id} className="rounded-lg border border-border bg-surface-sunken/40 p-3">
                <div className="flex items-baseline justify-between gap-4">
                  <span className="text-[12.5px] font-semibold text-ink">
                    {entry.kind_display}
                    {entry.method_name && (
                      <span className="text-ink-muted"> — {entry.method_name}</span>
                    )}
                  </span>
                  <span
                    className={`text-[13px] font-bold ${
                      Number(entry.amount) < 0 ? 'text-critical' : 'text-normal'
                    }`}
                  >
                    {Number(entry.amount) > 0 ? '+' : ''}
                    {money(entry.amount)}
                  </span>
                </div>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">{entry.reason}</p>
                <p className="mt-1 text-[11px] text-ink-faint">
                  {entry.raised_by_email} · {dateAndTime(entry.raised_at)}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {canAdjust && (
        <div className="border-t border-border p-4">
          {!open ? (
            <Button variant="secondary" onClick={() => setOpen(true)}>
              Record a correction
            </Button>
          ) : (
            <div className="grid gap-4">
              <p className="text-[12px] leading-relaxed text-ink-muted">
                This session cannot be changed. A correction is a new entry against it, and
                both stay on the record.
              </p>
              <Field label="What was found" required>
                <Select
                  value={kind}
                  onChange={(event) => setKind(event.target.value as SessionAdjustment['kind'])}
                >
                  <option value="shortage">Shortage found after sign-off</option>
                  <option value="overage">Overage found after sign-off</option>
                  <option value="misposted">Taken against the wrong method or session</option>
                </Select>
              </Field>
              <Field label="Method" hint="Leave blank if it is not specific to one.">
                <Select value={method} onChange={(event) => setMethod(event.target.value)}>
                  <option value="">Not specific to one method</option>
                  {session.variance_by_method.map((row) => (
                    <option key={row.method} value={row.method}>
                      {row.method_name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Amount" required hint={signed ? `Recorded as ${signed}` : undefined}>
                <Input
                  type="number"
                  step="0.01"
                  min={0}
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  className="text-right"
                />
              </Field>
              <Field label="Reason" required>
                <Textarea
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="₦300 found missing at the second count next morning."
                />
              </Field>
              <div className="flex gap-2">
                <Button
                  disabled={busy || signed === '' || Number(signed) === 0 || !reason.trim()}
                  onClick={() => {
                    onAdjust({
                      id: session.id,
                      kind,
                      method: method === '' ? null : Number(method),
                      amount: signed,
                      reason,
                    })
                    setOpen(false)
                    setAmount('')
                    setReason('')
                  }}
                >
                  {busy ? 'Recording…' : 'Record correction'}
                </Button>
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

/**
 * Taking over a colleague's till.
 *
 * The incoming cashier counts what is in the drawer with the outgoing cashier
 * present, and confirms it here. Their own session opens with the float that
 * came across, so the drawer's contents are continuous — never in two sessions,
 * never in none.
 */
function HandoverPanel({
  sessions, busy, onReceive,
}: {
  sessions: CashierSession[]
  busy: boolean
  onReceive: (payload: {
    id: number
    counts: { method: number; counted: string; note: string }[]
    float_handed: string
    note: string
  }) => void
}) {
  const [selected, setSelected] = useState(String(sessions[0]?.id ?? ''))
  const [counts, setCounts] = useState<CountState>({})
  const [handed, setHanded] = useState('')
  const [note, setNote] = useState('')

  const session = sessions.find((entry) => String(entry.id) === selected)
  const rows = session?.variance_by_method ?? []
  const complete = countSheetComplete(rows, counts)
  const inDrawer = session
    ? Number(session.opening_float) +
      rows.reduce((total, row) => total + Number(counts[row.method]?.counted ?? 0), 0)
    : 0

  return (
    <Panel>
      <PanelHeader
        title="Take over a till"
        hint="Count the drawer with the outgoing cashier present."
      />
      <div className="grid gap-4 p-5">
        <p className="text-[12.5px] leading-relaxed text-ink-muted">
          Confirming this closes their session and opens yours with the float that comes
          across. Both names are recorded against it.
        </p>

        <Field label="Whose till" required>
          <Select
            value={selected}
            onChange={(event) => {
              // Changing till clears the sheet. Carrying figures counted from
              // one drawer over to another is how a count becomes fiction.
              setSelected(event.target.value)
              setCounts({})
              setHanded('')
            }}
          >
            {sessions.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.cashier_email} — open since {dateAndTime(entry.opened_at)}
              </option>
            ))}
          </Select>
        </Field>

        {session && (
          <>
            <CountSheet
              rows={rows}
              counts={counts}
              onChange={(method, value) =>
                setCounts((previous) => ({ ...previous, [method]: value }))
              }
            />

            <div className="rounded-lg border border-border bg-surface-sunken/40 px-4 py-3 text-[12.5px]">
              <div className="flex justify-between gap-4">
                <span className="text-ink-muted">Their opening float</span>
                <span className="font-semibold">{money(session.opening_float)}</span>
              </div>
              <div className="mt-1.5 flex justify-between gap-4 border-t border-border pt-1.5">
                <span className="text-ink">In the drawer, by your count</span>
                <span className="font-bold">{money(inDrawer)}</span>
              </div>
            </div>

            <Field
              label="Float you are taking on"
              required
              hint="Usually everything in the drawer."
            >
              <Input
                type="number"
                step="0.01"
                min={0}
                value={handed}
                onChange={(event) => setHanded(event.target.value)}
                className="text-right"
              />
            </Field>

            <Field label="Note" hint="Optional.">
              <Input
                value={note}
                maxLength={255}
                onChange={(event) => setNote(event.target.value)}
                placeholder="Afternoon shift, counted together at 14:00."
              />
            </Field>

            <div>
              <Button
                disabled={busy || !complete || handed === ''}
                onClick={() =>
                  onReceive({
                    id: session.id,
                    counts: countPayload(rows, counts),
                    float_handed: handed,
                    note,
                  })
                }
                className="px-4 py-2.5"
              >
                {busy ? 'Taking over…' : 'Confirm handover'}
              </Button>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}
