'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { AlertIcon, HospitalIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Panel,
  PanelHeader,
  StatTile,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import {
  type BoardBed,
  type WardBoard,
  useSetBedState,
  useWardBoard,
  useWards,
} from '@/lib/inpatient'
import { bedLabel, bedTone, dayAndMonth, waitedFor } from '@/lib/workflow'

/**
 * The bed board.
 *
 * This is the screen a ward keeps open all shift, so it is built to be read at
 * a glance and to be enough to hand over from: who is in which bed, what they
 * must not be given, what is overdue and what nobody has answered for.
 *
 * The buttons come from the server's `can` block rather than from the client's
 * own permission list. Both would usually agree; when they don't, the server is
 * right, and a board that offers an action which 403s is worse than one that
 * hides it.
 */
export default function WardsPage() {
  const wards = useWards()
  const [wardId, setWardId] = useState<number | null>(null)

  // First ward once the list arrives, so the screen is never an empty picker.
  useEffect(() => {
    if (wardId === null && wards.data?.length) setWardId(wards.data[0].id)
  }, [wardId, wards.data])

  const board = useWardBoard(wardId)
  const ward = wards.data?.find((entry) => entry.id === wardId)

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Inpatient
      </div>
      <PageHeading
        title="Bed board"
        subtitle="Who is in which bed, and what is outstanding for them."
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/wards/requests"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
            >
              Admission requests
            </Link>
            <Link
              href="/wards/discharges"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
            >
              Discharges
            </Link>
          </div>
        }
      />

      {wards.isError && <ErrorNotice>Could not load the wards.</ErrorNotice>}
      {wards.isLoading && <LoadingNotice>Loading wards…</LoadingNotice>}

      {wards.data?.length === 0 && (
        <EmptyState>
          No wards are configured yet. A hospital administrator adds them under
          Configuration → Wards &amp; beds.
        </EmptyState>
      )}

      {(wards.data?.length ?? 0) > 0 && (
        <>
          <div
            className="mb-5 flex flex-wrap gap-2"
            role="tablist"
            aria-label="Wards"
          >
            {wards.data?.map((entry) => {
              const selected = entry.id === wardId
              const free = entry.occupancy.available
              return (
                <button
                  key={entry.id}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => setWardId(entry.id)}
                  className={`rounded-xl border px-4 py-3 text-left transition-colors ${
                    selected
                      ? 'border-accent bg-accent-muted/40'
                      : 'border-border bg-surface hover:border-border-strong'
                  }`}
                >
                  <span className="block text-[13px] font-semibold text-ink">
                    {entry.name}
                  </span>
                  <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                    {entry.occupancy.occupied} of {entry.occupancy.beds} occupied ·{' '}
                    {free} free
                  </span>
                </button>
              )
            })}
          </div>

          {board.isError && <ErrorNotice>Could not load this ward&apos;s board.</ErrorNotice>}
          {board.isLoading && <LoadingNotice>Loading the board…</LoadingNotice>}
          {board.data && (
            <Board board={board.data} wardName={ward?.name ?? board.data.ward.name} />
          )}
        </>
      )}
    </PageShell>
  )
}

function Board({ board, wardName }: { board: WardBoard; wardName: string }) {
  const census = board.occupancy
  const overdueTotal = board.overdue.in_window + board.overdue.older
  const escalations = board.beds.reduce(
    (total, bed) => total + (bed.patient?.escalation_count ?? 0),
    0,
  )

  return (
    <>
      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Occupied"
          value={`${census.occupied} / ${census.beds}`}
          hint={`${census.available} free to allocate`}
          tone="accent"
          icon={<HospitalIcon className="size-4" />}
        />
        <StatTile
          label="Overdue doses"
          value={overdueTotal}
          hint={
            board.overdue.older
              ? `${board.overdue.in_window} this shift, ${board.overdue.older} older`
              : `In the last ${board.overdue.window_hours} hours`
          }
          tone={overdueTotal ? 'abnormal' : 'normal'}
        />
        <StatTile
          label="Escalations outstanding"
          value={escalations}
          hint={escalations ? 'Nobody has recorded an action yet' : 'All answered'}
          tone={escalations ? 'critical' : 'normal'}
          icon={escalations ? <AlertIcon className="size-4" /> : undefined}
        />
        <StatTile
          label="Out of service"
          value={census.cleaning + census.maintenance}
          hint={`${census.cleaning} being cleaned, ${census.maintenance} maintenance`}
          tone="idle"
        />
      </div>

      <Panel>
        <PanelHeader
          title={`${wardName} — ${board.beds.length} beds`}
          hint="Refreshes every 30 seconds. A bed a patient has just left goes for cleaning, not straight back to free."
        />
        <ul className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {board.beds.map((bed) => (
            <li key={bed.bed}>
              <BedCard bed={bed} can={board.can} />
            </li>
          ))}
        </ul>
      </Panel>
    </>
  )
}

