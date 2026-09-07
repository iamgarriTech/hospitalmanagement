'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { PatientHeader } from '@/components/PatientHeader'
import { Badge, ClinicalFlag, EmptyState, Panel, PanelHeader } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import {
  useAccessLog, useCheckIn, useEncounters, useInvoices, useLabOrders, usePatient,
  usePrescriptions, useVitalsTrend, useVisitsForPatient,
} from '@/lib/queries'
import {
  dateAndTime, dispenseLabel, dispenseTone, invoiceLabel, invoiceTone, labLabel, labTone,
  money, queueLabel, queueTone,
} from '@/lib/workflow'

/**
 * The unified patient record.
 *
 * The point of this screen is that the whole visit is reconstructable from it
 * afterwards: what was recorded, by whom, what was ordered, what came back,
 * what was dispensed and what was paid. Sections are tabs rather than one long
 * scroll because clinicians arrive here looking for one specific thing.
 */

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'encounters', label: 'Consultations' },
  { key: 'vitals', label: 'Vitals' },
  { key: 'laboratory', label: 'Laboratory' },
  { key: 'medication', label: 'Medication' },
  { key: 'billing', label: 'Billing' },
  { key: 'access', label: 'Who accessed this' },
]

export default function PatientPage() {
  const params = useParams<{ id: string }>()
  const patientId = Number(params.id)
  const { can } = useAuth()
  const [tab, setTab] = useState('overview')

  const patient = usePatient(Number.isFinite(patientId) ? patientId : null)
  const visits = useVisitsForPatient(patientId)
  const encounters = useEncounters({ patient: patientId, enabled: can('clinical.view_encounter') })
  const vitals = useVitalsTrend(patientId, can('clinical.view_vitalsigns'))
  const labs = useLabOrders({ patient: patientId, enabled: can('laboratory.view_laborder') })
  const prescriptions = usePrescriptions({
    patient: patientId,
    enabled: can('pharmacy.view_prescription'),
  })
  const invoices = useInvoices({ patient: patientId, enabled: can('billing.view_invoice') })
  const accessLog = useAccessLog(
    patientId,
    can('patients.view_patient_access_log') && tab === 'access',
  )

  if (patient.isLoading) {
    return (
      <PageShell>
        <p role="status" className="py-10 text-[13px] text-ink-muted">
          Loading the patient record…
        </p>
      </PageShell>
    )
  }

  if (patient.isError || !patient.data) {
    return (
      <PageShell>
        <Panel className="p-5">
          <p role="alert" className="text-[13px] text-ink-muted">
            This patient record is not available to you. It may not exist, or it may belong to
            another facility.
          </p>
          <Link href="/patients" className="mt-3 inline-block text-[13px] font-semibold text-accent">
            Back to patient search
          </Link>
        </Panel>
      </PageShell>
    )
  }

  const record = patient.data
  const openVisit = (visits.data?.results ?? []).find(
    (visit) => !['completed', 'cancelled'].includes(visit.status),
  )
  const visibleTabs = TABS.filter((entry) => {
    if (entry.key === 'access') return can('patients.view_patient_access_log')
    if (entry.key === 'encounters') return can('clinical.view_encounter')
    if (entry.key === 'vitals') return can('clinical.view_vitalsigns')
    if (entry.key === 'laboratory') return can('laboratory.view_laborder')
    if (entry.key === 'medication') return can('pharmacy.view_prescription')
    if (entry.key === 'billing') return can('billing.view_invoice')
    return true
  })

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Patient record
      </div>

      <PatientHeader
        patient={record}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {openVisit ? (
              <Link
                href="/queue"
                className="inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[12.5px] font-medium text-ink hover:bg-surface-muted"
              >
                <Badge tone={queueTone(openVisit.status)}>{queueLabel(openVisit.status)}</Badge>
                <span className="font-mono text-[11.5px]">{openVisit.visit_number}</span>
              </Link>
            ) : (
              can('visits.check_in_patient') && (
                <CheckInButton patientId={record.id} facilityId={record.facility} />
              )
            )}
          </div>
        }
      />

      <div
        className="mt-5 -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0"
        role="tablist"
        aria-label="Patient record sections"
      >
        {visibleTabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            onClick={() => setTab(entry.key)}
            className={`shrink-0 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
              tab === entry.key
                ? 'bg-accent text-white'
                : 'bg-surface text-ink-muted hover:bg-surface-muted hover:text-ink'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="mt-4 grid gap-5">
        {tab === 'overview' && (
          <>
            <div className="grid gap-5 xl:grid-cols-2">
              <Panel>
                <PanelHeader title="Contact" />
                <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 p-5 text-[12.5px]">
                  <Detail label="Phone" value={record.phone_primary} />
                  <Detail label="Alternate" value={record.phone_alternate} />
                  <Detail label="Email" value={record.email} />
                  <Detail
                    label="Address"
                    value={[record.address_line, record.city, record.state, record.country]
                      .filter(Boolean)
                      .join(', ')}
                  />
                  <Detail label="Registered" value={dateAndTime(record.created_at)} />
                </dl>
              </Panel>

              <Panel>
                <PanelHeader title="Next of kin" />
                {record.next_of_kin.length === 0 ? (
                  <div className="p-5">
                    <EmptyState>No next of kin recorded.</EmptyState>
                  </div>
                ) : (
                  <ul className="divide-y divide-border">
                    {record.next_of_kin.map((kin) => (
                      <li key={kin.id} className="p-5">
                        <p className="text-[13px] font-semibold text-ink">{kin.full_name}</p>
                        <p className="mt-0.5 text-[12px] text-ink-muted">
                          {kin.relationship}
                          {kin.phone && ` · ${kin.phone}`}
                          {kin.is_emergency_contact && (
                            <span className="ml-2 text-[11px] font-semibold text-accent">
                              Emergency contact
                            </span>
                          )}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>

            <Panel>
              <PanelHeader title="Chronic conditions" />
              {record.chronic_conditions.filter((entry) => entry.is_active).length === 0 ? (
                <div className="p-5">
                  <EmptyState>None recorded.</EmptyState>
                </div>
              ) : (
                <ul className="flex flex-wrap gap-2 p-5">
                  {record.chronic_conditions
                    .filter((entry) => entry.is_active)
                    .map((entry) => (
                      <li key={entry.id}>
                        <Badge tone="progress">{entry.condition}</Badge>
                      </li>
                    ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader title="Visits" hint="Most recent first" />
              {(visits.data?.results ?? []).length === 0 ? (
                <div className="p-5">
                  <EmptyState>This patient has not attended yet.</EmptyState>
                </div>
              ) : (
                <TableFrame minWidth={620}>
                  <thead>
                    <tr>
                      <Th>Visit</Th>
                      <Th>Arrived</Th>
                      <Th>Reason</Th>
                      <Th>Status</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(visits.data?.results ?? [])]
                      .sort((a, b) => b.arrived_at.localeCompare(a.arrived_at))
                      .map((visit) => (
                        <tr key={visit.id}>
                          <Td className="font-mono text-[11.5px]">{visit.visit_number}</Td>
                          <Td className="text-ink-muted">{dateAndTime(visit.arrived_at)}</Td>
                          <Td className="text-[12px] text-ink-muted">{visit.reason || '—'}</Td>
                          <Td>
                            <Badge tone={queueTone(visit.status)}>{queueLabel(visit.status)}</Badge>
                          </Td>
                        </tr>
                      ))}
                  </tbody>
                </TableFrame>
              )}
            </Panel>
          </>
        )}

        {tab === 'encounters' && (
          <Panel>
            <PanelHeader title="Consultations" hint="Amendments keep the earlier version" />
            {(encounters.data?.results ?? []).length === 0 ? (
              <div className="p-5">
                <EmptyState>No consultations recorded.</EmptyState>
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {encounters.data!.results.map((encounter) => (
                  <li key={encounter.id} className="p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-[13px] font-semibold text-ink capitalize">
                          {encounter.encounter_type} · {dateAndTime(encounter.started_at)}
                        </p>
                        <p className="mt-0.5 text-[11.5px] text-ink-faint">
                          {encounter.clinician_email}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {encounter.status === 'amended' && (
                          <Badge tone="abnormal">
                            Amended · {encounter.version_count} versions
                          </Badge>
                        )}
                        {encounter.status === 'final' && <Badge tone="normal">Final</Badge>}
                        {encounter.status === 'draft' && <Badge tone="idle">Draft</Badge>}
                        <Link
                          href={`/clinic/${encounter.id}`}
                          className="text-[12px] font-semibold text-accent hover:underline"
                        >
                          Open
                        </Link>
                      </div>
                    </div>

                    {encounter.current && (
                      <>
                        {encounter.current.diagnoses.length > 0 && (
                          <ul className="mt-3 flex flex-wrap gap-2">
                            {encounter.current.diagnoses.map((diagnosis) => (
                              <li key={diagnosis.id}>
                                <Badge tone={diagnosis.is_primary ? 'accent' : 'idle'}>
                                  {diagnosis.description}
                                  <span className="ml-1 opacity-70">{diagnosis.certainty}</span>
                                </Badge>
                              </li>
                            ))}
                          </ul>
                        )}
                        {encounter.current.presenting_complaint && (
                          <p className="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
                            {encounter.current.presenting_complaint}
                          </p>
                        )}
                        {encounter.current.amendment_reason && (
                          <p className="mt-2 rounded-md bg-abnormal-muted px-3 py-2 text-[12px] text-abnormal">
                            Amended: {encounter.current.amendment_reason}
                          </p>
                        )}
                      </>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {tab === 'vitals' && <VitalsPanel series={vitals.data} loading={vitals.isLoading} />}

        {tab === 'laboratory' && (
          <>
            {(labs.data?.results ?? []).length === 0 ? (
              <Panel className="p-5">
                <EmptyState>No investigations requested.</EmptyState>
              </Panel>
            ) : (
              labs.data!.results.map((order) => (
                <Panel key={order.id}>
                  <PanelHeader
                    title={`${order.order_number} · ${dateAndTime(order.ordered_at)}`}
                    hint={`Requested by ${order.ordered_by_email}${
                      order.clinical_details ? ` — ${order.clinical_details}` : ''
                    }`}
                    action={order.priority === 'urgent' ? <Badge tone="critical">Urgent</Badge> : null}
                  />
                  {order.items.map((item) => (
                    <div key={item.id} className="border-b border-border last:border-b-0">
                      <div className="flex flex-wrap items-center justify-between gap-2 bg-surface-muted/40 px-5 py-2.5">
                        <p className="text-[12.5px] font-semibold text-ink">{item.test_name}</p>
                        <div className="flex items-center gap-2">
                          {item.specimen && (
                            <span className="font-mono text-[11px] text-ink-faint">
                              {item.specimen.specimen_id}
                            </span>
                          )}
                          <Badge tone={labTone(item.status)}>{labLabel(item.status)}</Badge>
                        </div>
                      </div>
                      {item.results.length > 0 && (
                        <TableFrame minWidth={620}>
                          <thead>
                            <tr>
                              <Th>Measurement</Th>
                              <Th className="text-right">Result</Th>
                              <Th>Flag</Th>
                              <Th>Reference</Th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.results.map((result) => (
                              <tr key={result.id}>
                                <Td>{result.parameter_name}</Td>
                                <Td
                                  className={`text-right font-semibold ${
                                    result.is_critical
                                      ? 'text-critical'
                                      : result.is_abnormal
                                        ? 'text-abnormal'
                                        : ''
                                  }`}
                                >
                                  {result.display_value} {result.unit}
                                </Td>
                                <Td>
                                  <ClinicalFlag flag={result.flag} label={result.flag_label} />
                                </Td>
                                <Td className="text-ink-muted">{result.reference_text || '—'}</Td>
                              </tr>
                            ))}
                          </tbody>
                        </TableFrame>
                      )}
                      {item.superseded_results.length > 0 && (
                        <div className="border-t border-border bg-abnormal-muted/40 px-5 py-2.5">
                          <p className="text-[11px] font-bold tracking-wide text-abnormal uppercase">
                            Superseded values
                          </p>
                          {item.superseded_results.map((result) => (
                            <p key={result.id} className="mt-1 text-[12px] text-ink-muted">
                              <span className="line-through">
                                {result.parameter_name} {result.display_value} {result.unit}
                              </span>
                              {result.amendment_reason && ` — ${result.amendment_reason}`}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </Panel>
              ))
            )}
          </>
        )}

        {tab === 'medication' && (
          <>
            {(prescriptions.data?.results ?? []).length === 0 ? (
              <Panel className="p-5">
                <EmptyState>Nothing prescribed.</EmptyState>
              </Panel>
            ) : (
              prescriptions.data!.results.map((prescription) => (
                <Panel key={prescription.id}>
                  <PanelHeader
                    title={`${prescription.prescription_number} · ${dateAndTime(
                      prescription.prescribed_at,
                    )}`}
                    hint={`Prescribed by ${prescription.prescribed_by_email}`}
                    action={
                      <Badge tone={dispenseTone(prescription.status)}>
                        {dispenseLabel(prescription.status)}
                      </Badge>
                    }
                  />
                  <TableFrame minWidth={720}>
                    <thead>
                      <tr>
                        <Th>Medication</Th>
                        <Th>Directions</Th>
                        <Th className="text-right">Prescribed</Th>
                        <Th className="text-right">Dispensed</Th>
                        <Th>Status</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {prescription.items.map((item) => (
                        <tr key={item.id}>
                          <Td className="font-medium">{item.medication_label}</Td>
                          <Td className="text-[12px] text-ink-muted">
                            {Number(item.dose)} {item.dose_unit} · {item.route} ·{' '}
                            {item.frequency_per_day}×/day · {item.duration_days} days
                            {item.instructions && (
                              <div className="mt-0.5 text-ink-faint">{item.instructions}</div>
                            )}
                            {item.overrides.length > 0 && (
                              <div className="mt-1.5 rounded-md bg-critical-muted px-2 py-1 text-[11px] font-medium text-critical">
                                Safety warning overridden ({item.overrides[0].kind}):{' '}
                                {item.overrides[0].reason}
                              </div>
                            )}
                          </Td>
                          <Td className="text-right">{item.quantity_prescribed}</Td>
                          <Td className="text-right">{item.quantity_dispensed}</Td>
                          <Td>
                            <Badge tone={dispenseTone(item.status)}>
                              {dispenseLabel(item.status)}
                            </Badge>
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </TableFrame>
                </Panel>
              ))
            )}
          </>
        )}

        {tab === 'billing' && (
          <>
            {(invoices.data?.results ?? []).length === 0 ? (
              <Panel className="p-5">
                <EmptyState>No invoices.</EmptyState>
              </Panel>
            ) : (
              invoices.data!.results.map((invoice) => (
                <Panel key={invoice.id}>
                  <PanelHeader
                    title={`${invoice.invoice_number} · ${dateAndTime(invoice.created_at)}`}
                    hint={`Total ${money(invoice.total)} · paid ${money(
                      invoice.amount_paid,
                    )} · balance ${money(invoice.balance)}`}
                    action={
                      <div className="flex items-center gap-2">
                        <Badge tone={invoiceTone(invoice.status)}>
                          {invoiceLabel(invoice.status)}
                        </Badge>
                        <Link
                          href={`/billing/${invoice.id}`}
                          className="text-[12px] font-semibold text-accent hover:underline"
                        >
                          Open
                        </Link>
                      </div>
                    }
                  />
                  <TableFrame minWidth={620}>
                    <thead>
                      <tr>
                        <Th>Charge</Th>
                        <Th className="text-right">Qty</Th>
                        <Th className="text-right">Unit</Th>
                        <Th className="text-right">Amount</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {invoice.items.map((item) => (
                        <tr key={item.id} className={item.is_cancelled ? 'opacity-50' : ''}>
                          <Td className={item.is_cancelled ? 'line-through' : ''}>
                            {item.description}
                          </Td>
                          <Td className="text-right">{item.quantity}</Td>
                          <Td className="text-right text-ink-muted">{money(item.unit_price)}</Td>
                          <Td className="text-right font-semibold">{money(item.amount)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </TableFrame>
                </Panel>
              ))
            )}
          </>
        )}

        {tab === 'access' && (
          <Panel>
            <PanelHeader
              title="Who accessed this record"
              hint="Every view, change and refusal, most recent first"
            />
            {accessLog.isLoading ? (
              <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
                Loading…
              </p>
            ) : (accessLog.data ?? []).length === 0 ? (
              <div className="p-5">
                <EmptyState>No recorded access.</EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={720}>
                <thead>
                  <tr>
                    <Th>When</Th>
                    <Th>Who</Th>
                    <Th>Action</Th>
                    <Th>Outcome</Th>
                    <Th>Reason</Th>
                  </tr>
                </thead>
                <tbody>
                  {accessLog.data!.map((entry) => (
                    <tr key={entry.id}>
                      <Td className="text-ink-muted">{dateAndTime(entry.occurred_at)}</Td>
                      <Td>{entry.actor || <span className="text-ink-faint">anonymous</span>}</Td>
                      <Td className="font-mono text-[11.5px]">{entry.action}</Td>
                      <Td>
                        {entry.outcome === 'denied' ? (
                          <Badge tone="critical">Refused</Badge>
                        ) : (
                          <Badge tone="normal">Allowed</Badge>
                        )}
                      </Td>
                      <Td className="text-[12px] text-ink-muted">{entry.reason || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
          </Panel>
        )}
      </div>
    </PageShell>
  )
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-ink">{value || <span className="text-ink-faint">—</span>}</dd>
    </>
  )
}

/**
 * A minimal sparkline table. Deliberately not a charting library: what a
 * clinician needs from a trend is the numbers in order with the direction
 * visible, and a dependency for that is not worth carrying.
 */
function VitalsPanel({
  series,
  loading,
}: {
  series?: Record<string, { at: string; value: number }[]>
  loading: boolean
}) {
  const LABELS: Record<string, string> = {
    temperature_c: 'Temperature (°C)',
    systolic_bp: 'Systolic BP (mmHg)',
    diastolic_bp: 'Diastolic BP (mmHg)',
    pulse_bpm: 'Pulse (bpm)',
    respiratory_rate: 'Respiratory rate',
    oxygen_saturation: 'SpO₂ (%)',
    weight_kg: 'Weight (kg)',
    bmi: 'BMI',
    blood_glucose_mmol: 'Glucose (mmol/L)',
    pain_score: 'Pain score',
  }
  const entries = Object.entries(series ?? {})

  return (
    <Panel>
      <PanelHeader title="Vital signs" hint="Oldest first" />
      {loading ? (
        <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
          Loading…
        </p>
      ) : entries.length === 0 ? (
        <div className="p-5">
          <EmptyState>No observations recorded.</EmptyState>
        </div>
      ) : (
        <div className="grid gap-x-8 gap-y-5 p-5 sm:grid-cols-2">
          {entries.map(([key, points]) => {
            const latest = points[points.length - 1]
            const previous = points[points.length - 2]
            const direction = previous
              ? latest.value > previous.value
                ? '▲'
                : latest.value < previous.value
                  ? '▼'
                  : '='
              : ''
            return (
              <div key={key}>
                <p className="text-[11.5px] text-ink-muted">{LABELS[key] ?? key}</p>
                <p className="mt-1 flex items-baseline gap-2">
                  <span className="text-[20px] leading-none font-semibold text-ink">
                    {latest.value}
                  </span>
                  {direction && (
                    <span className="text-[12px] text-ink-faint">
                      {direction} from {previous.value}
                    </span>
                  )}
                </p>
                <p className="mt-1 font-mono text-[11px] text-ink-faint">
                  {points.map((point) => point.value).join(' · ')}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}

function CheckInButton({ patientId, facilityId }: { patientId: number; facilityId: number }) {
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const checkIn = useCheckIn()

  async function submit() {
    setError(null)
    try {
      await checkIn.mutateAsync({
        patient: patientId,
        facility: facilityId,
        visit_type: 'walk_in',
        reason,
      })
      setOpen(false)
      setReason('')
    } catch {
      setError('Could not check this patient in. They may already have an open visit.')
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
      >
        Check in
      </button>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        autoFocus
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Reason for visit"
        className="rounded-lg border border-border bg-surface px-2.5 py-2 text-[12.5px]"
      />
      <button
        type="button"
        onClick={submit}
        disabled={checkIn.isPending}
        className="rounded-lg bg-accent px-3 py-2 text-[12.5px] font-semibold text-white disabled:opacity-60"
      >
        {checkIn.isPending ? 'Checking in…' : 'Confirm'}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-lg border border-border px-3 py-2 text-[12.5px] text-ink"
      >
        Cancel
      </button>
      {error && <p className="text-[12px] text-critical">{error}</p>}
    </div>
  )
}
