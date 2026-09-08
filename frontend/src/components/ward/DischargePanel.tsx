'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ErrorNotice, LoadingNotice } from '@/components/PageShell'
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type AdmissionRow,
  useDischarge,
  useDischargeBilling,
  useDischargeSummary,
  usePlanDischarge,
} from '@/lib/inpatient'
import { dateAndTime, invoiceLabel, invoiceTone, money } from '@/lib/workflow'

const DESTINATIONS = [
  { value: 'home', label: 'Home' },
  { value: 'transferred', label: 'Transferred to another facility' },
  { value: 'absconded', label: 'Absconded' },
  { value: 'died', label: 'Died' },
]

/**
 * Planning a discharge, settling the stay, and completing it.
 *
 * The billing gate is shown as a list of what is still outstanding rather than
 * a disabled button with no explanation. A ward told "cannot discharge" and
 * nothing else has nowhere to go; a ward told which invoice is still a draft
 * can send the patient to the cash desk.
 */
export function DischargePanel({ stay }: { stay: AdmissionRow }) {
  const { can } = useAuth()
  const discharged = stay.status === 'discharged'

  return (
    <div className="space-y-5">
      {!discharged && can('inpatient.plan_discharge') && <PlanPanel stay={stay} />}
      {!discharged && <SettlePanel stay={stay} />}
      {!discharged && can('inpatient.discharge_patient') && <CompletePanel stay={stay} />}
      {discharged && <Summary stay={stay} />}
    </div>
  )
}

