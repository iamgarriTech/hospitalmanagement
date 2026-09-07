'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Panel } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type QueueRow, useMoveVisit, useQueue } from '@/lib/queries'
import { queueAction, queueLabel, queueTone, timeOfDay, waitedFor } from '@/lib/workflow'

/**
 * The queue board.
 *
 * This is a wall-board: staff leave it open and act on what it says, so it
 * refreshes on its own and shows the whole building rather than one clinic.
 * Longest wait first, because the person who has been there longest is the one
 * being forgotten.
 *
 * Allergies are on the row on purpose. Nobody should have to open a chart to
 * learn that the patient they are about to see is allergic to something.
 */

const FILTERS: { key: string; label: string; statuses?: string }[] = [
  { key: 'active', label: 'In the building' },
  { key: 'waiting', label: 'Waiting', statuses: 'waiting,called' },
  { key: 'clinic', label: 'With a clinician', statuses: 'in_consultation' },
  { key: 'lab', label: 'At laboratory', statuses: 'sent_for_investigation' },
  { key: 'pharmacy', label: 'At pharmacy', statuses: 'sent_to_pharmacy' },
  { key: 'cash', label: 'At cash desk', statuses: 'sent_for_billing' },
  { key: 'closed', label: 'Finished today', statuses: 'completed,cancelled' },
]