function BedCard({ bed, can }: { bed: BoardBed; can: WardBoard['can'] }) {
  const patient = bed.patient
  const setState = useSetBedState()
  const [note, setNote] = useState('')
  const [showState, setShowState] = useState(false)

  const conflict =
    setState.error instanceof ApiError && setState.error.status === 409
      ? setState.error.message
      : null

  return (
    <div
      className={`flex h-full flex-col rounded-xl border p-4 ${
        patient
          ? 'border-border bg-surface'
          : 'border-dashed border-border bg-surface-muted/40'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[13px] font-bold tracking-tight text-ink">
          {bed.bed_label}
        </span>
        <Badge tone={bedTone(bed.state)}>{bedLabel(bed.state)}</Badge>
      </div>

      {bed.state_note && (
        <p className="mt-1 text-[11.5px] text-ink-muted">{bed.state_note}</p>
      )}

      {patient ? (
        <>
          <Link
            href={`/wards/${patient.admission}`}
            className="mt-3 block text-[14px] font-semibold text-ink hover:text-accent"
          >
            {patient.name}
          </Link>
          <p className="mt-0.5 text-[11.5px] text-ink-muted">
            {patient.hospital_number} · {patient.sex}
            {patient.age_years !== null && ` · ${patient.age_years}y`} ·{' '}
            {patient.nights === 0 ? 'day 1' : `night ${patient.nights}`}
          </p>
          <p className="mt-2 text-[12.5px] leading-relaxed text-ink">
            {patient.diagnosis}
          </p>
          <p className="mt-0.5 text-[11.5px] text-ink-faint">
            Under {patient.consultant}
          </p>

          {patient.allergies.length > 0 ? (
            <p className="mt-3 rounded-md bg-critical-muted px-2.5 py-1.5 text-[11.5px] font-semibold text-critical">
              <span aria-hidden>▲ </span>
              Allergic to {patient.allergies.join(', ')}
            </p>
          ) : (
            <p className="mt-3 text-[11px] text-ink-faint">No allergies recorded</p>
          )}

          {patient.escalation_count > 0 && (
            <div className="mt-3 rounded-md border border-critical/30 bg-critical-muted/50 px-2.5 py-2">
              <p className="text-[11.5px] font-semibold text-critical">
                {patient.escalation_count} escalation
                {patient.escalation_count === 1 ? '' : 's'} outstanding
              </p>
              <ul className="mt-1 space-y-0.5">
                {patient.escalations.map((entry) => (
                  <li key={entry.id} className="text-[11px] text-critical/90">
                    {entry.measurement} {entry.value} ({entry.direction}) ·{' '}
                    {waitedFor(entry.minutes_waiting)} ago
                  </li>
                ))}
              </ul>
              {patient.escalation_count > patient.escalations.length && (
                <p className="mt-1 text-[10.5px] text-critical/80">
                  and {patient.escalation_count - patient.escalations.length} more
                </p>
              )}
            </div>
          )}

          {patient.overdue_count > 0 && (
            <div className="mt-2 rounded-md border border-abnormal/30 bg-abnormal-muted/50 px-2.5 py-2">
              <p className="text-[11.5px] font-semibold text-abnormal">
                {patient.overdue_count} dose{patient.overdue_count === 1 ? '' : 's'} overdue
              </p>
              <ul className="mt-1 space-y-0.5">
                {patient.overdue_doses.map((dose) => (
                  <li key={dose.dose_id} className="text-[11px] text-abnormal/90">
                    {dose.medication}
                    {dose.minutes_late !== null && ` · ${waitedFor(dose.minutes_late)} late`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {patient.discharge_planned && (
            <p className="mt-2 text-[11.5px] font-medium text-progress">
              Discharge planned
              {patient.expected_discharge_date &&
                ` for ${dayAndMonth(patient.expected_discharge_date)}`}
            </p>
          )}

          <div className="mt-auto pt-3">
            <Link
              href={`/wards/${patient.admission}`}
              className="text-[12px] font-semibold text-accent hover:underline"
            >
              Open chart →
            </Link>
          </div>
        </>
      ) : (
        <>
          <p className="mt-3 text-[12.5px] text-ink-muted">
            {bed.state === 'available'
              ? 'Free to allocate.'
              : 'Not available for a patient.'}
          </p>
          <div className="mt-auto space-y-2 pt-3">
            {can.admit && bed.state === 'available' && (
              <Link
                href={`/wards/requests?bed=${bed.bed}`}
                className="block text-[12px] font-semibold text-accent hover:underline"
              >
                Admit into this bed →
              </Link>
            )}
            {can.manage_beds && (
              <>
                {!showState ? (
                  <button
                    type="button"
                    onClick={() => setShowState(true)}
                    className="text-[12px] font-medium text-ink-muted hover:text-ink"
                  >
                    Change availability
                  </button>
                ) : (
                  <div className="space-y-2">
                    {conflict && (
                      <p role="alert" className="text-[11.5px] font-medium text-critical">
                        {conflict}
                      </p>
                    )}
                    <Field label="Note" hint="Shown on the board.">
                      <Input
                        value={note}
                        onChange={(event) => setNote(event.target.value)}
                        placeholder="Terminal clean, broken rail…"
                      />
                    </Field>
                    <div className="flex flex-wrap gap-1.5">
                      {(['available', 'reserved', 'cleaning', 'maintenance'] as const)
                        .filter((state) => state !== bed.state)
                        .map((state) => (
                          <Button
                            key={state}
                            variant="secondary"
                            className="px-2.5 py-1.5 text-[11.5px]"
                            disabled={setState.isPending}
                            onClick={() =>
                              setState.mutate(
                                { id: bed.bed, service_state: state, note },
                                { onSuccess: () => setShowState(false) },
                              )
                            }
                          >
                            {bedLabel(state)}
                          </Button>
                        ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