function PlanPanel({ stay }: { stay: AdmissionRow }) {
  const plan = usePlanDischarge()
  const [date, setDate] = useState(stay.expected_discharge_date ?? '')
  const [destination, setDestination] = useState(stay.discharge_destination || 'home')
  const [notes, setNotes] = useState(stay.discharge_plan_notes ?? '')

  return (
    <Panel>
      <PanelHeader
        title="Discharge plan"
        hint="Recorded before the discharge itself: the plan is what the ward, pharmacy and cash desk work towards."
        action={
          stay.status === 'discharge_planned' ? (
            <Badge tone="progress">Planned</Badge>
          ) : undefined
        }
      />
      <div className="space-y-4 p-5">
        {plan.error instanceof ApiError && <ErrorNotice>{plan.error.message}</ErrorNotice>}
        {plan.isSuccess && (
          <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            Plan recorded. This stay now appears on the ward&apos;s discharge list.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Expected date" hint="Leave blank if it is not known yet.">
            <Input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </Field>
          <Field label="Destination">
            <Select
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
            >
              {DESTINATIONS.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field
          label="What has to happen first"
          hint="Read by the pharmacy and the cash desk."
        >
          <Textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Needs the discharge medication dispensed and a BP diary."
          />
        </Field>
        <Button
          disabled={plan.isPending}
          onClick={() =>
            plan.mutate({
              id: stay.id,
              expected_date: date || null,
              destination,
              notes,
            })
          }
        >
          {plan.isPending ? 'Saving…' : 'Record the plan'}
        </Button>
      </div>
    </Panel>
  )
}

function SettlePanel({ stay }: { stay: AdmissionRow }) {
  /* Reading this endpoint is also what charges the nights: the check does the
     charging, so it cannot pass and then bill a patient who has gone home. */
  const billing = useDischargeBilling(stay.id)
  const data = billing.data

  return (
    <Panel>
      <PanelHeader
        title="What still has to be settled"
        hint="Opening this charges any bed nights not yet billed, so the figures below are current."
      />
      <div className="space-y-4 p-5">
        {billing.isLoading && <LoadingNotice>Working out the bill…</LoadingNotice>}
        {billing.isError && <ErrorNotice>Could not read the stay&apos;s billing.</ErrorNotice>}

        {data && (
          <>
            <p className="text-[12.5px] text-ink-muted">
              {data.nights_occupied} night{data.nights_occupied === 1 ? '' : 's'} occupied
              {data.nights_charged_now.length > 0 && (
                <>
                  {' · '}
                  <span className="font-medium text-ink">
                    {data.nights_charged_now.length} newly charged
                  </span>
                </>
              )}
            </p>

            {data.invoices.length === 0 ? (
              <EmptyState>Nothing has been charged to this stay.</EmptyState>
            ) : (
              <ul className="space-y-2">
                {data.invoices.map((invoice) => (
                  <li
                    key={invoice.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border px-4 py-3"
                  >
                    <div>
                      <Link
                        href={`/billing/${invoice.id}`}
                        className="text-[13px] font-semibold text-ink hover:text-accent"
                      >
                        {invoice.invoice_number}
                      </Link>
                      <p className="mt-0.5 text-[11.5px] text-ink-muted">
                        {invoice.items} charge{invoice.items === 1 ? '' : 's'} ·{' '}
                        {money(invoice.total)}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={`text-[13px] font-semibold ${
                          Number(invoice.balance) > 0 ? 'text-abnormal' : 'text-normal'
                        }`}
                      >
                        {money(invoice.balance)} outstanding
                      </span>
                      <Badge tone={invoiceTone(invoice.status)}>
                        {invoiceLabel(invoice.status)}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {data.outstanding.length > 0 ? (
              <div
                role="alert"
                className="rounded-lg border border-abnormal/40 bg-abnormal-muted px-4 py-3"
              >
                <p className="text-[12.5px] font-bold text-abnormal">
                  This patient cannot be discharged yet
                </p>
                <ul className="mt-1.5 space-y-1">
                  {data.outstanding.map((problem) => (
                    <li key={problem} className="text-[12px] text-abnormal">
                      {problem}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
                Nothing outstanding. This stay can be discharged.
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}

function CompletePanel({ stay }: { stay: AdmissionRow }) {
  const discharge = useDischarge()
  const billing = useDischargeBilling(stay.id)
  const [diagnosis, setDiagnosis] = useState(stay.admission_diagnosis)
  const [destination, setDestination] = useState(stay.discharge_destination || 'home')
  const [instructions, setInstructions] = useState('')
  const [override, setOverride] = useState('')

  const blocked = (billing.data?.outstanding.length ?? 0) > 0
  const canOverride = billing.data?.can_override ?? false

  const conflict =
    discharge.error instanceof ApiError && discharge.error.status === 409
      ? (discharge.error.body as { detail?: string[] })?.detail ?? [
          discharge.error.message,
        ]
      : null
  const forbidden =
    discharge.error instanceof ApiError && discharge.error.status === 403
      ? discharge.error.message
      : null
  const fieldErrors = discharge.error instanceof ApiError ? discharge.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title="Complete the discharge"
        hint="Closes the stay, releases the bed for cleaning, and is audited with both diagnoses and the length of stay."
      />
      <div className="space-y-4 p-5">
        {forbidden && <ErrorNotice>{forbidden}</ErrorNotice>}
        {conflict && (
          <div role="alert" className="rounded-lg border border-critical/40 bg-critical-muted px-4 py-3">
            <p className="text-[12.5px] font-bold text-critical">Discharge refused</p>
            <ul className="mt-1.5 space-y-1">
              {conflict.map((problem) => (
                <li key={problem} className="text-[12px] text-critical">
                  {problem}
                </li>
              ))}
            </ul>
          </div>
        )}

        <Field
          label="Discharge diagnosis"
          hint="What the patient is going home with, not what they came in with."
          error={fieldErrors.diagnosis}
          required
        >
          <Input
            value={diagnosis}
            onChange={(event) => setDiagnosis(event.target.value)}
          />
        </Field>
        <Field label="Destination" error={fieldErrors.destination} required>
          <Select
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
          >
            {DESTINATIONS.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="Follow-up instructions"
          hint="Printed on the discharge summary the patient takes with them."
        >
          <Textarea
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="Amlodipine 10 mg daily. Clinic in two weeks with a BP diary."
          />
        </Field>

        {blocked && canOverride && (
          <Field
            label="Reason for discharging with the bill unsettled"
            hint="Recorded as an exception, not as a discharge. Needs the billing override permission, which you hold."
            error={fieldErrors.override_reason}
          >
            <Textarea
              value={override}
              onChange={(event) => setOverride(event.target.value)}
              placeholder="Absconded overnight; bill referred to accounts."
            />
          </Field>
        )}
        {blocked && !canOverride && (
          <p className="rounded-md bg-surface-muted px-4 py-3 text-[12.5px] text-ink-muted">
            The stay is not settled. Discharging anyway needs the billing override
            permission, which you do not hold — send the patient to the cash desk,
            or ask a ward manager.
          </p>
        )}

        <Button
          disabled={
            !diagnosis.trim() ||
            !destination ||
            discharge.isPending ||
            (blocked && (!canOverride || !override.trim()))
          }
          onClick={() =>
            discharge.mutate({
              id: stay.id,
              diagnosis: diagnosis.trim(),
              destination,
              instructions,
              override_reason: override.trim(),
            })
          }
        >
          {discharge.isPending ? 'Discharging…' : 'Discharge patient'}
        </Button>
      </div>
    </Panel>
  )
}

function Summary({ stay }: { stay: AdmissionRow }) {
  const summary = useDischargeSummary(stay.id)
  const data = summary.data

  return (
    <Panel>
      <PanelHeader
        title="Discharge summary"
        hint="Assembled from the record on every read, so a reprint is identical by construction. Each print is logged."
        action={
          <Button variant="secondary" onClick={() => window.print()}>
            Print
          </Button>
        }
      />
      <div className="space-y-6 p-5 print:p-0">
        {summary.isLoading && <LoadingNotice>Assembling the summary…</LoadingNotice>}
        {summary.isError && <ErrorNotice>Could not assemble the summary.</ErrorNotice>}

        {data && (
          <>
            <dl className="grid gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2">
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">Patient</dt>
                <dd className="mt-0.5 text-ink">
                  {data.patient_name} · {data.hospital_number}
                </dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">Stay</dt>
                <dd className="mt-0.5 text-ink">
                  {data.admission_number} · {data.nights} night
                  {data.nights === 1 ? '' : 's'}
                </dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">Admitted</dt>
                <dd className="mt-0.5 text-ink">{dateAndTime(data.admitted_at)}</dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">Discharged</dt>
                <dd className="mt-0.5 text-ink">
                  {data.discharged_at ? dateAndTime(data.discharged_at) : '—'} to{' '}
                  {data.destination}
                </dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">
                  Admission diagnosis
                </dt>
                <dd className="mt-0.5 text-ink">{data.admission_diagnosis}</dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">
                  Discharge diagnosis
                </dt>
                <dd className="mt-0.5 font-semibold text-ink">
                  {data.discharge_diagnosis}
                </dd>
              </div>
            </dl>

            <SummarySection title="What was done">
              {data.reviews.length === 0 ? (
                <p className="text-[12.5px] text-ink-muted">No reviews recorded.</p>
              ) : (
                <ol className="space-y-2.5">
                  {data.reviews.map((review) => (
                    <li key={`${review.date}-${review.clinician}`}>
                      <p className="text-[11.5px] font-semibold text-ink-muted">
                        {dateAndTime(review.date)} · {review.clinician}
                      </p>
                      <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink">
                        {review.notes}
                      </p>
                      {review.diagnoses.length > 0 && (
                        <p className="mt-0.5 text-[11.5px] text-ink-muted">
                          {review.diagnoses.join('; ')}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </SummarySection>

            <SummarySection title="Investigations">
              {data.investigations.length === 0 ? (
                <p className="text-[12.5px] text-ink-muted">None verified.</p>
              ) : (
                <ul className="space-y-2">
                  {data.investigations.map((entry) => (
                    <li key={`${entry.test}-${entry.when}`}>
                      <p className="text-[12.5px] font-semibold text-ink">{entry.test}</p>
                      <p className="mt-0.5 text-[11.5px] text-ink-muted">
                        {entry.results
                          .map(
                            (result) =>
                              `${result.parameter} ${result.value}${
                                result.flag ? ` (${result.flag})` : ''
                              }`,
                          )
                          .join(' · ')}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </SummarySection>

            <SummarySection title="Imaging">
              {data.imaging.length === 0 ? (
                <p className="text-[12.5px] text-ink-muted">
                  None verified. An unreleased report is not quoted here.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.imaging.map((entry) => (
                    <li key={`${entry.procedure}-${entry.when}`}>
                      <p className="text-[12.5px] font-semibold text-ink">
                        {entry.procedure}
                        {entry.amended && (
                          <span className="ml-2 text-[10.5px] font-bold tracking-wide text-abnormal uppercase">
                            amended
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 text-[12px] text-ink-muted">
                        {entry.conclusion}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </SummarySection>

            <SummarySection title="Medication to take home">
              {data.discharge_medication.length === 0 ? (
                <p className="text-[12.5px] text-ink-muted">
                  None prescribed. Discharge medication is a prescription the
                  pharmacy dispenses, not free text typed here.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.discharge_medication.map((entry) => (
                    <li key={entry.medication}>
                      <p className="text-[12.5px] font-semibold text-ink">
                        {entry.medication}
                      </p>
                      <p className="mt-0.5 text-[11.5px] text-ink-muted">
                        {entry.directions} · {entry.quantity} to supply
                        {entry.instructions && ` · ${entry.instructions}`}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </SummarySection>

            <SummarySection title="Follow-up">
              <p className="text-[12.5px] leading-relaxed text-ink">
                {data.follow_up_instructions || 'None recorded.'}
              </p>
            </SummarySection>

            <p className="border-t border-border pt-3 text-[11px] text-ink-faint">
              Responsible consultant: {data.responsible_consultant} · {data.facility}
            </p>
          </>
        )}
      </div>
    </Panel>
  )
}

function SummarySection({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section>
      <h3 className="mb-2 border-b border-border pb-1 text-[11px] font-bold tracking-[0.08em] text-ink-muted uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}
