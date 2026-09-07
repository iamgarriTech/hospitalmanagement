'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, Td, Th, TableFrame } from '@/components/PageShell'
import {
  AlertIcon,
  ArrowRightIcon,
  BillingIcon,
  CalendarIcon,
  LabIcon,
  PharmacyIcon,
  QueueIcon,
  RefreshIcon,
  SearchIcon,
  StethoscopeIcon,
} from '@/components/icons'
import {
  Badge,
  Button,
  EmptyState,
  Panel,
  PanelHeader,
  Select,
  StatTile,
  type Tone,
} from '@/components/ui'
import { useAuth } from '@/lib/auth'
import {
  useCriticalResults,
  useLabWorklist,
  useOutstandingInvoices,
  usePharmacyQueue,
  useQueue,
} from '@/lib/queries'

/**
 * One dashboard, composed from what the signed-in user can actually act on.
 *
 * A receptionist, a nurse, a doctor, a laboratory scientist, a pharmacist and
 * a cashier each see a different page here — not the same statistics page with
 * different numbers. Panels are chosen by permission, so a hospital inventing
 * a role gets a sensible dashboard without a frontend release, and nothing is
 * shown that the viewer cannot do something about.
 */
export default function DashboardPage() {
  const { user, can, facility } = useAuth()
  const [search, setSearch] = useState('')
  const [queueFilter, setQueueFilter] = useState('all')
  const [date, setDate] = useState('')
  useEffect(() => {
    function updateDate() {
      setDate(
        new Intl.DateTimeFormat('en-GB', {
          day: 'numeric',
          month: 'long',
          year: 'numeric',
          timeZone: facility?.timezone ?? 'Africa/Lagos',
        }).format(new Date()),
      )
    }
    updateDate()
    const interval = window.setInterval(updateDate, 60_000)
    return () => window.clearInterval(interval)
  }, [facility?.timezone])

  const seesQueue = can('visits.view_visit')
  const seesLab = can('laboratory.view_laborder')
  const seesPharmacy = can('pharmacy.view_prescription')
  const seesBilling = can('billing.view_invoice')
  const recordsVitals = can('clinical.add_vitalsigns')
  const consults = can('clinical.add_encounter')

  const queue = useQueue({ enabled: seesQueue })
  const worklist = useLabWorklist(seesLab)
  const criticals = useCriticalResults(seesLab || consults)
  const pharmacy = usePharmacyQueue(seesPharmacy)
  const invoices = useOutstandingInvoices(seesBilling)

  const rows = queue.data ?? []
  const visibleRows = [...rows]
    .filter(
      (row) =>
        (queueFilter === 'all' || row.status === queueFilter) &&
        `${row.patient.full_name} ${row.patient.hospital_number}`
          .toLowerCase()
          .includes(search.toLowerCase().trim()),
    )
    .sort((a, b) => b.waiting_minutes - a.waiting_minutes)
  const sources = [
    ...(seesQueue ? [queue] : []),
    ...(seesLab ? [worklist] : []),
    ...(seesLab || consults ? [criticals] : []),
    ...(seesPharmacy ? [pharmacy] : []),
    ...(seesBilling ? [invoices] : []),
  ]
  const refreshing = sources.some((source) => source.isFetching)
  const hasErrors = sources.some((source) => source.isError)
  function refresh() {
    sources.forEach((source) => {
      void source.refetch()
    })
  }

  const waiting = rows.filter((row) => row.status === 'waiting')
  const withClinician = rows.filter((row) => row.status === 'in_consultation')
  const atLab = rows.filter((row) => row.status === 'sent_for_investigation')
  const atPharmacy = rows.filter((row) => row.status === 'sent_to_pharmacy')
  const atCashDesk = rows.filter((row) => row.status === 'sent_for_billing')
  const longestWait = waiting.reduce((worst, row) => Math.max(worst, row.waiting_minutes), 0)

  const readyForResults = (worklist.data ?? []).filter((row) => row.status === 'resulted')
  const awaitingCollection = (worklist.data ?? []).filter((row) => row.status === 'ordered')
  const urgentOnBench = (worklist.data ?? []).filter((row) => row.priority === 'urgent')
  const outstandingTotal = (invoices.data ?? []).reduce(
    (total, invoice) => total + Number(invoice.balance),
    0,
  )

  const firstName = user?.full_name.split(' ')[0] ?? ''

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        <span className="h-px w-5 bg-accent/50" /> Your daily overview
      </div>
      <PageHeading
        title={firstName ? `Good day, ${firstName}` : 'Dashboard'}
        subtitle="Here’s what’s happening across your hospital."
        action={
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex h-10 items-center gap-2 rounded-lg border border-border bg-surface px-3 text-xs text-ink-muted">
              <CalendarIcon className="size-4" />
              {date || 'Today'}
            </span>
            <Button
              variant="secondary"
              onClick={refresh}
              disabled={refreshing || sources.length === 0}
              className="bg-surface"
            >
              <RefreshIcon className={`size-4 ${refreshing ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        }
      />

      {hasErrors && (
        <div className="mt-5">
          <ErrorNotice>
            Some hospital data could not be refreshed. Any previously loaded information may be out
            of date. Use Refresh to try again.
          </ErrorNotice>
        </div>
      )}

      {/* Criticals come first for anyone who can act on them. Nothing else on
          this page outranks a critical laboratory value. */}
      {(seesLab || consults) && (criticals.data?.length ?? 0) > 0 && (
        <details className="group mt-5 overflow-hidden rounded-xl border border-critical/30 bg-critical-muted">
          <summary className="flex list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
            <AlertIcon className="size-4 text-critical" />
            <span className="text-[13px] font-semibold text-critical">
              {criticals.data!.length} critical result
              {criticals.data!.length === 1 ? '' : 's'} awaiting acknowledgement
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-2 text-xs font-semibold text-critical">
              <span className="hidden sm:inline">Review results</span>
              <ArrowRightIcon className="size-4 transition-transform group-open:rotate-90" />
            </span>
          </summary>
          <TableFrame minWidth={640}>
            <thead>
              <tr>
                <Th>Patient</Th>
                <Th>Test</Th>
                <Th>Value</Th>
                <Th>Reference</Th>
                <Th>Ordered by</Th>
              </tr>
            </thead>
            <tbody>
              {criticals.data!.map((row) => (
                <tr key={row.result_id}>
                  <Td>
                    <span className="font-semibold">{row.patient_name}</span>
                    <span className="ml-1.5 text-ink-faint">{row.hospital_number}</span>
                  </Td>
                  <Td>{row.test}</Td>
                  <Td>
                    <span className="font-bold text-critical">{row.value}</span>
                    <span className="ml-1.5 text-[10.5px] font-bold text-critical">
                      ▲ {row.flag_label}
                    </span>
                  </Td>
                  <Td className="text-ink-muted">{row.reference || '—'}</Td>
                  <Td className="text-ink-muted">{row.ordered_by}</Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
          <div className="border-t border-critical/20 px-5 py-3">
            <Link
              href="/laboratory/critical"
              className="text-xs font-semibold text-critical underline"
            >
              Open critical results worklist
            </Link>
          </div>
        </details>
      )}

      <div className="mt-6 grid grid-cols-2 gap-3 max-[359px]:grid-cols-1 sm:gap-4 xl:grid-cols-[repeat(auto-fit,minmax(175px,1fr))]">
        {seesQueue && (
          <>
            <StatTile
              label="Patients waiting"
              icon={<QueueIcon className="size-[18px]" />}
              loading={queue.isLoading}
              value={queue.isError ? '—' : waiting.length}
              hint={
                queue.isError
                  ? 'Unable to load queue'
                  : longestWait > 0
                    ? `Longest wait ${longestWait} min`
                    : 'Nobody waiting'
              }
              tone={longestWait >= 45 ? 'abnormal' : 'idle'}
              href="/queue"
            />
            <StatTile
              label="In consultation"
              icon={<StethoscopeIcon className="size-[18px]" />}
              loading={queue.isLoading}
              value={queue.isError ? '—' : withClinician.length}
              hint={queue.isError ? 'Unable to load queue' : 'Currently with a clinician'}
              tone="progress"
              href="/queue"
            />
          </>
        )}
        {seesLab && (
          <StatTile
            label="Results to verify"
            icon={<LabIcon className="size-[18px]" />}
            loading={worklist.isLoading}
            value={worklist.isError ? '—' : readyForResults.length}
            hint={
              worklist.isError
                ? 'Unable to load results'
                : urgentOnBench.length > 0
                  ? `${urgentOnBench.length} urgent on the bench`
                  : 'Laboratory verification queue'
            }
            tone={readyForResults.length > 0 ? 'abnormal' : 'idle'}
            href="/laboratory"
          />
        )}
        {seesPharmacy && (
          <StatTile
            label="To dispense"
            icon={<PharmacyIcon className="size-[18px]" />}
            loading={pharmacy.isLoading}
            hint={
              pharmacy.isError
                ? 'Unable to load prescriptions'
                : 'Prescriptions awaiting collection'
            }
            value={pharmacy.isError ? '—' : (pharmacy.data?.length ?? 0)}
            tone={(pharmacy.data?.length ?? 0) > 0 ? 'progress' : 'idle'}
            href="/pharmacy"
          />
        )}
        {seesBilling && (
          <StatTile
            label="Outstanding balance"
            icon={<BillingIcon className="size-[18px]" />}
            loading={invoices.isLoading}
            value={
              invoices.isError
                ? '—'
                : `₦${outstandingTotal.toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
            }
            hint={
              invoices.isError
                ? 'Unable to load invoices'
                : `${invoices.data?.length ?? 0} unpaid invoice${
                    (invoices.data?.length ?? 0) === 1 ? '' : 's'
                  }`
            }
            tone={outstandingTotal > 0 ? 'abnormal' : 'normal'}
            href="/billing"
          />
        )}
      </div>

      {seesQueue && (
        <Panel className="mt-6">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
            <div className="flex items-center gap-3">
              <span className="flex size-8 items-center justify-center rounded-lg bg-accent-muted text-accent">
                <QueueIcon className="size-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">Patient flow</h2>
                <p className="text-xs text-ink-muted">A snapshot of active visits</p>
              </div>
            </div>
            <span className="rounded-full bg-surface-muted px-3 py-1 text-xs font-medium text-ink-muted">
              {queue.isLoading || queue.isError ? '—' : rows.length} active patients
            </span>
          </div>
          <div className="grid grid-cols-2 gap-y-4 p-5 sm:grid-cols-3 xl:grid-cols-5">
            {[
              { label: 'Waiting', count: waiting.length, icon: QueueIcon },
              { label: 'Consultation', count: withClinician.length, icon: StethoscopeIcon },
              { label: 'Laboratory', count: atLab.length, icon: LabIcon },
              { label: 'Pharmacy', count: atPharmacy.length, icon: PharmacyIcon },
              { label: 'Billing', count: atCashDesk.length, icon: BillingIcon },
            ].map(({ label, count, icon: Icon }, index) => (
              <div key={label} className="flex items-center justify-between gap-2 px-2">
                <div className="flex items-center gap-3">
                  <Icon className="size-[18px] shrink-0 text-ink-faint" />
                  <div>
                    <p className="text-[11px] text-ink-muted">{label}</p>
                    <p className="mt-1 text-lg font-semibold leading-none">
                      {queue.isLoading || queue.isError ? '—' : count}
                    </p>
                  </div>
                </div>
                {index < 4 && (
                  <ArrowRightIcon className="hidden size-3.5 text-border-strong xl:block" />
                )}
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="mt-7 mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold tracking-tight">Care & operations</h2>
        <span className="text-[11px] text-ink-muted">
          {refreshing
            ? 'Updating…'
            : hasErrors
              ? 'Some data unavailable'
              : 'Overview of your worklists'}
        </span>
      </div>
      <div
        className={`grid items-start gap-5 ${seesQueue && (seesLab || seesPharmacy || seesBilling) ? 'xl:grid-cols-[1.15fr_1fr]' : ''}`}
      >
        {seesQueue && (
          <Panel>
            <PanelHeader
              title={recordsVitals && !consults ? 'Waiting for vitals' : 'Patient queue'}
              hint="Active visits, longest wait first"
              action={
                <Link href="/queue" className="text-[12px] font-semibold text-accent">
                  Full queue
                </Link>
              }
            />
            <div className="flex flex-wrap gap-3 border-b border-border px-5 py-3">
              <div className="relative min-w-40 flex-1">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" />
                <input
                  aria-label="Search patient queue"
                  placeholder="Search name or hospital number…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-3 text-xs placeholder:text-ink-faint"
                />
              </div>
              <Select
                aria-label="Filter queue by status"
                value={queueFilter}
                onChange={(event) => setQueueFilter(event.target.value)}
                className="max-w-full text-xs sm:max-w-40"
              >
                <option value="all">All statuses</option>
                <option value="waiting">Waiting</option>
                <option value="called">Called</option>
                <option value="in_consultation">With clinician</option>
                <option value="sent_for_investigation">At laboratory</option>
                <option value="sent_to_pharmacy">At pharmacy</option>
                <option value="sent_for_billing">At cash desk</option>
              </Select>
            </div>
            {queue.isError ? (
              <DataNotice failed />
            ) : queue.isLoading ? (
              <p className="px-4 py-6 text-[13px] text-ink-muted">Loading…</p>
            ) : visibleRows.length === 0 ? (
              <div className="p-4">
                <EmptyState>
                  {rows.length > 0
                    ? 'No patients match your search or filter.'
                    : 'No active visits. New arrivals will appear here.'}
                </EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={520}>
                <thead>
                  <tr>
                    <Th>Patient</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Waiting</Th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.slice(0, 8).map((row) => (
                    <tr key={row.id}>
                      <Td>
                        <div className="flex items-center gap-3">
                          <span
                            aria-hidden
                            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-muted/70 text-[11px] font-semibold text-accent"
                          >
                            {row.patient.full_name
                              .split(' ')
                              .filter(Boolean)
                              .slice(0, 2)
                              .map((name) => name[0])
                              .join('')}
                          </span>
                          <div>
                            <Link
                              href={`/patients/${row.patient.id}`}
                              className="font-semibold hover:text-accent hover:underline"
                            >
                              {row.patient.full_name}
                            </Link>
                            <div className="mt-0.5 text-[11px] text-ink-faint">
                              {row.patient.hospital_number}
                              {row.patient.age_years !== null && ` · ${row.patient.age_years}y`}
                              {` · ${row.patient.sex}`}
                            </div>
                          </div>
                        </div>
                        {row.allergies.length > 0 && (
                          <div className="mt-1 inline-flex items-center gap-1 rounded bg-critical-muted px-1.5 py-0.5 text-[10.5px] font-bold text-critical">
                            <AlertIcon className="size-3" />
                            Allergic to {row.allergies.join(', ')}
                          </div>
                        )}
                      </Td>
                      <Td>
                        <Badge tone={queueTone(row.status)}>{queueLabel(row.status)}</Badge>
                      </Td>
                      <Td className="text-right tabular-nums">
                        <span
                          className={row.waiting_minutes >= 45 ? 'font-semibold text-abnormal' : ''}
                        >
                          {row.waiting_minutes} min
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
            {!queue.isLoading && !queue.isError && visibleRows.length > 0 && (
              <div className="border-t border-border px-5 py-3 text-[11px] text-ink-muted">
                Showing {Math.min(visibleRows.length, 8)} of {visibleRows.length} active visits
              </div>
            )}
          </Panel>
        )}

        <div className="grid min-w-0 gap-5">
          {seesLab && (
            <Panel>
              <PanelHeader
                title="Laboratory"
                hint="Specimens and results needing attention"
                action={
                  <Link href="/laboratory" className="text-[12px] font-semibold text-accent">
                    Worklist
                  </Link>
                }
              />
              <div className="grid grid-cols-3 divide-x divide-border border-b border-border bg-surface-muted/40">
                <Figure
                  label="To collect"
                  value={worklist.isLoading || worklist.isError ? '—' : awaitingCollection.length}
                />
                <Figure
                  label="On the bench"
                  value={
                    worklist.isLoading || worklist.isError
                      ? '—'
                      : (worklist.data ?? []).filter((row) =>
                          ['collected', 'processing'].includes(row.status),
                        ).length
                  }
                />
                <Figure
                  label="To verify"
                  value={worklist.isLoading || worklist.isError ? '—' : readyForResults.length}
                  tone="abnormal"
                />
              </div>
              {worklist.isError || worklist.isLoading ? (
                <DataNotice failed={worklist.isError} />
              ) : readyForResults.length === 0 ? (
                <div className="p-4">
                  <EmptyState>Nothing awaiting verification.</EmptyState>
                </div>
              ) : (
                <TableFrame minWidth={480}>
                  <thead>
                    <tr>
                      <Th>Patient</Th>
                      <Th>Test</Th>
                      <Th>Priority</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {readyForResults.slice(0, 6).map((row) => (
                      <tr key={row.item_id}>
                        <Td>
                          <span className="font-semibold">{row.patient_name}</span>
                          <div className="text-[11px] text-ink-faint">{row.hospital_number}</div>
                        </Td>
                        <Td>{row.test}</Td>
                        <Td>
                          {row.priority === 'urgent' ? (
                            <Badge tone="critical">Urgent</Badge>
                          ) : (
                            <span className="text-ink-faint">Routine</span>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </TableFrame>
              )}
            </Panel>
          )}

          {seesPharmacy && (
            <Panel>
              <PanelHeader
                title="Dispensing queue"
                action={
                  <Link href="/pharmacy" className="text-[12px] font-semibold text-accent">
                    Open
                  </Link>
                }
              />
              {pharmacy.isError || pharmacy.isLoading ? (
                <DataNotice failed={pharmacy.isError} />
              ) : (pharmacy.data?.length ?? 0) === 0 ? (
                <div className="p-4">
                  <EmptyState>No prescriptions waiting.</EmptyState>
                </div>
              ) : (
                <TableFrame minWidth={480}>
                  <thead>
                    <tr>
                      <Th>Patient</Th>
                      <Th>Prescription</Th>
                      <Th className="text-right">Items</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {pharmacy.data!.slice(0, 6).map((row) => (
                      <tr key={row.id}>
                        <Td>
                          <span className="font-semibold">{row.patient_name}</span>
                          <div className="text-[11px] text-ink-faint">{row.hospital_number}</div>
                          {row.allergies.length > 0 && (
                            <div className="mt-1 inline-flex items-center gap-1 text-[10.5px] font-bold text-critical">
                              <AlertIcon className="size-3" />
                              {row.allergies.join(', ')}
                            </div>
                          )}
                        </Td>
                        <Td className="font-mono text-[11.5px]">{row.prescription_number}</Td>
                        <Td className="text-right">{row.items.length}</Td>
                      </tr>
                    ))}
                  </tbody>
                </TableFrame>
              )}
            </Panel>
          )}

          {seesBilling && (
            <Panel>
              <PanelHeader
                title="Unpaid invoices"
                action={
                  <Link href="/billing" className="text-[12px] font-semibold text-accent">
                    Open
                  </Link>
                }
              />
              {invoices.isError || invoices.isLoading ? (
                <DataNotice failed={invoices.isError} />
              ) : (invoices.data?.length ?? 0) === 0 ? (
                <div className="p-4">
                  <EmptyState>Nothing outstanding.</EmptyState>
                </div>
              ) : (
                <TableFrame minWidth={480}>
                  <thead>
                    <tr>
                      <Th>Patient</Th>
                      <Th>Invoice</Th>
                      <Th className="text-right">Balance</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.data!.slice(0, 6).map((invoice) => (
                      <tr key={invoice.id}>
                        <Td>
                          <span className="font-semibold">{invoice.patient_name}</span>
                          <div className="text-[11px] text-ink-faint">
                            {invoice.hospital_number}
                          </div>
                        </Td>
                        <Td className="font-mono text-[11.5px]">{invoice.invoice_number}</Td>
                        <Td className="text-right font-semibold tabular-nums">
                          ₦{Number(invoice.balance).toLocaleString('en-NG')}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </TableFrame>
              )}
            </Panel>
          )}
        </div>
      </div>

      {!seesQueue && !seesLab && !seesPharmacy && !seesBilling && (
        <div className="mt-5">
          <EmptyState>
            Your account has no clinical or administrative permissions yet. An administrator needs
            to assign you a role before this dashboard can show anything.
          </EmptyState>
        </div>
      )}
    </PageShell>
  )
}

function Figure({
  label,
  value,
  tone = 'idle',
}: {
  label: string
  value: number | string
  tone?: Tone
}) {
  const toneClass =
    tone === 'abnormal' && typeof value === 'number' && value > 0 ? 'text-abnormal' : 'text-ink'
  return (
    <div className="px-5 py-4">
      <div className="text-[11px] text-ink-muted">{label}</div>
      <div className={`mt-2 text-[24px] leading-none font-semibold ${toneClass}`}>{value}</div>
    </div>
  )
}

const QUEUE_LABELS: Record<string, string> = {
  scheduled: 'Scheduled',
  waiting: 'Waiting',
  called: 'Called',
  in_consultation: 'With clinician',
  sent_for_investigation: 'At laboratory',
  sent_to_pharmacy: 'At pharmacy',
  sent_for_billing: 'At cash desk',
  completed: 'Completed',
  cancelled: 'Cancelled',
}

const QUEUE_TONES: Record<string, Tone> = {
  scheduled: 'idle',
  waiting: 'idle',
  called: 'accent',
  in_consultation: 'progress',
  sent_for_investigation: 'progress',
  sent_to_pharmacy: 'progress',
  sent_for_billing: 'abnormal',
  completed: 'normal',
  cancelled: 'idle',
}

export function queueLabel(status: string) {
  return QUEUE_LABELS[status] ?? status
}
export function queueTone(status: string): Tone {
  return QUEUE_TONES[status] ?? 'idle'
}

function DataNotice({ failed = false }: { failed?: boolean }) {
  return (
    <div
      role={failed ? 'alert' : 'status'}
      className="px-5 py-10 text-center text-[13px] text-ink-muted"
    >
      {failed ? 'Unable to load this worklist. Use Refresh to try again.' : 'Loading worklist…'}
    </div>
  )
}
