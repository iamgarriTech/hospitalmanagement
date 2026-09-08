'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { DrugChart } from '@/components/ward/DrugChart'
import { NursingRecord } from '@/components/ward/NursingRecord'
import { DischargePanel } from '@/components/ward/DischargePanel'
import { ErrorNotice, LoadingNotice, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Panel, PanelHeader, Select } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useImagingOrders } from '@/lib/imaging'
import {
  type AdmissionRow,
  useAdmission,
  useBeds,
  useTransfer,
  useWards,
} from '@/lib/inpatient'
import { useLabOrders } from '@/lib/queries'
import {
  admissionLabel,
  admissionTone,
  dateAndTime,
  imagingLabel,
  imagingTone,
  labLabel,
  labTone,
} from '@/lib/workflow'

/**
 * One patient's stay.
 *
 * The tabs are the things a ward round actually asks for in turn — where they
 * are, what their observations are doing, whether the drugs are going in, what
 * the nurses have written, what has come back from the lab and radiology, and
 * whether they can go home. Tab-gated queries, because loading all of it on
 * mount is what made the outpatient profile take three seconds in Phase 1.
 */
const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'mar', label: 'Drug chart' },
  { key: 'nursing', label: 'Nursing' },
  { key: 'investigations', label: 'Investigations' },
  { key: 'discharge', label: 'Discharge' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function AdmissionPage() {
  const params = useParams<{ id: string }>()
  const admissionId = Number(params.id)
  const admission = useAdmission(Number.isFinite(admissionId) ? admissionId : null)
  const [tab, setTab] = useState<TabKey>('overview')

  if (admission.isLoading) {
    return (
      <PageShell>
        <LoadingNotice>Loading the stay…</LoadingNotice>
      </PageShell>
    )
  }
  if (admission.isError || !admission.data) {
    return (
      <PageShell>
        <ErrorNotice>
          That admission could not be loaded. It may belong to another facility.
        </ErrorNotice>
        <Link href="/wards" className="text-[13px] font-semibold text-accent">
          ← Back to the bed board
        </Link>
      </PageShell>
    )
  }

  const stay = admission.data

  return (
    <PageShell>
      <Link href="/wards" className="text-[12.5px] font-medium text-ink-muted hover:text-ink">
        ← Bed board
      </Link>

      <StayHeader stay={stay} />

      <div
        className="mb-5 flex flex-wrap gap-1 border-b border-border"
        role="tablist"
        aria-label="Stay sections"
      >
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            onClick={() => setTab(entry.key)}
            className={`-mb-px border-b-2 px-3.5 py-2.5 text-[13px] font-semibold transition-colors ${
              tab === entry.key
                ? 'border-accent text-accent'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <Overview stay={stay} />}
      {tab === 'mar' && <DrugChart admissionId={stay.id} />}
      {tab === 'nursing' && <NursingRecord admissionId={stay.id} />}
      {tab === 'investigations' && <Investigations stay={stay} />}
      {tab === 'discharge' && <DischargePanel stay={stay} />}
    </PageShell>
  )
}

function StayHeader({ stay }: { stay: AdmissionRow }) {
  const patient = stay.patient_detail
  return (
    <header className="my-4 rounded-2xl border border-border bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/patients/${stay.patient}`}
              className="text-[19px] font-semibold tracking-tight text-ink hover:text-accent"
            >
              {patient.full_name}
            </Link>
            <Badge tone={admissionTone(stay.status)}>{admissionLabel(stay.status)}</Badge>
          </div>
          <p className="mt-1 text-[12.5px] text-ink-muted">
            {patient.hospital_number} · {patient.sex}
            {patient.age_years !== null && ` · ${patient.age_years}y`} ·{' '}
            {stay.admission_number}
          </p>
          <p className="mt-2 text-[13px] text-ink">{stay.admission_diagnosis}</p>
          <p className="mt-0.5 text-[11.5px] text-ink-faint">
            Under {stay.consultant_name} · admitted {dateAndTime(stay.admitted_at)} by{' '}
            {stay.admitted_by_name}
          </p>
        </div>
        <div className="text-right">
          <p className="text-[26px] leading-none font-semibold tracking-tight text-ink">
            {stay.bed ? stay.bed.label : '—'}
          </p>
          <p className="mt-1.5 text-[11.5px] text-ink-muted">
            {stay.bed ? stay.bed.ward_name : 'No bed — discharged'}
          </p>
          <p className="mt-1 text-[11.5px] text-ink-faint">
            {stay.length_of_stay_nights === 0
              ? 'Day 1'
              : `Night ${stay.length_of_stay_nights}`}
          </p>
        </div>
      </div>

      {stay.allergies.length > 0 ? (
        <p className="mt-4 rounded-md bg-critical-muted px-3 py-2 text-[12.5px] font-semibold text-critical">
          <span aria-hidden>▲ </span>
          Allergic to {stay.allergies.join(', ')}
        </p>
      ) : (
        <p className="mt-4 text-[11.5px] text-ink-faint">No allergies recorded.</p>
      )}
    </header>
  )
}

function Overview({ stay }: { stay: AdmissionRow }) {
  const { can } = useAuth()
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Panel>
        <PanelHeader
          title="Reason for admission"
          hint="As written by the clinician who asked for the bed."
        />
        <div className="space-y-4 p-5 text-[13px]">
          <p className="leading-relaxed text-ink">{stay.admission_reason}</p>
          {stay.visit !== null && (
            <p className="text-[11.5px] text-ink-faint">
              Admitted from an outpatient attendance, which closed as admitted.
            </p>
          )}
          {stay.discharged_at && (
            <div className="rounded-lg bg-surface-muted/60 p-3">
              <p className="text-[11.5px] font-semibold text-ink-muted">
                Discharged {dateAndTime(stay.discharged_at)} by {stay.discharged_by_name}
              </p>
              <p className="mt-1 text-ink">{stay.discharge_diagnosis}</p>
              <p className="mt-1 text-[11.5px] text-ink-muted">
                To {stay.destination_display}
              </p>
              {stay.billing_override_reason && (
                <p className="mt-2 text-[11.5px] font-medium text-critical">
                  Discharged with an unsettled bill: {stay.billing_override_reason}
                </p>
              )}
            </div>
          )}
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title="Where this patient has been"
          hint="Every bed and ward, in order, reconstructed from the stay itself."
        />
        <div className="p-5">
          {stay.movement.length === 0 ? (
            <EmptyState>No bed has been allocated.</EmptyState>
          ) : (
            <ol className="space-y-3">
              {stay.movement.map((leg, index) => (
                <li key={`${leg.bed}-${leg.from}`} className="flex gap-3">
                  <span
                    aria-hidden
                    className={`mt-1 size-2 shrink-0 rounded-full ${
                      leg.to === null ? 'bg-accent' : 'bg-border-strong'
                    }`}
                  />
                  <div className="min-w-0 text-[13px]">
                    <p className="font-semibold text-ink">
                      {leg.bed}
                      <span className="ml-2 font-normal text-ink-muted">{leg.ward}</span>
                    </p>
                    <p className="mt-0.5 text-[11.5px] text-ink-muted">
                      {dateAndTime(leg.from)} —{' '}
                      {leg.to ? dateAndTime(leg.to) : 'still here'} ·{' '}
                      {leg.nights} night{leg.nights === 1 ? '' : 's'}
                    </p>
                    {stay.transfers[index - 1]?.reason && index > 0 && (
                      <p className="mt-0.5 text-[11.5px] text-ink-faint">
                        Moved: {stay.transfers[index - 1].reason} (
                        {stay.transfers[index - 1].authorised_by_name})
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </Panel>

      {can('inpatient.transfer_patient') && stay.status !== 'discharged' && stay.bed && (
        <TransferPanel stay={stay} />
      )}
    </div>
  )
}

function TransferPanel({ stay }: { stay: AdmissionRow }) {
  const wards = useWards()
  const transfer = useTransfer()
  const [wardId, setWardId] = useState<number | null>(stay.bed?.ward ?? null)
  const beds = useBeds(
    wardId ? { ward: String(wardId), state: 'available' } : { state: 'available' },
  )
  const [bedId, setBedId] = useState<number | null>(null)
  const [reason, setReason] = useState('')

  const error =
    transfer.error instanceof ApiError
      ? Object.values(transfer.error.fields).flat().join(' ') || transfer.error.message
      : null

  return (
    <Panel className="lg:col-span-2">
      <PanelHeader
        title="Move this patient"
        hint="The old bed closes and the new one opens together, so the patient is never in two beds and never in none."
      />
      <div className="p-5">
        {error && <ErrorNotice>{error}</ErrorNotice>}
        {transfer.isSuccess && (
          <p className="mb-4 rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            Moved.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Ward">
            <Select
              value={wardId ?? ''}
              onChange={(event) => {
                setWardId(event.target.value ? Number(event.target.value) : null)
                setBedId(null)
              }}
            >
              {wards.data?.map((ward) => (
                <option key={ward.id} value={ward.id}>
                  {ward.name} — {ward.occupancy.available} free
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Bed"
            hint="Occupied beds are not listed; the database refuses them anyway."
            required
          >
            <Select
              value={bedId ?? ''}
              onChange={(event) =>
                setBedId(event.target.value ? Number(event.target.value) : null)
              }
            >
              <option value="">Choose a bed…</option>
              {(beds.data ?? [])
                .filter((bed) => bed.id !== stay.bed?.id)
                .map((bed) => (
                  <option key={bed.id} value={bed.id}>
                    {bed.label} (room {bed.room_code})
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Reason" hint="Recorded against the move." required>
            <Select value={reason} onChange={(event) => setReason(event.target.value)}>
              <option value="">Choose…</option>
              <option value="Clinical deterioration — needs closer observation">
                Clinical deterioration
              </option>
              <option value="Stepped down from intensive care">Stepped down</option>
              <option value="Moved closer to the nurses' station">
                Closer to the nurses&apos; station
              </option>
              <option value="Isolation required">Isolation required</option>
              <option value="Bed needed for another patient">Bed needed elsewhere</option>
            </Select>
          </Field>
        </div>
        <Button
          className="mt-4"
          disabled={bedId === null || !reason || transfer.isPending}
          onClick={() =>
            transfer.mutate(
              { id: stay.id, to_bed: bedId as number, reason },
              { onSuccess: () => setBedId(null) },
            )
          }
        >
          {transfer.isPending ? 'Moving…' : 'Move patient'}
        </Button>
      </div>
    </Panel>
  )
}

function Investigations({ stay }: { stay: AdmissionRow }) {
  const labs = useLabOrders({ patient: stay.patient })
  const imaging = useImagingOrders({ admission: String(stay.id) })

  const labRows = (labs.data?.results ?? []).flatMap((order) =>
    order.items.map((item) => ({ order, item })),
  )

  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader
          title="Laboratory"
          hint="The whole patient's history, not only this stay — a result from last month still matters."
        />
        {labRows.length === 0 ? (
          <div className="p-5">
            <EmptyState>Nothing has been requested.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={640}>
            <thead>
              <tr>
                <Th>Test</Th>
                <Th>Requested</Th>
                <Th>Status</Th>
                <Th>Result</Th>
              </tr>
            </thead>
            <tbody>
              {labRows.map(({ order, item }) => (
                <tr key={item.id} className="border-t border-border">
                  <Td>
                    <span className="font-medium text-ink">{item.test_name}</span>
                    {order.admission === stay.id && (
                      <span className="ml-2 text-[10.5px] text-accent">this stay</span>
                    )}
                  </Td>
                  <Td className="text-ink-muted">{dateAndTime(order.ordered_at)}</Td>
                  <Td>
                    <Badge tone={labTone(item.status)}>{labLabel(item.status)}</Badge>
                  </Td>
                  <Td>
                    <Link
                      href={`/patients/${stay.patient}`}
                      className="text-[12px] font-semibold text-accent hover:underline"
                    >
                      View
                    </Link>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      <Panel>
        <PanelHeader
          title="Imaging"
          hint="A report reaches you when the radiologist has verified it, not before."
        />
        {(imaging.data ?? []).length === 0 ? (
          <div className="p-5">
            <EmptyState>No imaging has been requested for this stay.</EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {imaging.data?.map((order) =>
              order.items.map((item) => (
                <li key={item.id} className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[13.5px] font-semibold text-ink">
                        {item.procedure_name}
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-ink-muted">
                        {order.order_number} · {item.modality} · requested{' '}
                        {dateAndTime(order.ordered_at)}
                      </p>
                      <p className="mt-1.5 text-[12.5px] text-ink">
                        <span className="text-ink-muted">Question: </span>
                        {order.clinical_question}
                      </p>
                    </div>
                    <Badge tone={imagingTone(item.status)}>
                      {imagingLabel(item.status)}
                    </Badge>
                  </div>

                  {item.report === null ? (
                    <p className="mt-3 text-[12px] text-ink-faint">No report yet.</p>
                  ) : 'awaiting_verification' in item.report ? (
                    <p className="mt-3 rounded-md bg-surface-muted px-3 py-2 text-[12px] text-ink-muted">
                      A report has been written and is not verified yet, so it is not
                      released. The department will release it once a radiologist has
                      signed it off.
                    </p>
                  ) : (
                    <div className="mt-3 rounded-lg bg-surface-muted/60 p-3 text-[12.5px]">
                      {item.report.is_amended && (
                        <p className="mb-1.5 text-[11px] font-bold tracking-wide text-abnormal uppercase">
                          {item.report.status_label}
                        </p>
                      )}
                      {item.report.is_critical && (
                        <p className="mb-2 rounded bg-critical-muted px-2 py-1 text-[11.5px] font-bold text-critical">
                          <span aria-hidden>▲ </span>
                          {item.report.critical_finding}
                        </p>
                      )}
                      <p className="font-semibold text-ink">{item.report.conclusion}</p>
                      <p className="mt-1.5 leading-relaxed text-ink-muted">
                        {item.report.findings}
                      </p>
                      <p className="mt-2 text-[11px] text-ink-faint">
                        Reported by {item.report.reported_by_name}
                        {item.report.verified_by_name &&
                          `, verified by ${item.report.verified_by_name}`}
                      </p>
                    </div>
                  )}
                </li>
              )),
            )}
          </ul>
        )}
      </Panel>
    </div>
  )
}
