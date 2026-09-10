'use client'

import { use, useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useStaff } from '@/lib/config'
import { useInventoryItems } from '@/lib/inventory'
import {
  type ProcedureRequest,
  useAmendNote, useBookTheatre, useCancelBooking, useCancelProcedure,
  usePerformProcedure, useProcedureCatalogue, useProcedureRequests,
  useRecordConsent, useTheatres, useWithdrawConsent,
} from '@/lib/procedures'
import { dateAndTime, timeOfDay } from '@/lib/workflow'

/**
 * One procedure, from request to operation note.
 *
 * The panels appear in the order the case moves: consent, then a slot, then
 * the record of what happened. Each disappears once it is done and reappears
 * as history, so the screen always shows the next thing rather than a form
 * with everything on it.
 *
 * Consent is shown at the top and in red when it is missing, because it is
 * the one thing that stops the case and the one thing people discover late.
 */
export default function ProcedureCasePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const caseId = Number(id)
  const { can } = useAuth()

  const requests = useProcedureRequests()
  const [error, setError] = useState<string | null>(null)

  const record = (requests.data ?? []).find((r) => r.id === caseId)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      return true
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That action could not be completed.',
      )
      return false
    }
  }

  if (requests.isPending) return <PageShell><LoadingNotice /></PageShell>
  if (!record) {
    return (
      <PageShell>
        <ErrorNotice>No such procedure, or not one you have access to.</ErrorNotice>
      </PageShell>
    )
  }

  const live = record.bookings.filter((b) => b.status !== 'cancelled')

  return (
    <PageShell>
      <Link
        href="/theatre"
        className="mb-3 inline-block text-[12px] font-medium text-ink-muted hover:text-accent"
      >
        ← Operating list
      </Link>
      <PageHeading
        title={record.procedure_name}
        subtitle={`${record.patient_name} · ${record.hospital_number} · ${record.reference}`}
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {record.consent_blocking && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/5 px-4 py-3 text-[13px] leading-relaxed text-critical">
          <AlertIcon className="mt-0.5 size-4 shrink-0" />
          <span className="font-medium">{record.consent_blocking}</span>
        </div>
      )}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
        <div className="grid gap-5">
          <Panel>
            <PanelHeader
              title="The request"
              hint={`Asked by ${record.requested_by_email}, ${dateAndTime(record.requested_at)}`}
              action={
                <div className="flex gap-1.5">
                  <Badge
                    tone={
                      record.urgency === 'emergency' ? 'critical'
                        : record.urgency === 'urgent' ? 'abnormal' : 'idle'
                    }
                  >
                    {record.urgency_display}
                  </Badge>
                  <Badge
                    tone={
                      record.status === 'performed' ? 'normal'
                        : record.status === 'cancelled' ? 'idle' : 'progress'
                    }
                  >
                    {record.status_display}
                  </Badge>
                </div>
              }
            />
            <div className="p-5">
              <p className="text-[13px] leading-relaxed text-ink">{record.indication}</p>
              {record.cancellation_reason && (
                <p className="mt-3 text-[12.5px] leading-relaxed text-ink-muted">
                  Cancelled: {record.cancellation_reason}
                </p>
              )}
            </div>
            {record.status !== 'performed' && record.status !== 'cancelled' &&
              can('procedures.request_procedure') && (
                <CancelPanel record={record} run={run} />
              )}
          </Panel>

          <ConsentPanel record={record} run={run} canRecord={can('procedures.record_consent')} />

          {record.status !== 'performed' && record.status !== 'cancelled' &&
            can('procedures.schedule_procedure') && (
              <BookingPanel record={record} run={run} />
            )}

          {live.length > 0 && (
            <Panel>
              <PanelHeader title="Booked" hint="Cancelling a slot frees the theatre." />
              <div className="grid gap-2.5 p-5">
                {live.map((booking) => (
                  <BookingRow
                    key={booking.id}
                    booking={booking}
                    canCancel={
                      can('procedures.schedule_procedure') && booking.status !== 'completed'
                    }
                    run={run}
                  />
                ))}
              </div>
            </Panel>
          )}
        </div>

        <div className="grid gap-5">
          {record.performed ? (
            <PerformedPanel record={record} run={run} canAmend={can('procedures.amend_operation_note')} />
          ) : record.status !== 'cancelled' && can('procedures.perform_procedure') ? (
            <PerformPanel record={record} run={run} />
          ) : (
            <Panel>
              <PanelHeader title="Operation note" />
              <div className="p-5">
                <EmptyState>
                  {record.status === 'cancelled'
                    ? 'This procedure was cancelled and never happened.'
                    : 'Nothing recorded yet.'}
                </EmptyState>
              </div>
            </Panel>
          )}
        </div>
      </div>
    </PageShell>
  )
}