export default function QueuePage() {
  const { can } = useAuth()
  const [filter, setFilter] = useState('active')
  const [error, setError] = useState<string | null>(null)

  const selected = FILTERS.find((entry) => entry.key === filter) ?? FILTERS[0]
  const queue = useQueue({ status: selected.statuses })
  const move = useMoveVisit()
  const canMove = can('visits.move_queue')

  const rows = queue.data ?? []
  const longest = rows.reduce((worst, row) => Math.max(worst, row.waiting_minutes), 0)

  async function moveTo(row: QueueRow, to: string) {
    setError(null)
    try {
      await move.mutateAsync({ id: row.id, to })
    } catch (caught) {
      // A refused move is usually someone else having moved the patient first,
      // so the message from the server is the useful one.
      setError(caught instanceof ApiError ? caught.message : 'Could not move this patient.')
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Front desk
      </div>
      <PageHeading
        title="Patient queue"
        subtitle={
          queue.isLoading
            ? 'Loading…'
            : `${rows.length} patient${rows.length === 1 ? '' : 's'}${
                longest > 0 ? ` · longest wait ${waitedFor(longest)}` : ''
              }`
        }
        action={
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => queue.refetch()} disabled={queue.isFetching}>
              {queue.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
            {can('visits.check_in_patient') && (
              <Link
                href="/patients?checkin=1"
                className="inline-flex items-center justify-center rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
              >
                Check in a patient
              </Link>
            )}
          </div>
        }
      />

      {error && <div className="mt-4">
        <ErrorNotice>{error}</ErrorNotice>
      </div>}

      <div
        className="mt-6 -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0"
        role="tablist"
        aria-label="Filter the queue"
      >
        {FILTERS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={filter === entry.key}
            onClick={() => setFilter(entry.key)}
            className={`shrink-0 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
              filter === entry.key
                ? 'bg-accent text-white'
                : 'bg-surface text-ink-muted hover:bg-surface-muted hover:text-ink'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <Panel className="mt-4">
        {queue.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
            Loading the queue…
          </p>
        ) : queue.isError ? (
          <p role="alert" className="px-5 py-10 text-center text-[13px] text-ink-muted">
            Unable to load the queue. Use Refresh to try again.
          </p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>
              {filter === 'active'
                ? 'Nobody is currently in the building.'
                : `No patients ${selected.label.toLowerCase()}.`}
            </EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={980}>
            <thead>
              <tr>
                <Th>Patient</Th>
                <Th>Visit</Th>
                <Th>Reason</Th>
                <Th>Where</Th>
                <Th className="text-right">Arrived</Th>
                <Th className="text-right">Waited</Th>
                {canMove && <Th className="text-right">Move</Th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link
                      href={`/patients/${row.patient.id}`}
                      className="font-semibold text-ink hover:text-accent hover:underline"
                    >
                      {row.patient.full_name}
                    </Link>
                    <div className="mt-0.5 text-[11px] text-ink-faint">
                      {row.patient.hospital_number}
                      {row.patient.age_years !== null && ` · ${row.patient.age_years}y`}
                      {` · ${row.patient.sex}`}
                    </div>
                    {row.allergies.length > 0 && (
                      <div className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-critical-muted px-1.5 py-0.5 text-[10.5px] font-bold text-critical">
                        <AlertIcon className="size-3" />
                        Allergic to {row.allergies.join(', ')}
                      </div>
                    )}
                  </Td>
                  <Td className="font-mono text-[11.5px] text-ink-muted">{row.visit_number}</Td>
                  <Td className="max-w-[220px] text-[12px] text-ink-muted">
                    {row.reason || <span className="text-ink-faint">—</span>}
                    {row.clinic_name && (
                      <div className="mt-0.5 text-[11px] text-ink-faint">{row.clinic_name}</div>
                    )}
                  </Td>
                  <Td>
                    <Badge tone={queueTone(row.status)}>{queueLabel(row.status)}</Badge>
                  </Td>
                  <Td className="text-right text-[12px] text-ink-muted">
                    {timeOfDay(row.arrived_at)}
                  </Td>
                  <Td className="text-right">
                    <span
                      className={
                        row.waiting_minutes >= 45 ? 'font-semibold text-abnormal' : 'text-ink'
                      }
                    >
                      {waitedFor(row.waiting_minutes)}
                    </span>
                  </Td>
                  {canMove && (
                    <Td className="text-right">
                      <MoveMenu
                        row={row}
                        busy={move.isPending && move.variables?.id === row.id}
                        onMove={(to) => moveTo(row, to)}
                      />
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}

/**
 * Only the moves the workflow allows from here, as sent by the server. The
 * first one is promoted to a button because there is almost always an obvious
 * next step, and the rest sit behind "More" so the row stays readable.
 */
function MoveMenu({
  row,
  busy,
  onMove,
}: {
  row: QueueRow
  busy: boolean
  onMove: (to: string) => void
}) {
  const [open, setOpen] = useState(false)
  const transitions = row.allowed_transitions.filter((entry) => entry !== 'cancelled')
  const rest = transitions.slice(1)
  const primary = transitions[0]

  if (!primary) {
    return <span className="text-[11.5px] text-ink-faint">No further steps</span>
  }

  return (
    <div className="relative inline-flex items-center gap-1.5">
      <Button variant="secondary" disabled={busy} onClick={() => onMove(primary)}>
        {busy ? 'Moving…' : queueAction(primary)}
      </Button>
      {(rest.length > 0 || row.allowed_transitions.includes('cancelled')) && (
        <>
          <Button
            variant="ghost"
            aria-label="More moves"
            aria-expanded={open}
            onClick={() => setOpen((shown) => !shown)}
          >
            More
          </Button>
          {open && (
            <div className="absolute top-9 right-0 z-30 w-56 rounded-xl border border-border bg-surface py-1 shadow-popover">
              {rest.map((entry) => (
                <button
                  key={entry}
                  type="button"
                  onClick={() => {
                    setOpen(false)
                    onMove(entry)
                  }}
                  className="block w-full px-3 py-2 text-left text-[12.5px] text-ink hover:bg-surface-muted"
                >
                  {queueAction(entry)}
                </button>
              ))}
              {row.allowed_transitions.includes('cancelled') && (
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false)
                    onMove('cancelled')
                  }}
                  className="block w-full border-t border-border px-3 py-2 text-left text-[12.5px] text-critical hover:bg-critical-muted"
                >
                  Cancel visit
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
