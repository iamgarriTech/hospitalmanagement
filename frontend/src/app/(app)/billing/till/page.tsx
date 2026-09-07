'use client'

import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  useCashierSessions, useCloseSession, useOpenSession, useReconcileSession,
} from '@/lib/billing'
import { dateAndTime, money } from '@/lib/workflow'

/**
 * The cashier's till.
 *
 * Reconciling freezes everything taken during the session — after that, no
 * application role can edit those invoices or payments, and a correction has to
 * be a new adjusting entry. That is what makes the day's takings trustworthy,
 * so the screen says it before the button is pressed rather than after.
 *
 * A variance has to be explained. An unexplained shortfall recorded as if it
 * were nothing is how a pattern goes unnoticed.
 */
export default function TillPage() {
  const { can, facility, user } = useAuth()
  const sessions = useCashierSessions()
  const openSession = useOpenSession()
  const closeSession = useCloseSession()
  const reconcile = useReconcileSession()

  const [float, setFloat] = useState('0.00')
  const [counted, setCounted] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mine = (sessions.data ?? []).filter((session) => session.cashier === user?.id)
  const current = mine.find((session) => session.status !== 'reconciled')
  const expected = current ? Number(current.expected_total) : 0
  const variance = counted === '' ? null : Number(counted) - expected

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That action could not be completed.')
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Cash desk
      </div>
      <PageHeading
        title="My till"
        subtitle="Payments land in a session so the day can be reconciled and the takings accounted for."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

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
              title={current.status === 'open' ? 'Till open' : 'Till closed, awaiting reconciliation'}
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
                {money(Number(current.opening_float) + expected)}
              </dd>
            </dl>

            <div className="border-t border-border p-5">
              {current.status === 'open' ? (
                <>
                  <p className="mb-3 text-[12.5px] leading-relaxed text-ink-muted">
                    Closing stops further payments landing in this session. You can still
                    reconcile afterwards.
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
                <>
                  <p className="mb-4 flex items-start gap-2 rounded-lg border border-abnormal/30 bg-abnormal-muted px-3 py-2.5 text-[12px] leading-relaxed text-abnormal">
                    <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
                    Reconciling freezes every invoice and payment in this session. Nobody can
                    edit them afterwards — corrections have to be new adjusting entries.
                  </p>
                  <div className="grid gap-4">
                    <Field label="Counted in the drawer" required>
                      <Input
                        type="number"
                        step="0.01"
                        value={counted}
                        onChange={(event) => setCounted(event.target.value)}
                        className="text-right"
                        autoFocus
                      />
                    </Field>
                    {variance !== null && variance !== 0 && (
                      <Field
                        label={`Explain the ${variance > 0 ? 'surplus' : 'shortfall'} of ${money(Math.abs(variance))}`}
                        required
                      >
                        <Textarea
                          value={note}
                          onChange={(event) => setNote(event.target.value)}
                          placeholder="₦200 shortfall, reported to the accountant"
                        />
                      </Field>
                    )}
                    {variance === 0 && (
                      <p className="text-[12.5px] font-medium text-normal">
                        Counted total matches exactly.
                      </p>
                    )}
                    <div>
                      <Button
                        disabled={
                          reconcile.isPending ||
                          counted === '' ||
                          !can('billing.reconcile_cashiersession') ||
                          (variance !== null && variance !== 0 && !note.trim())
                        }
                        onClick={() =>
                          run(() =>
                            reconcile.mutateAsync({
                              id: current.id,
                              counted_total: counted,
                              variance_note: note,
                            }),
                          )
                        }
                        className="px-4 py-2.5"
                      >
                        {reconcile.isPending ? 'Reconciling…' : 'Reconcile and freeze'}
                      </Button>
                      {!can('billing.reconcile_cashiersession') && (
                        <p className="mt-2 text-[12px] text-ink-muted">
                          A cashier does not sign off their own till. Ask an accountant to
                          reconcile it.
                        </p>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </Panel>
        )}

        <Panel>
          <PanelHeader title="Earlier sessions" hint="Most recent first" />
          {mine.length === 0 ? (
            <div className="p-5">
              <EmptyState>No sessions yet.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={520}>
              <thead>
                <tr>
                  <Th>Opened</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Taken</Th>
                  <Th className="text-right">Counted</Th>
                </tr>
              </thead>
              <tbody>
                {mine.map((session) => {
                  const diff =
                    session.counted_total === null
                      ? null
                      : Number(session.counted_total) - Number(session.expected_total)
                  return (
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
                            {diff !== null && diff !== 0 && (
                              <div className="text-[11px] font-semibold text-critical">
                                {diff > 0 ? '+' : ''}
                                {money(diff)}
                              </div>
                            )}
                          </>
                        )}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </TableFrame>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}
