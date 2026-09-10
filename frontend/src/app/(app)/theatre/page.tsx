'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import { Badge, EmptyState, Field, Panel, PanelHeader, Select, StatTile } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import {
  type ProcedureRequest,
  useProcedureRequests, useTheatreList, useTheatres,
} from '@/lib/procedures'
import { timeOfDay } from '@/lib/workflow'

/**
 * The operating list, and everything waiting to get onto one.
 *
 * The list is ordered by time rather than by urgency, because that is the
 * order the day actually runs in and the board on the theatre wall says the
 * same. Urgency decides what gets *booked* next, which is why the waiting
 * column beside it is sorted the other way.
 *
 * A case with consent outstanding is flagged here rather than at the theatre
 * door. Finding out on the table is how a list collapses.
 */
export default function TheatrePage() {
  const { can } = useAuth()
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [theatre, setTheatre] = useState<string>('')

  const theatres = useTheatres()
  const list = useTheatreList(date, theatre === '' ? null : Number(theatre))
  const waiting = useProcedureRequests('?open=true')

  const cases = list.data ?? []
  const unbooked = (waiting.data ?? [])
    .filter((r) => r.status === 'requested')
    .sort((a, b) => {
      const order = { emergency: 0, urgent: 1, routine: 2 }
      return order[a.urgency] - order[b.urgency]
    })
  const consentOutstanding = (waiting.data ?? []).filter(
    (r) => r.consent_blocking !== null,
  )

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Theatre
      </div>
      <PageHeading
        title="Operating list"
        subtitle="What is booked, what is waiting, and what cannot go ahead yet."
      />

      {list.isError && (
        <div className="mt-4"><ErrorNotice>The list could not be loaded.</ErrorNotice></div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Booked today" value={cases.length} />
        <StatTile
          label="Waiting for a slot"
          value={unbooked.length}
          tone={unbooked.length ? 'progress' : 'normal'}
        />
        <StatTile
          label="Consent outstanding"
          value={consentOutstanding.length}
          tone={consentOutstanding.length ? 'critical' : 'normal'}
        />
      </div>

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Panel>
          <PanelHeader
            title="The list"
            hint="In the order the day runs."
            action={
              <div className="flex gap-2">
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  className="rounded-md border border-border bg-surface px-2 py-1 text-[12px] text-ink"
                  aria-label="List date"
                />
                <Select
                  value={theatre}
                  onChange={(e) => setTheatre(e.target.value)}
                  className="py-1 text-[12px]"
                  aria-label="Theatre"
                >
                  <option value="">All theatres</option>
                  {(theatres.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </Select>
              </div>
            }
          />
          {list.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : cases.length === 0 ? (
            <div className="p-5"><EmptyState>Nothing booked for that day.</EmptyState></div>
          ) : (
            <TableFrame minWidth={680}>
              <thead>
                <tr>
                  <Th>Time</Th>
                  <Th>Theatre</Th>
                  <Th>Patient</Th>
                  <Th>Procedure</Th>
                  <Th>Surgeon</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {cases.map((entry) => (
                  <tr key={entry.id}>
                    <Td>
                      <span className="font-semibold text-ink">
                        {timeOfDay(entry.starts_at)}
                      </span>
                      <div className="text-[11px] text-ink-faint">
                        to {timeOfDay(entry.ends_at)}
                      </div>
                    </Td>
                    <Td className="text-ink-muted">{entry.theatre_name}</Td>
                    <Td>
                      <span className="font-medium text-ink">{entry.patient_name}</span>
                      <div className="text-[11px] text-ink-faint">
                        {entry.hospital_number}
                      </div>
                    </Td>
                    <Td className="text-ink-muted">{entry.procedure_name}</Td>
                    <Td className="text-ink-muted">
                      {entry.lead_surgeon_name}
                      {entry.anaesthetist_name && (
                        <div className="text-[11px] text-ink-faint">
                          {entry.anaesthetist_name}
                        </div>
                      )}
                    </Td>
                    <Td>
                      <Badge
                        tone={
                          entry.status === 'completed' ? 'normal'
                            : entry.status === 'in_progress' ? 'progress' : 'idle'
                        }
                      >
                        {entry.status_display}
                      </Badge>
                      <div className="mt-1">
                        <Link
                          href={`/theatre/${entry.request}`}
                          className="text-[12px] font-medium text-accent hover:underline"
                        >
                          Open
                        </Link>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <div className="grid gap-5">
          {consentOutstanding.length > 0 && (
            <Panel>
              <PanelHeader
                title="Cannot go ahead yet"
                hint="Consent is outstanding. Finding out at the door is too late."
                action={<Badge tone="critical">{consentOutstanding.length}</Badge>}
              />
              <div className="grid gap-2.5 p-5">
                {consentOutstanding.map((entry) => (
                  <Link
                    key={entry.id}
                    href={`/theatre/${entry.id}`}
                    className="block rounded-lg border border-critical/30 bg-critical/5 p-3 transition hover:border-critical/60"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[12.5px] font-semibold text-ink">
                        {entry.patient_name}
                      </span>
                      <span className="text-[11px] text-ink-faint">
                        {entry.reference}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[12px] text-ink-muted">
                      {entry.procedure_name}
                    </p>
                    <p className="mt-1 flex items-start gap-1.5 text-[12px] leading-relaxed text-critical">
                      <AlertIcon className="mt-0.5 size-3 shrink-0" />
                      {entry.consent_blocking}
                    </p>
                  </Link>
                ))}
              </div>
            </Panel>
          )}

          <WaitingList requests={unbooked} loading={waiting.isPending} canBook={can('procedures.schedule_procedure')} />
        </div>
      </div>
    </PageShell>
  )
}

function WaitingList({
  requests, loading, canBook,
}: {
  requests: ProcedureRequest[]
  loading: boolean
  canBook: boolean
}) {
  return (
    <Panel>
      <PanelHeader
        title="Waiting for a slot"
        hint="Most urgent first — the order things should be booked in."
      />
      {loading ? (
        <div className="p-5"><LoadingNotice /></div>
      ) : requests.length === 0 ? (
        <div className="p-5"><EmptyState>Nothing waiting.</EmptyState></div>
      ) : (
        <div className="grid gap-2.5 p-5">
          {requests.map((entry) => (
            <Link
              key={entry.id}
              href={`/theatre/${entry.id}`}
              className="block rounded-lg border border-border bg-surface-sunken/40 p-3 transition hover:border-accent/50"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[12.5px] font-semibold text-ink">
                  {entry.patient_name}
                </span>
                <Badge
                  tone={
                    entry.urgency === 'emergency' ? 'critical'
                      : entry.urgency === 'urgent' ? 'abnormal' : 'idle'
                  }
                >
                  {entry.urgency_display}
                </Badge>
              </div>
              <p className="mt-0.5 text-[12px] text-ink-muted">
                {entry.procedure_name}
                {entry.requires_theatre && ' · needs a theatre'}
              </p>
              <p className="mt-1 text-[11.5px] leading-relaxed text-ink-faint">
                {entry.indication}
              </p>
              {canBook && (
                <span className="mt-1.5 inline-block text-[12px] font-medium text-accent">
                  Book a slot →
                </span>
              )}
            </Link>
          ))}
        </div>
      )}
    </Panel>
  )
}
