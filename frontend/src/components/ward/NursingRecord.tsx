'use client'

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
  StatTile,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type NursingNoteRow,
  useAcknowledgeEscalation,
  useEscalations,
  useFluidBalance,
  useNursingAssessments,
  useNursingNotes,
  useRecordAssessment,
  useRecordFluid,
  useWriteNursingNote,
} from '@/lib/inpatient'
import { dateAndTime, millilitres, shiftLabel, waitedFor } from '@/lib/workflow'

/**
 * The nursing record: escalations, observations, notes and fluid balance.
 *
 * Notes are append-only. There is no edit control anywhere on this screen — a
 * correction writes a new note that supersedes the earlier one, and the earlier
 * one stays exactly as written, because somebody may have acted on it.
 */
export function NursingRecord({ admissionId }: { admissionId: number }) {
  return (
    <div className="space-y-5">
      <Escalations admissionId={admissionId} />
      <FluidBalancePanel admissionId={admissionId} />
      <div className="grid gap-5 xl:grid-cols-2">
        <Notes admissionId={admissionId} />
        <Assessments admissionId={admissionId} />
      </div>
    </div>
  )
}

function Escalations({ admissionId }: { admissionId: number }) {
  const { can } = useAuth()
  const escalations = useEscalations({ admission: String(admissionId) })
  const acknowledge = useAcknowledgeEscalation()
  const [openId, setOpenId] = useState<number | null>(null)
  const [action, setAction] = useState('')

  const rows = escalations.data ?? []
  const outstanding = rows.filter((row) => row.is_outstanding)

  return (
    <Panel>
      <PanelHeader
        title="Escalations"
        hint="Observations outside this ward's thresholds. Each carries the instruction as it stood when it was raised."
        action={
          outstanding.length > 0 ? (
            <Badge tone="critical">{outstanding.length} outstanding</Badge>
          ) : rows.length > 0 ? (
            <Badge tone="normal">All answered</Badge>
          ) : undefined
        }
      />
      {escalations.isLoading && (
        <div className="p-5">
          <LoadingNotice>Loading escalations…</LoadingNotice>
        </div>
      )}
      {rows.length === 0 && !escalations.isLoading && (
        <div className="p-5">
          <EmptyState>
            No observation has breached this ward&apos;s thresholds.
          </EmptyState>
        </div>
      )}
      {rows.length > 0 && (
        <ul className="divide-y divide-border">
          {rows.map((row) => (
            <li
              key={row.id}
              className={`p-5 ${row.is_outstanding ? 'bg-critical-muted/25' : ''}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-semibold text-ink">
                    {row.is_outstanding && <span aria-hidden className="text-critical">▲ </span>}
                    {row.summary}
                  </p>
                  <p className="mt-0.5 text-[11.5px] text-ink-muted">
                    Raised by {row.raised_by_name} · {dateAndTime(row.raised_at)}
                  </p>
                  {row.instruction && (
                    <p className="mt-1.5 text-[12.5px] font-medium text-ink">
                      {row.instruction}
                    </p>
                  )}
                  {row.escalated_to_name && (
                    <p className="mt-1 text-[11.5px] text-ink-muted">
                      {row.escalated_to_name} was told
                      {row.escalated_at && ` at ${dateAndTime(row.escalated_at)}`}
                    </p>
                  )}
                </div>
                <Badge tone={row.is_outstanding ? 'critical' : 'normal'}>
                  {row.is_outstanding
                    ? `Waiting ${waitedFor(row.minutes_waiting)}`
                    : `Answered in ${waitedFor(row.minutes_waiting)}`}
                </Badge>
              </div>

              {row.action_taken && (
                <p className="mt-3 rounded-md bg-surface-muted px-3 py-2 text-[12.5px] text-ink">
                  <span className="font-semibold">{row.acknowledged_by_name}:</span>{' '}
                  {row.action_taken}
                </p>
              )}

              {row.is_outstanding && can('inpatient.escalate_observation') && (
                <div className="mt-3">
                  {openId === row.id ? (
                    <div className="space-y-2">
                      {acknowledge.error instanceof ApiError && (
                        <p role="alert" className="text-[12px] font-medium text-critical">
                          {Object.values(acknowledge.error.fields).flat().join(' ') ||
                            acknowledge.error.message}
                        </p>
                      )}
                      <Field
                        label="What was done about it?"
                        hint="Required. An acknowledgement with no action is a tick box, not a record."
                        required
                      >
                        <Textarea
                          value={action}
                          onChange={(event) => setAction(event.target.value)}
                          placeholder="Reviewed at the bedside, IV labetalol started, repeat in 15 minutes."
                        />
                      </Field>
                      <div className="flex gap-2">
                        <Button
                          disabled={!action.trim() || acknowledge.isPending}
                          onClick={() =>
                            acknowledge.mutate(
                              { id: row.id, action_taken: action.trim() },
                              {
                                onSuccess: () => {
                                  setOpenId(null)
                                  setAction('')
                                },
                              },
                            )
                          }
                        >
                          Record the action
                        </Button>
                        <Button variant="ghost" onClick={() => setOpenId(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setOpenId(row.id)}
                      className="text-[12px] font-semibold text-accent hover:underline"
                    >
                      Record what was done →
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

const INTAKE_ROUTES = [
  { value: 'oral', label: 'Oral' },
  { value: 'iv', label: 'Intravenous' },
  { value: 'ng', label: 'Nasogastric' },
  { value: 'other_in', label: 'Other intake' },
]
const OUTPUT_ROUTES = [
  { value: 'urine', label: 'Urine' },
  { value: 'vomit', label: 'Vomit' },
  { value: 'drain', label: 'Drain' },
  { value: 'stool', label: 'Stool' },
  { value: 'other_out', label: 'Other output' },
]

function FluidBalancePanel({ admissionId }: { admissionId: number }) {
  const { can } = useAuth()
  const [hours, setHours] = useState(24)
  const balance = useFluidBalance(admissionId, hours)
  const record = useRecordFluid()
  const [direction, setDirection] = useState<'intake' | 'output'>('intake')
  const [route, setRoute] = useState('oral')
  const [volume, setVolume] = useState('')

  const routes = direction === 'intake' ? INTAKE_ROUTES : OUTPUT_ROUTES
  const data = balance.data

  return (
    <Panel>
      <PanelHeader
        title="Fluid balance"
        hint="Summed from the entries on every read. Never stored, so it cannot drift from what was recorded."
        action={
          <Field label="Over">
            <Select
              value={hours}
              onChange={(event) => setHours(Number(event.target.value))}
              className="py-1.5 text-[12.5px]"
            >
              <option value={8}>8 hours</option>
              <option value={12}>12 hours</option>
              <option value={24}>24 hours</option>
              <option value={72}>3 days</option>
            </Select>
          </Field>
        }
      />
      <div className="space-y-5 p-5">
        {balance.isLoading && <LoadingNotice>Loading the balance…</LoadingNotice>}
        {data && (
          <div className="grid gap-3 sm:grid-cols-3">
            <StatTile label="Intake" value={`${data.intake_ml.toLocaleString()} mL`} hint={`${data.hours} hours`} />
            <StatTile label="Output" value={`${data.output_ml.toLocaleString()} mL`} hint={`${data.entries} entries`} />
            <StatTile
              label="Balance"
              value={millilitres(data.balance_ml)}
              hint={data.balance_ml >= 0 ? 'Positive balance' : 'Negative balance'}
              tone={Math.abs(data.balance_ml) > 1500 ? 'abnormal' : 'idle'}
            />
          </div>
        )}

        {data && Object.keys(data.by_route).length > 0 && (
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
            {Object.entries(data.by_route).map(([key, value]) => (
              <li key={key} className="text-[11.5px] text-ink-muted">
                <span className="font-medium text-ink">
                  {[...INTAKE_ROUTES, ...OUTPUT_ROUTES].find((entry) => entry.value === key)
                    ?.label ?? key}
                </span>{' '}
                {value.toLocaleString()} mL
              </li>
            ))}
          </ul>
        )}

        {can('inpatient.add_fluidbalanceentry') && (
          <div className="border-t border-border pt-4">
            {record.error instanceof ApiError && (
              <ErrorNotice>
                {Object.values(record.error.fields).flat().join(' ') ||
                  record.error.message}
              </ErrorNotice>
            )}
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="In or out" required>
                <Select
                  value={direction}
                  onChange={(event) => {
                    const next = event.target.value as 'intake' | 'output'
                    setDirection(next)
                    // The route has to follow the direction: an output route on
                    // an intake row still adds up, which is the worst kind of
                    // wrong. The server refuses it too.
                    setRoute(next === 'intake' ? 'oral' : 'urine')
                  }}
                >
                  <option value="intake">Intake</option>
                  <option value="output">Output</option>
                </Select>
              </Field>
              <Field label="Route" required>
                <Select value={route} onChange={(event) => setRoute(event.target.value)}>
                  {routes.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Volume (mL)" required>
                <Input
                  type="number"
                  min={1}
                  max={20000}
                  inputMode="numeric"
                  value={volume}
                  onChange={(event) => setVolume(event.target.value)}
                />
              </Field>
              <div className="flex items-end">
                <Button
                  disabled={!volume || Number(volume) < 1 || record.isPending}
                  onClick={() =>
                    record.mutate(
                      {
                        admission: admissionId,
                        direction,
                        route,
                        volume_ml: Number(volume),
                      },
                      { onSuccess: () => setVolume('') },
                    )
                  }
                >
                  Record
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

function Notes({ admissionId }: { admissionId: number }) {
  const { can } = useAuth()
  const notes = useNursingNotes(admissionId)
  const write = useWriteNursingNote()
  const [shift, setShift] = useState('early')
  const [text, setText] = useState('')
  const [correcting, setCorrecting] = useState<NursingNoteRow | null>(null)
  const [why, setWhy] = useState('')

  const rows = notes.data ?? []
  const fieldErrors = write.error instanceof ApiError ? write.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title="Nursing notes"
        hint="Append-only. A correction adds a new note; the original stays exactly as written."
      />
      <div className="space-y-4 p-5">
        {can('inpatient.add_nursingnote') && (
          <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
            {correcting && (
              <div className="rounded-md border border-abnormal/30 bg-abnormal-muted/40 px-3 py-2">
                <p className="text-[11.5px] font-semibold text-abnormal">
                  Correcting the note by {correcting.author_name},{' '}
                  {dateAndTime(correcting.recorded_at)}
                </p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-ink-muted italic">
                  “{correcting.note}”
                </p>
                <button
                  type="button"
                  onClick={() => setCorrecting(null)}
                  className="mt-1.5 text-[11.5px] font-medium text-ink-muted hover:text-ink"
                >
                  Write a new note instead
                </button>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
              <Field label="Shift" required>
                <Select value={shift} onChange={(event) => setShift(event.target.value)}>
                  <option value="early">Early</option>
                  <option value="late">Late</option>
                  <option value="night">Night</option>
                </Select>
              </Field>
              <Field label="Note" error={fieldErrors.note} required>
                <Textarea
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="Reviewed on the ward round. Plan: continue current treatment…"
                />
              </Field>
            </div>
            {correcting && (
              <Field
                label="Why does the earlier note need correcting?"
                error={fieldErrors.correction_reason}
                required
              >
                <Input
                  value={why}
                  onChange={(event) => setWhy(event.target.value)}
                  placeholder="Recorded on the wrong patient's round."
                />
              </Field>
            )}
            {fieldErrors.supersedes && (
              <p role="alert" className="text-[12px] font-medium text-critical">
                {fieldErrors.supersedes.join(' ')}
              </p>
            )}
            <Button
              disabled={
                !text.trim() ||
                (correcting !== null && !why.trim()) ||
                write.isPending
              }
              onClick={() =>
                write.mutate(
                  {
                    admission: admissionId,
                    shift,
                    note: text.trim(),
                    supersedes: correcting?.id ?? null,
                    correction_reason: correcting ? why.trim() : '',
                  },
                  {
                    onSuccess: () => {
                      setText('')
                      setWhy('')
                      setCorrecting(null)
                    },
                  },
                )
              }
            >
              {correcting ? 'Add the correction' : 'Add note'}
            </Button>
          </div>
        )}

        {rows.length === 0 ? (
          <EmptyState>Nothing has been written yet.</EmptyState>
        ) : (
          <ol className="space-y-3">
            {rows.map((note) => (
              <li
                key={note.id}
                className={`rounded-lg border p-3 ${
                  note.is_superseded
                    ? 'border-dashed border-border bg-surface-muted/40'
                    : 'border-border bg-surface'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-semibold text-ink">
                    {note.author_name}
                  </span>
                  <span className="text-[11.5px] text-ink-muted">
                    {shiftLabel(note.shift)} shift · {dateAndTime(note.recorded_at)}
                  </span>
                  {note.is_superseded && (
                    <span className="text-[10.5px] font-bold tracking-wide text-ink-faint uppercase">
                      Corrected later
                    </span>
                  )}
                  {note.supersedes !== null && (
                    <span className="text-[10.5px] font-bold tracking-wide text-abnormal uppercase">
                      Correction
                    </span>
                  )}
                </div>
                <p
                  className={`mt-1.5 text-[12.5px] leading-relaxed ${
                    note.is_superseded ? 'text-ink-muted' : 'text-ink'
                  }`}
                >
                  {note.note}
                </p>
                {note.correction_reason && (
                  <p className="mt-1.5 text-[11.5px] text-ink-faint">
                    Corrects an earlier note: {note.correction_reason}
                  </p>
                )}
                {!note.is_superseded && can('inpatient.add_nursingnote') && (
                  <button
                    type="button"
                    onClick={() => setCorrecting(note)}
                    className="mt-2 text-[11.5px] font-medium text-ink-muted hover:text-accent"
                  >
                    Correct this note
                  </button>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </Panel>
  )
}

function Assessments({ admissionId }: { admissionId: number }) {
  const { can } = useAuth()
  const assessments = useNursingAssessments(admissionId)
  const record = useRecordAssessment()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    shift: 'early',
    consciousness: 'alert',
    mobility: 'independent',
    falls_risk: false,
    pressure_area_concern: false,
    eating_and_drinking: '',
    continence: '',
    summary: '',
  })

  const rows = assessments.data ?? []

  return (
    <Panel>
      <PanelHeader
        title="Shift assessments"
        hint="Attached to the stay, not to an attendance. The observations themselves sit on the patient's own trend."
        action={
          can('inpatient.add_nursingassessment') ? (
            <Button variant="secondary" onClick={() => setOpen((value) => !value)}>
              {open ? 'Close' : 'Record one'}
            </Button>
          ) : undefined
        }
      />
      <div className="space-y-4 p-5">
        {open && (
          <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
            {record.error instanceof ApiError && (
              <ErrorNotice>{record.error.message}</ErrorNotice>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Shift" required>
                <Select
                  value={form.shift}
                  onChange={(event) => setForm({ ...form, shift: event.target.value })}
                >
                  <option value="early">Early</option>
                  <option value="late">Late</option>
                  <option value="night">Night</option>
                </Select>
              </Field>
              <Field label="Consciousness">
                <Select
                  value={form.consciousness}
                  onChange={(event) =>
                    setForm({ ...form, consciousness: event.target.value })
                  }
                >
                  <option value="alert">Alert</option>
                  <option value="voice">Responds to voice</option>
                  <option value="pain">Responds to pain</option>
                  <option value="unresponsive">Unresponsive</option>
                </Select>
              </Field>
              <Field label="Mobility">
                <Select
                  value={form.mobility}
                  onChange={(event) => setForm({ ...form, mobility: event.target.value })}
                >
                  <option value="independent">Independent</option>
                  <option value="assisted">Needs assistance</option>
                  <option value="bedbound">Bedbound</option>
                </Select>
              </Field>
            </div>
            <div className="flex flex-wrap gap-5">
              <label className="flex items-center gap-2 text-[12.5px] font-medium text-ink">
                <input
                  type="checkbox"
                  checked={form.falls_risk}
                  onChange={(event) =>
                    setForm({ ...form, falls_risk: event.target.checked })
                  }
                  className="size-4 rounded border-border"
                />
                At risk of falls
              </label>
              <label className="flex items-center gap-2 text-[12.5px] font-medium text-ink">
                <input
                  type="checkbox"
                  checked={form.pressure_area_concern}
                  onChange={(event) =>
                    setForm({ ...form, pressure_area_concern: event.target.checked })
                  }
                  className="size-4 rounded border-border"
                />
                Pressure-area concern
              </label>
            </div>
            <Field label="Summary">
              <Textarea
                value={form.summary}
                onChange={(event) => setForm({ ...form, summary: event.target.value })}
                placeholder="Settled overnight, taking oral fluids well."
              />
            </Field>
            <Button
              disabled={record.isPending}
              onClick={() =>
                record.mutate(
                  { admission: admissionId, ...form },
                  { onSuccess: () => setOpen(false) },
                )
              }
            >
              Record assessment
            </Button>
          </div>
        )}

        {rows.length === 0 ? (
          <EmptyState>No shift assessment has been recorded.</EmptyState>
        ) : (
          <ul className="space-y-3">
            {rows.map((row) => (
              <li key={row.id} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] font-semibold text-ink">
                    {row.shift_display} shift
                  </span>
                  <span className="text-[11.5px] text-ink-muted">
                    {row.recorded_by_name} · {dateAndTime(row.recorded_at)}
                  </span>
                  {row.falls_risk && <Badge tone="abnormal">Falls risk</Badge>}
                  {row.pressure_area_concern && (
                    <Badge tone="abnormal">Pressure areas</Badge>
                  )}
                </div>
                <p className="mt-1.5 text-[12px] text-ink-muted">
                  {row.consciousness_display} · {row.mobility_display}
                </p>
                {row.summary && (
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
                    {row.summary}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}
