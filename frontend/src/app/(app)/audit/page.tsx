'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Input, Panel, PanelHeader, Select } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { type AuditEventRecord, useAuditEvents, useVerifyChain } from '@/lib/config'
import { dateAndTime } from '@/lib/workflow'
import { useDebounced } from '@/lib/useDebounced'

/**
 * The audit log.
 *
 * Read-only, and not because this screen chooses to be: the model refuses
 * modification, a database trigger refuses it even from raw SQL, and there is
 * no write endpoint. What this screen adds is the ability to *check* that —
 * "verify the chain" recomputes every row's hash and reports any row whose
 * contents no longer match, which is what makes the log evidence rather than a
 * list someone could have edited.
 *
 * Refusals are shown alongside successes. A denied action is often the more
 * interesting record.
 */
export default function AuditPage() {
  const { can } = useAuth()
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [outcome, setOutcome] = useState('')
  const heldAction = useDebounced(action.trim())
  const heldActor = useDebounced(actor.trim())

  const events = useAuditEvents(
    { action: heldAction || undefined, actor: heldActor || undefined, outcome: outcome || undefined },
    can('audit.view_auditevent'),
  )
  const verify = useVerifyChain()

  const rows = events.data?.results ?? []

  if (!can('audit.view_auditevent')) {
    return (
      <PageShell>
        <Panel className="p-5">
          <p className="text-[13px] text-ink-muted">
            You do not hold the permission to read the audit log. It names which staff opened
            which patient&apos;s record, so it is restricted in its own right.
          </p>
        </Panel>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Audit
      </div>
      <PageHeading
        title="Audit log"
        subtitle={
          events.isLoading
            ? 'Loading…'
            : `${events.data?.count ?? 0} recorded event${(events.data?.count ?? 0) === 1 ? '' : 's'}`
        }
        action={
          <Button
            variant="secondary"
            onClick={() => verify.mutate()}
            disabled={verify.isPending}
          >
            {verify.isPending ? 'Verifying…' : 'Verify the chain'}
          </Button>
        }
      />

      {verify.data && (
        <p
          role="status"
          className={`mt-4 flex items-start gap-2 rounded-lg border px-4 py-3 text-[12.5px] font-medium ${
            verify.data.intact
              ? 'border-normal/30 bg-normal-muted text-normal'
              : 'border-critical/40 bg-critical-muted text-critical'
          }`}
        >
          {!verify.data.intact && <AlertIcon className="mt-0.5 size-4 shrink-0" />}
          <span>
            {verify.data.intact ? (
              <>
                Chain intact across {verify.data.events} events. Every row&apos;s hash matches
                its contents and links to the row before it.
              </>
            ) : (
              <>
                Chain broken. {verify.data.problems.length} problem
                {verify.data.problems.length === 1 ? '' : 's'}:
                <ul className="mt-1.5 list-disc pl-5">
                  {verify.data.problems.slice(0, 8).map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </>
            )}
          </span>
        </p>
      )}

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="filter-action" className="mb-1 block text-[11.5px] text-ink-muted">
            Action
          </label>
          <Input
            id="filter-action"
            type="search"
            value={action}
            onChange={(event) => setAction(event.target.value)}
            placeholder="patient.viewed, payment.received…"
          />
        </div>
        <div>
          <label htmlFor="filter-actor" className="mb-1 block text-[11.5px] text-ink-muted">
            Who
          </label>
          <Input
            id="filter-actor"
            type="search"
            value={actor}
            onChange={(event) => setActor(event.target.value)}
            placeholder="Email"
          />
        </div>
        <div>
          <label htmlFor="filter-outcome" className="mb-1 block text-[11.5px] text-ink-muted">
            Outcome
          </label>
          <Select
            id="filter-outcome"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
          >
            <option value="">Everything</option>
            <option value="allowed">Allowed</option>
            <option value="denied">Refused</option>
          </Select>
        </div>
      </div>

      <Panel className="mt-5">
        <PanelHeader title="Events" hint="Most recent first" />
        {events.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>Nothing matches those filters.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={1040}>
            <thead>
              <tr>
                <Th>When</Th>
                <Th>Who</Th>
                <Th>Action</Th>
                <Th>Outcome</Th>
                <Th>Patient</Th>
                <Th>What changed</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.id} className={event.outcome === 'denied' ? 'bg-critical-muted/20' : ''}>
                  <Td className="text-[11.5px] whitespace-nowrap text-ink-muted">
                    {dateAndTime(event.occurred_at)}
                  </Td>
                  <Td className="text-[11.5px]">
                    {event.actor_email || <span className="text-ink-faint">anonymous</span>}
                    {event.ip_address && (
                      <div className="font-mono text-[10.5px] text-ink-faint">{event.ip_address}</div>
                    )}
                  </Td>
                  <Td className="font-mono text-[11.5px]">{event.action}</Td>
                  <Td>
                    {event.outcome === 'denied' ? (
                      <Badge tone="critical">Refused</Badge>
                    ) : (
                      <Badge tone="normal">Allowed</Badge>
                    )}
                  </Td>
                  <Td className="text-[11.5px]">
                    {event.patient ? (
                      <Link href={`/patients/${event.patient}`} className="text-accent hover:underline">
                        {event.patient_name}
                        <div className="font-mono text-[10.5px] text-ink-faint">
                          {event.hospital_number}
                        </div>
                      </Link>
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </Td>
                  <Td className="max-w-[340px]">
                    <Changes event={event} />
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

/** Before → after, in the field-by-field form a reviewer actually reads. */
function Changes({ event }: { event: AuditEventRecord }) {
  const before = event.changes?.before ?? {}
  const after = event.changes?.after ?? {}
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]))

  if (keys.length === 0 && !event.reason) {
    return <span className="text-ink-faint">—</span>
  }

  return (
    <div className="text-[11.5px]">
      {keys.slice(0, 4).map((key) => (
        <div key={key} className="truncate">
          <span className="text-ink-muted">{key}: </span>
          {key in before && (
            <span className="text-critical line-through">{format(before[key])}</span>
          )}
          {key in before && key in after && <span className="text-ink-faint"> → </span>}
          {key in after && <span className="text-ink">{format(after[key])}</span>}
        </div>
      ))}
      {keys.length > 4 && (
        <div className="text-ink-faint">and {keys.length - 4} more</div>
      )}
      {event.reason && (
        <div className="mt-0.5 text-abnormal">Reason: {event.reason}</div>
      )}
    </div>
  )
}

function format(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