function CancelPanel({
  record, run,
}: {
  record: ProcedureRequest
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const cancel = useCancelProcedure()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')

  return (
    <div className="border-t border-border p-5">
      {!open ? (
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Cancel this procedure
        </Button>
      ) : (
        <div className="grid gap-3">
          <p className="text-[12.5px] leading-relaxed text-ink-muted">
            A cancelled procedure never bills, and any theatre slot it holds is given
            back.
          </p>
          <Field label="Why" required>
            <Input
              value={reason}
              maxLength={255}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Patient declined after further discussion."
            />
          </Field>
          <div className="flex gap-2">
            <Button
              disabled={cancel.isPending || !reason.trim()}
              onClick={async () => {
                const ok = await run(() =>
                  cancel.mutateAsync({ id: record.id, reason }),
                )
                if (ok) setOpen(false)
              }}
            >
              Cancel it
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>Keep it</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function ConsentPanel({
  record, run, canRecord,
}: {
  record: ProcedureRequest
  run: (a: () => Promise<unknown>) => Promise<boolean>
  canRecord: boolean
}) {
  const recordConsent = useRecordConsent()
  const withdraw = useWithdrawConsent()
  const [open, setOpen] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [form, setForm] = useState({
    risks_discussed: '', given_by: 'patient' as const, given_by_name: '',
    relationship: '', interpreter_used: false, interpreter_name: '',
  })
  const [withdrawReason, setWithdrawReason] = useState('')

  const consent = record.consent

  if (!record.requires_consent && consent === null) {
    return (
      <Panel>
        <PanelHeader title="Consent" />
        <div className="p-5">
          <p className="text-[12.5px] leading-relaxed text-ink-muted">
            {record.procedure_name} is not one the catalogue marks as requiring written
            consent. That is a configuration decision, not a clinical one — if it is
            wrong, an administrator can change it.
          </p>
        </div>
      </Panel>
    )
  }

  return (
    <Panel>
      <PanelHeader
        title="Consent"
        action={
          consent === null ? <Badge tone="critical">not recorded</Badge>
            : consent.is_valid ? <Badge tone="normal">recorded</Badge>
              : <Badge tone="critical">withdrawn</Badge>
        }
      />
      <div className="p-5">
        {consent !== null && (
          <div className="grid gap-2">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[12.5px]">
              <dt className="text-ink-muted">Given by</dt>
              <dd className="text-ink">
                {consent.given_by_display}
                {consent.given_by_name && ` — ${consent.given_by_name}`}
                {consent.relationship && ` (${consent.relationship})`}
              </dd>
              <dt className="text-ink-muted">Taken by</dt>
              <dd className="text-ink">{consent.taken_by_email}</dd>
              <dt className="text-ink-muted">When</dt>
              <dd className="text-ink">{dateAndTime(consent.taken_at)}</dd>
              {consent.interpreter_used && (
                <>
                  <dt className="text-ink-muted">Interpreter</dt>
                  <dd className="text-ink">{consent.interpreter_name}</dd>
                </>
              )}
            </dl>
            <p className="mt-1 rounded-md border border-border bg-surface-sunken/40 p-3 text-[12.5px] leading-relaxed text-ink">
              {consent.risks_discussed}
            </p>
            {!consent.is_valid && (
              <p className="text-[12.5px] leading-relaxed text-critical">
                Withdrawn {consent.withdrawn_at && dateAndTime(consent.withdrawn_at)} —{' '}
                {consent.withdrawal_reason}
              </p>
            )}
          </div>
        )}

        {canRecord && (consent === null || !consent.is_valid) && (
          open ? (
            <div className="mt-4 grid gap-4">
              <Field label="Who is consenting" required>
                <Select
                  value={form.given_by}
                  onChange={(e) =>
                    setForm({ ...form, given_by: e.target.value as 'patient' })
                  }
                >
                  <option value="patient">The patient</option>
                  <option value="next_of_kin">Next of kin or legal guardian</option>
                  <option value="two_doctors">
                    Two doctors, patient unable to consent
                  </option>
                </Select>
              </Field>
              {form.given_by !== 'patient' && (
                <>
                  <Field label="Their name" required>
                    <Input
                      value={form.given_by_name}
                      maxLength={200}
                      onChange={(e) =>
                        setForm({ ...form, given_by_name: e.target.value })
                      }
                    />
                  </Field>
                  <Field label="Relationship to the patient">
                    <Input
                      value={form.relationship}
                      maxLength={80}
                      onChange={(e) => setForm({ ...form, relationship: e.target.value })}
                    />
                  </Field>
                </>
              )}
              <Field
                label="What was explained"
                required
                hint="The procedure, its risks, and the alternatives. A tick with no content is not a record of consent."
              >
                <Textarea
                  value={form.risks_discussed}
                  onChange={(e) =>
                    setForm({ ...form, risks_discussed: e.target.value })
                  }
                  placeholder="Explained the procedure, the risks of bleeding and infection, and the alternative of conservative management. Questions answered."
                />
              </Field>
              <div>
                <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
                  <input
                    type="checkbox"
                    checked={form.interpreter_used}
                    onChange={(e) =>
                      setForm({ ...form, interpreter_used: e.target.checked })
                    }
                    className="size-4 rounded border-border"
                  />
                  An interpreter was used
                </label>
              </div>
              {form.interpreter_used && (
                <Field label="Interpreter's name" required>
                  <Input
                    value={form.interpreter_name}
                    maxLength={200}
                    onChange={(e) =>
                      setForm({ ...form, interpreter_name: e.target.value })
                    }
                  />
                </Field>
              )}
              <div className="flex gap-2">
                <Button
                  disabled={
                    recordConsent.isPending ||
                    !form.risks_discussed.trim() ||
                    (form.given_by !== 'patient' && !form.given_by_name.trim()) ||
                    (form.interpreter_used && !form.interpreter_name.trim())
                  }
                  onClick={async () => {
                    const ok = await run(() =>
                      recordConsent.mutateAsync({ id: record.id, ...form }),
                    )
                    if (ok) setOpen(false)
                  }}
                >
                  Record consent
                </Button>
                <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
              </div>
            </div>
          ) : (
            <div className="mt-4">
              <Button onClick={() => setOpen(true)}>Record consent</Button>
            </div>
          )
        )}

        {canRecord && consent !== null && consent.is_valid &&
          record.status !== 'performed' && (
            <div className="mt-4 border-t border-border pt-4">
              {!withdrawing ? (
                <Button variant="ghost" onClick={() => setWithdrawing(true)}>
                  The patient has withdrawn consent
                </Button>
              ) : (
                <div className="grid gap-3">
                  <Field label="What the patient said" required>
                    <Input
                      value={withdrawReason}
                      maxLength={255}
                      onChange={(e) => setWithdrawReason(e.target.value)}
                    />
                  </Field>
                  <div className="flex gap-2">
                    <Button
                      disabled={withdraw.isPending || !withdrawReason.trim()}
                      onClick={async () => {
                        const ok = await run(() =>
                          withdraw.mutateAsync({
                            id: record.id, reason: withdrawReason,
                          }),
                        )
                        if (ok) setWithdrawing(false)
                      }}
                    >
                      Record the withdrawal
                    </Button>
                    <Button variant="ghost" onClick={() => setWithdrawing(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
      </div>
    </Panel>
  )
}

function BookingPanel({
  record, run,
}: {
  record: ProcedureRequest
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const theatres = useTheatres()
  const catalogue = useProcedureCatalogue()
  const staff = useStaff()
  const book = useBookTheatre()
  const [open, setOpen] = useState(false)
  const [theatre, setTheatre] = useState('')
  const [starts, setStarts] = useState('')
  const [minutes, setMinutes] = useState('')
  const [surgeon, setSurgeon] = useState('')
  const [anaesthetist, setAnaesthetist] = useState('')

  const procedure = (catalogue.data ?? []).find((p) => p.id === record.procedure)

  function endFrom(start: string, mins: string) {
    if (!start || !mins) return ''
    const end = new Date(new Date(start).getTime() + Number(mins) * 60_000)
    return end.toISOString()
  }

  return (
    <Panel>
      <PanelHeader
        title="Book a theatre"
        hint="Two operations cannot hold one theatre at one time."
      />
      <div className="p-5">
        {!open ? (
          <Button
            onClick={() => {
              setOpen(true)
              setMinutes(String(procedure?.typical_duration_minutes ?? 30))
            }}
          >
            Book a slot
          </Button>
        ) : (
          <div className="grid gap-4">
            <Field label="Theatre" required>
              <Select value={theatre} onChange={(e) => setTheatre(e.target.value)}>
                <option value="">Choose a theatre…</option>
                {(theatres.data ?? [])
                  .filter((t) => t.is_active)
                  .map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
              </Select>
            </Field>
            <Field label="Starting" required>
              <Input
                type="datetime-local"
                value={starts}
                onChange={(e) => setStarts(e.target.value)}
              />
            </Field>
            <Field
              label="Minutes"
              required
              hint={
                procedure
                  ? `${procedure.name} usually takes ${procedure.typical_duration_minutes}.`
                  : undefined
              }
            >
              <Input
                type="number"
                min={5}
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
                className="text-right"
              />
            </Field>
            <Field label="Lead surgeon" required>
              <Select value={surgeon} onChange={(e) => setSurgeon(e.target.value)}>
                <option value="">Choose…</option>
                {(staff.data ?? []).map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Anaesthetist"
              hint={
                procedure?.requires_anaesthesia
                  ? 'This procedure needs one.'
                  : 'Optional for this procedure.'
              }
            >
              <Select
                value={anaesthetist}
                onChange={(e) => setAnaesthetist(e.target.value)}
              >
                <option value="">None</option>
                {(staff.data ?? []).map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex gap-2">
              <Button
                disabled={
                  book.isPending || theatre === '' || starts === '' ||
                  minutes === '' || surgeon === ''
                }
                onClick={async () => {
                  const ok = await run(() =>
                    book.mutateAsync({
                      id: record.id,
                      theatre: Number(theatre),
                      starts_at: new Date(starts).toISOString(),
                      ends_at: endFrom(starts, minutes),
                      lead_surgeon: Number(surgeon),
                      anaesthetist: anaesthetist === '' ? null : Number(anaesthetist),
                    }),
                  )
                  if (ok) setOpen(false)
                }}
              >
                {book.isPending ? 'Booking…' : 'Hold the slot'}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

function BookingRow({
  booking, canCancel, run,
}: {
  booking: ProcedureRequest['bookings'][number]
  canCancel: boolean
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const cancel = useCancelBooking()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')

  return (
    <div className="rounded-lg border border-border bg-surface-sunken/40 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12.5px] font-semibold text-ink">
          {booking.theatre_name}
        </span>
        <Badge tone={booking.status === 'completed' ? 'normal' : 'progress'}>
          {booking.status_display}
        </Badge>
      </div>
      <p className="mt-0.5 text-[12px] text-ink-muted">
        {dateAndTime(booking.starts_at)} — {timeOfDay(booking.ends_at)}
      </p>
      <p className="mt-0.5 text-[11.5px] text-ink-faint">
        {booking.lead_surgeon_name}
        {booking.anaesthetist_name && ` · ${booking.anaesthetist_name}`}
      </p>
      {canCancel && (
        open ? (
          <div className="mt-2.5 grid gap-2">
            <Input
              value={reason}
              maxLength={255}
              placeholder="Why the slot is being given back"
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                disabled={cancel.isPending || !reason.trim()}
                onClick={async () => {
                  const ok = await run(() =>
                    cancel.mutateAsync({ id: booking.id, reason }),
                  )
                  if (ok) setOpen(false)
                }}
              >
                Cancel the slot
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Keep it</Button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="mt-1.5 text-[12px] font-medium text-accent hover:underline"
          >
            Cancel this slot
          </button>
        )
      )}
    </div>
  )
}

function PerformPanel({
  record, run,
}: {
  record: ProcedureRequest
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const staff = useStaff()
  const items = useInventoryItems()
  const catalogue = useProcedureCatalogue()
  const perform = usePerformProcedure()

  const procedure = (catalogue.data ?? []).find((p) => p.id === record.procedure)
  const booking = record.bookings.find((b) => b.status !== 'cancelled') ?? null

  const [form, setForm] = useState({
    started_at: '', finished_at: '', lead_clinician: '',
    findings: '', procedure_performed: '', closure: '',
    blood_loss_ml: '', specimens: '', complications: '',
    post_operative_instructions: '',
  })
  const [used, setUsed] = useState<Record<number, string>>({})
  const [team, setTeam] = useState<{ member: string; role: string }[]>([])

  const blocked = record.consent_blocking !== null
  const ready =
    !blocked &&
    form.started_at !== '' && form.finished_at !== '' &&
    form.lead_clinician !== '' &&
    form.findings.trim() !== '' && form.procedure_performed.trim() !== ''

  return (
    <Panel>
      <PanelHeader
        title="Record what happened"
        hint="Consumables come off stock and the charge is raised, in one go."
      />
      <div className="grid gap-4 p-5">
        {blocked && (
          <p className="flex items-start gap-2 rounded-lg border border-critical/30 bg-critical/5 px-3 py-2.5 text-[12px] leading-relaxed text-critical">
            <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
            {record.consent_blocking}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Started" required>
            <Input
              type="datetime-local"
              value={form.started_at}
              onChange={(e) => setForm({ ...form, started_at: e.target.value })}
            />
          </Field>
          <Field label="Finished" required>
            <Input
              type="datetime-local"
              value={form.finished_at}
              onChange={(e) => setForm({ ...form, finished_at: e.target.value })}
            />
          </Field>
        </div>

        <Field label="Lead clinician" required>
          <Select
            value={form.lead_clinician}
            onChange={(e) => setForm({ ...form, lead_clinician: e.target.value })}
          >
            <option value="">Choose…</option>
            {(staff.data ?? []).map((person) => (
              <option key={person.id} value={person.id}>{person.full_name}</option>
            ))}
          </Select>
        </Field>

        <Field label="Findings" required>
          <Textarea
            value={form.findings}
            onChange={(e) => setForm({ ...form, findings: e.target.value })}
            placeholder="Acutely inflamed, non-perforated appendix. No free fluid."
          />
        </Field>
        <Field
          label="What was actually done"
          required
          hint="Not always what was requested, and the note is the only place that difference shows."
        >
          <Textarea
            value={form.procedure_performed}
            onChange={(e) =>
              setForm({ ...form, procedure_performed: e.target.value })
            }
            placeholder="Open appendicectomy through a grid-iron incision."
          />
        </Field>
        <Field label="Closure">
          <Input
            value={form.closure}
            onChange={(e) => setForm({ ...form, closure: e.target.value })}
          />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Estimated blood loss (mL)">
            <Input
              type="number"
              min={0}
              value={form.blood_loss_ml}
              onChange={(e) => setForm({ ...form, blood_loss_ml: e.target.value })}
              className="text-right"
            />
          </Field>
          <Field label="Specimens">
            <Input
              value={form.specimens}
              maxLength={255}
              onChange={(e) => setForm({ ...form, specimens: e.target.value })}
              placeholder="Appendix, to histology."
            />
          </Field>
        </div>
        <Field label="Complications">
          <Textarea
            value={form.complications}
            onChange={(e) => setForm({ ...form, complications: e.target.value })}
          />
        </Field>
        <Field label="Post-operative instructions">
          <Textarea
            value={form.post_operative_instructions}
            onChange={(e) =>
              setForm({ ...form, post_operative_instructions: e.target.value })
            }
          />
        </Field>

        <div className="grid gap-2.5 border-t border-border pt-4">
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Who was in the room
          </p>
          {team.map((entry, index) => (
            <div key={index} className="grid gap-2 sm:grid-cols-2">
              <Select
                value={entry.member}
                onChange={(e) => {
                  const next = [...team]
                  next[index] = { ...entry, member: e.target.value }
                  setTeam(next)
                }}
              >
                <option value="">Choose…</option>
                {(staff.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>{p.full_name}</option>
                ))}
              </Select>
              <Select
                value={entry.role}
                onChange={(e) => {
                  const next = [...team]
                  next[index] = { ...entry, role: e.target.value }
                  setTeam(next)
                }}
              >
                <option value="surgeon">Surgeon</option>
                <option value="assistant">Assistant</option>
                <option value="anaesthetist">Anaesthetist</option>
                <option value="scrub_nurse">Scrub nurse</option>
                <option value="circulating_nurse">Circulating nurse</option>
                <option value="other">Other</option>
              </Select>
            </div>
          ))}
          <div>
            <Button
              variant="ghost"
              onClick={() => setTeam([...team, { member: '', role: 'assistant' }])}
            >
              Add somebody
            </Button>
          </div>
        </div>

        <div className="grid gap-2.5 border-t border-border pt-4">
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Consumables used
          </p>
          <p className="text-[12px] leading-relaxed text-ink-muted">
            Pre-filled from what {record.procedure_name} usually opens. Change it to what
            was actually used — these come off the theatre store.
          </p>
          {(procedure?.consumables ?? []).map((line) => (
            <Field
              key={line.id}
              label={`${line.item_name} (${line.unit_of_issue})`}
            >
              <Input
                type="number"
                min={0}
                value={used[line.item] ?? String(line.quantity)}
                onChange={(e) => setUsed({ ...used, [line.item]: e.target.value })}
                className="text-right"
              />
            </Field>
          ))}
          {(procedure?.consumables ?? []).length === 0 && (
            <p className="text-[12px] text-ink-faint">
              Nothing configured for this procedure.
            </p>
          )}
        </div>

        <div>
          <Button
            disabled={!ready || perform.isPending}
            onClick={() =>
              run(() =>
                perform.mutateAsync({
                  id: record.id,
                  started_at: new Date(form.started_at).toISOString(),
                  finished_at: new Date(form.finished_at).toISOString(),
                  lead_clinician: Number(form.lead_clinician),
                  outcome: 'completed',
                  booking: booking?.id ?? null,
                  store: null,
                  findings: form.findings,
                  procedure_performed: form.procedure_performed,
                  closure: form.closure,
                  blood_loss_ml:
                    form.blood_loss_ml === '' ? null : Number(form.blood_loss_ml),
                  specimens: form.specimens,
                  complications: form.complications,
                  post_operative_instructions: form.post_operative_instructions,
                  team: team
                    .filter((t) => t.member !== '')
                    .map((t) => ({ member: Number(t.member), role: t.role })),
                  consumables: (procedure?.consumables ?? [])
                    .map((line) => ({
                      item: line.item,
                      quantity: Number(used[line.item] ?? line.quantity),
                    }))
                    .filter((line) => line.quantity > 0),
                  medications: [],
                }),
              )
            }
            className="px-4 py-2.5"
          >
            {perform.isPending ? 'Recording…' : 'Record the procedure'}
          </Button>
          {items.isError && (
            <p className="mt-2 text-[12px] text-ink-muted">
              The item list could not be loaded; consumables will not be taken off stock.
            </p>
          )}
        </div>
      </div>
    </Panel>
  )
}

function PerformedPanel({
  record, run, canAmend,
}: {
  record: ProcedureRequest
  run: (a: () => Promise<unknown>) => Promise<boolean>
  canAmend: boolean
}) {
  const amend = useAmendNote()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [findings, setFindings] = useState('')

  const done = record.performed!
  const note = done.note
  const current = note?.current ?? null
  const superseded = (note?.versions ?? []).filter((v) => !v.is_current)

  return (
    <>
      <Panel>
        <PanelHeader
          title="Operation note"
          hint={`${done.duration_minutes} minutes · ${done.lead_clinician_name}`}
          action={
            <div className="flex gap-1.5">
              <Badge tone={done.outcome === 'completed' ? 'normal' : 'abnormal'}>
                {done.outcome_display}
              </Badge>
              {done.is_billed && <Badge tone="idle">billed</Badge>}
            </div>
          }
        />
        <div className="grid gap-3 p-5">
          {current === null ? (
            <EmptyState>No note recorded.</EmptyState>
          ) : (
            <>
              {current.version_number > 1 && (
                <p className="text-[11.5px] text-ink-faint">
                  Version {current.version_number}, amended by {current.author_name}
                </p>
              )}
              <Section title="Findings">{current.findings}</Section>
              <Section title="What was done">{current.procedure_performed}</Section>
              {current.closure && <Section title="Closure">{current.closure}</Section>}
              {current.estimated_blood_loss_ml !== null && (
                <Section title="Blood loss">
                  {current.estimated_blood_loss_ml} mL
                </Section>
              )}
              {current.specimens_taken && (
                <Section title="Specimens">{current.specimens_taken}</Section>
              )}
              {current.complications && (
                <Section title="Complications">{current.complications}</Section>
              )}
              {current.post_operative_instructions && (
                <Section title="Post-operative">
                  {current.post_operative_instructions}
                </Section>
              )}
            </>
          )}
        </div>

        {canAmend && note !== null && (
          <div className="border-t border-border p-5">
            {!open ? (
              <Button variant="secondary" onClick={() => setOpen(true)}>
                Amend the note
              </Button>
            ) : (
              <div className="grid gap-3">
                <p className="text-[12px] leading-relaxed text-ink-muted">
                  Amending appends a version. The superseded text stays on the record,
                  because somebody may have made a decision on it.
                </p>
                <Field label="Why it is being amended" required>
                  <Textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Histology confirmed a perforation not seen at operation."
                  />
                </Field>
                <Field label="Revised findings" hint="Leave blank to keep what is there.">
                  <Textarea
                    value={findings}
                    onChange={(e) => setFindings(e.target.value)}
                  />
                </Field>
                <div className="flex gap-2">
                  <Button
                    disabled={amend.isPending || !reason.trim()}
                    onClick={async () => {
                      const ok = await run(() =>
                        amend.mutateAsync({
                          id: note.id,
                          reason,
                          ...(findings.trim() ? { findings } : {}),
                        }),
                      )
                      if (ok) { setOpen(false); setReason(''); setFindings('') }
                    }}
                  >
                    Append the amendment
                  </Button>
                  <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Panel>

      {superseded.length > 0 && (
        <Panel>
          <PanelHeader
            title="Superseded versions"
            hint="Kept because somebody may have acted on them."
          />
          <div className="grid gap-3 p-5">
            {superseded
              .sort((a, b) => b.version_number - a.version_number)
              .map((version) => (
                <div
                  key={version.id}
                  className="rounded-lg border border-border bg-surface-sunken/40 p-3"
                >
                  <p className="text-[11.5px] font-medium text-ink-muted">
                    Version {version.version_number} · {version.author_name} ·{' '}
                    {dateAndTime(version.created_at)}
                  </p>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
                    {version.findings}
                  </p>
                </div>
              ))}
          </div>
        </Panel>
      )}

      {(done.team.length > 0 || done.consumables_used.length > 0) && (
        <Panel>
          <PanelHeader title="Theatre record" />
          <div className="grid gap-4 p-5">
            {done.team.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                  Team
                </p>
                <ul className="grid gap-0.5">
                  {done.team.map((member) => (
                    <li key={member.id} className="text-[12.5px] text-ink">
                      {member.member_name}{' '}
                      <span className="text-ink-muted">— {member.role_display}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {done.consumables_used.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                  Consumables, taken off stock
                </p>
                <ul className="grid gap-0.5">
                  {done.consumables_used.map((line) => (
                    <li key={line.id} className="text-[12.5px] text-ink">
                      {line.quantity} × {line.item_name}{' '}
                      <span className="text-ink-faint">from {line.store_name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Panel>
      )}
    </>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
        {title}
      </p>
      <p className="mt-0.5 text-[13px] leading-relaxed text-ink">{children}</p>
    </div>
  )
}
