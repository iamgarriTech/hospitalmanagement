'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Badge, Button, EmptyState, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useOpenEncounter } from '@/lib/clinical'
import { type QueueRow, useEncounters, useQueue } from '@/lib/queries'
import { dateAndTime, queueLabel, queueTone, waitedFor } from '@/lib/workflow'

/**
 * The clinician's starting point: who is in front of me, and what have I
 * written recently.
 *
 * Opening a consultation from here creates the encounter and goes straight to
 * it — a clinician with a patient sitting down should not have to fill in a
 * form about which patient they are seeing.
 */
export default function ClinicPage() {
  const { can } = useAuth()
  const router = useRouter()
  const queue = useQueue({ status: 'called,in_consultation,sent_for_investigation' })
  const mine = useEncounters({ enabled: can('clinical.view_encounter') })
  const open = useOpenEncounter()
  const [error, setError] = useState<string | null>(null)
  const [busyVisit, setBusyVisit] = useState<number | null>(null)

  const rows = queue.data ?? []
  const encounters = mine.data?.results ?? []

  async function startConsultation(row: QueueRow) {
    setError(null)
    setBusyVisit(row.id)
    try {
      const encounter = await open.mutateAsync({ visit: row.id })
      router.push(`/clinic/${encounter.id}`)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not open a consultation. Nothing was recorded.',
      )
      setBusyVisit(null)
    }
  }

  /** An encounter already open for this visit — resume it rather than start a
   *  second one for the same attendance. */
  function existingFor(visitId: number) {
    return encounters.find(
      (encounter) => encounter.visit === visitId && encounter.status === 'draft',
    )
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Clinic
      </div>
      <PageHeading
        title="Consultations"
        subtitle="Patients called through, and the records you have written."
        action={
          <div className="flex gap-2">
            {can('clinical.add_vitalsigns') && (
              <Link
                href="/clinic/vitals"
                className="inline-flex items-center rounded-lg border border-border px-3 py-2 text-[13px] font-medium text-ink hover:bg-surface-muted"
              >
                Record vitals
              </Link>
            )}
            <Button variant="secondary" onClick={() => queue.refetch()} disabled={queue.isFetching}>
              {queue.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.1fr_1fr]">
        <Panel>
          <PanelHeader title="With me now" hint="Called through, in consultation, or back from the laboratory" />
          {queue.isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
              Loading…
            </p>
          ) : rows.length === 0 ? (
            <div className="p-5">
              <EmptyState>
                Nobody has been called through yet. Patients appear here once reception calls
                them.
              </EmptyState>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map((row) => {
                const existing = existingFor(row.id)
                return (
                  <li key={row.id} className="flex flex-wrap items-start justify-between gap-3 p-5">
                    <div className="min-w-0">
                      <Link
                        href={`/patients/${row.patient.id}`}
                        className="text-[14px] font-semibold text-ink hover:text-accent hover:underline"
                      >
                        {row.patient.full_name}
                      </Link>
                      <p className="mt-0.5 text-[11.5px] text-ink-faint">
                        {row.patient.hospital_number}
                        {row.patient.age_years !== null && ` · ${row.patient.age_years}y`}
                        {` · ${row.patient.sex} · waited ${waitedFor(row.waiting_minutes)}`}
                      </p>
                      {row.reason && (
                        <p className="mt-1 text-[12.5px] text-ink-muted">{row.reason}</p>
                      )}
                      {row.allergies.length > 0 && (
                        <p className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-critical-muted px-1.5 py-0.5 text-[10.5px] font-bold text-critical">
                          <AlertIcon className="size-3" />
                          Allergic to {row.allergies.join(', ')}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <Badge tone={queueTone(row.status)}>{queueLabel(row.status)}</Badge>
                      {existing ? (
                        <Link
                          href={`/clinic/${existing.id}`}
                          className="inline-flex items-center rounded-lg bg-accent px-3 py-2 text-[12.5px] font-semibold text-white hover:bg-accent-hover"
                        >
                          Resume draft
                        </Link>
                      ) : (
                        can('clinical.add_encounter') && (
                          <Button
                            onClick={() => startConsultation(row)}
                            disabled={busyVisit === row.id}
                          >
                            {busyVisit === row.id ? 'Opening…' : 'Start consultation'}
                          </Button>
                        )
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Recent records" hint="Drafts first" />
          {mine.isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
              Loading…
            </p>
          ) : encounters.length === 0 ? (
            <div className="p-5">
              <EmptyState>No consultation records yet.</EmptyState>
            </div>
          ) : (
            <ul className="max-h-[620px] divide-y divide-border overflow-y-auto">
              {[...encounters]
                .sort((a, b) =>
                  a.status === b.status ? 0 : a.status === 'draft' ? -1 : 1,
                )
                .map((encounter) => (
                  <li key={encounter.id}>
                    <Link
                      href={`/clinic/${encounter.id}`}
                      className="block px-5 py-3.5 transition-colors hover:bg-surface-muted"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-[13px] font-semibold text-ink">
                          {encounter.patient_name}
                        </span>
                        {encounter.status === 'draft' && <Badge tone="abnormal">Draft</Badge>}
                        {encounter.status === 'final' && <Badge tone="normal">Final</Badge>}
                        {encounter.status === 'amended' && (
                          <Badge tone="progress">Amended ×{encounter.version_count}</Badge>
                        )}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-faint">
                        {dateAndTime(encounter.started_at)} · {encounter.clinician_email}
                      </span>
                      {encounter.current?.diagnoses.length ? (
                        <span className="mt-1 block truncate text-[12px] text-ink-muted">
                          {encounter.current.diagnoses.map((d) => d.description).join(', ')}
                        </span>
                      ) : encounter.current?.presenting_complaint ? (
                        <span className="mt-1 block truncate text-[12px] text-ink-muted">
                          {encounter.current.presenting_complaint}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                ))}
            </ul>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}
