'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
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
  type ImagingOrderItemRow,
  type ImagingReportRow,
  type ImagingWorklistRow,
  isWithheld,
  useAmendImagingReport,
  useCancelImagingItem,
  useCriticalFindings,
  useImagingOrder,
  useImagingWorklist,
  usePerformImaging,
  useScheduleImaging,
  useVerifyImagingReport,
  useWriteImagingReport,
} from '@/lib/imaging'
import { dateAndTime, imagingLabel, imagingTone } from '@/lib/workflow'

/**
 * The radiology department.
 *
 * Worklist on the left, the selected examination's workspace on the right —
 * a radiographer works through a list rather than searching for one request at
 * a time. Urgent first, then oldest.
 *
 * The states advance in sequence and the server refuses skipping: a study
 * cannot be reported before it was performed, because "performed" is what the
 * department bills and what the patient was exposed to.
 */
export default function ImagingPage() {
  const { can } = useAuth()
  const worklist = useImagingWorklist()
  const criticals = useCriticalFindings()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState('all')

  const all = worklist.data ?? []
  const rows = all.filter((row) =>
    filter === 'all'
      ? true
      : filter === 'urgent'
        ? row.priority === 'urgent'
        : row.status === filter,
  )
  const counts = {
    requested: all.filter((row) => row.status === 'requested').length,
    scheduled: all.filter((row) => row.status === 'scheduled').length,
    performed: all.filter((row) => row.status === 'performed').length,
    reported: all.filter((row) => row.status === 'reported').length,
  }

  const selected = all.find((row) => row.item === selectedId) ?? null
  const unanswered = criticals.data?.length ?? 0

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Radiology
      </div>
      <PageHeading
        title="Worklist"
        subtitle="Requests to schedule, studies to perform, reports to verify."
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/imaging/critical"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-semibold ${
                unanswered
                  ? 'bg-critical text-white hover:opacity-90'
                  : 'border border-border text-ink hover:bg-surface-muted'
              }`}
            >
              {unanswered ? <AlertIcon className="size-4" /> : null}
              Critical findings{unanswered ? ` (${unanswered})` : ''}
            </Link>
            <Link
              href="/imaging/catalogue"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
            >
              Catalogue
            </Link>
          </div>
        }
      />

      {worklist.isError && <ErrorNotice>Could not load the worklist.</ErrorNotice>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <Panel>
          <PanelHeader
            title={`${rows.length} examination${rows.length === 1 ? '' : 's'}`}
            hint="Urgent ahead of routine, then oldest first."
            action={
              <Field label="Show">
                <Select
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  className="py-1.5 text-[12.5px]"
                >
                  <option value="all">Everything</option>
                  <option value="urgent">Urgent only</option>
                  <option value="requested">To schedule ({counts.requested})</option>
                  <option value="scheduled">Scheduled ({counts.scheduled})</option>
                  <option value="performed">To report ({counts.performed})</option>
                  <option value="reported">To verify ({counts.reported})</option>
                </Select>
              </Field>
            }
          />
          {worklist.isLoading && (
            <div className="p-5">
              <LoadingNotice>Loading the worklist…</LoadingNotice>
            </div>
          )}
          {!worklist.isLoading && rows.length === 0 && (
            <div className="p-5">
              <EmptyState>Nothing matches. The department is clear.</EmptyState>
            </div>
          )}
          <ul className="divide-y divide-border">
            {rows.map((row) => (
              <li key={row.item}>
                <button
                  type="button"
                  onClick={() => setSelectedId(row.item)}
                  aria-current={selectedId === row.item}
                  className={`w-full px-5 py-4 text-left transition-colors ${
                    selectedId === row.item
                      ? 'bg-accent-muted/30'
                      : 'hover:bg-surface-muted/60'
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <span className="block text-[13.5px] font-semibold text-ink">
                        {row.patient}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.hospital_number} · {row.order_number}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {row.priority === 'urgent' && <Badge tone="critical">Urgent</Badge>}
                      <Badge tone={imagingTone(row.status)}>
                        {imagingLabel(row.status)}
                      </Badge>
                    </div>
                  </div>
                  <p className="mt-2 text-[12.5px] font-medium text-ink">
                    {row.procedure}
                    <span className="ml-2 font-normal text-ink-muted">
                      {row.modality} · {row.body_part}
                    </span>
                  </p>
                  <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
                    {row.clinical_question}
                  </p>
                  {(row.is_pregnant || row.requires_contrast) && (
                    <p className="mt-1.5 text-[11.5px] font-semibold text-abnormal">
                      <span aria-hidden>▲ </span>
                      {row.is_pregnant && 'Pregnancy declared. '}
                      {row.requires_contrast && 'Contrast study. '}
                      {row.contraindications}
                    </p>
                  )}
                  <p className="mt-1.5 text-[11px] text-ink-faint">
                    Requested {dateAndTime(row.ordered_at)}
                    {row.scheduled_for && ` · slot ${dateAndTime(row.scheduled_for)}`}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        {selected ? (
          <Workspace row={selected} onDone={() => setSelectedId(null)} />
        ) : (
          <Panel>
            <PanelHeader
              title="No examination selected"
              hint="Choose one from the worklist."
            />
            <div className="p-5">
              <EmptyState>
                Pick an examination to schedule it, record that it was performed,
                write its report, or verify one.
              </EmptyState>
            </div>
          </Panel>
        )}
      </div>
    </PageShell>
  )
}

function Workspace({ row, onDone }: { row: ImagingWorklistRow; onDone: () => void }) {
  const order = useImagingOrder(row.order)
  const item = order.data?.items.find((entry) => entry.id === row.item) ?? null

  return (
    <Panel>
      <PanelHeader
        title={row.procedure}
        hint={`${row.patient} · ${row.hospital_number} · ${row.order_number}`}
        action={
          <Button variant="ghost" onClick={onDone}>
            Close
          </Button>
        }
      />
      <div className="space-y-5 p-5">
        {order.isLoading && <LoadingNotice>Loading the examination…</LoadingNotice>}
        {order.isError && <ErrorNotice>Could not load it.</ErrorNotice>}

        {order.data && item && (
          <>
            <dl className="grid gap-x-6 gap-y-2 text-[12.5px] sm:grid-cols-2">
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">
                  Clinical question
                </dt>
                <dd className="mt-0.5 text-ink">{order.data.clinical_question}</dd>
              </div>
              <div>
                <dt className="text-[11.5px] font-semibold text-ink-muted">
                  Requested by
                </dt>
                <dd className="mt-0.5 text-ink">{order.data.ordered_by_name}</dd>
              </div>
              {order.data.relevant_history && (
                <div className="sm:col-span-2">
                  <dt className="text-[11.5px] font-semibold text-ink-muted">History</dt>
                  <dd className="mt-0.5 text-ink">{order.data.relevant_history}</dd>
                </div>
              )}
              {item.preparation_instructions && (
                <div className="sm:col-span-2">
                  <dt className="text-[11.5px] font-semibold text-ink-muted">
                    Preparation
                  </dt>
                  <dd className="mt-0.5 text-ink">{item.preparation_instructions}</dd>
                </div>
              )}
            </dl>

            <Stage item={item} onDone={onDone} />
          </>
        )}
      </div>
    </Panel>
  )
}

function Stage({ item, onDone }: { item: ImagingOrderItemRow; onDone: () => void }) {
  const { can } = useAuth()

  return (
    <div className="space-y-4 border-t border-border pt-4">
      {item.status === 'requested' && can('imaging.schedule_imaging') && (
        <ScheduleForm item={item} />
      )}
      {['requested', 'scheduled'].includes(item.status) &&
        can('imaging.perform_imaging') && <PerformForm item={item} />}
      {item.status === 'performed' && can('imaging.add_imagingreport') && (
        <ReportForm item={item} />
      )}
      {item.report && !isWithheld(item.report) && (
        <ReportView item={item} report={item.report} />
      )}
      {item.report && isWithheld(item.report) && (
        <p className="rounded-md bg-surface-muted px-4 py-3 text-[12.5px] text-ink-muted">
          A report exists and has not been released. Only the department can read a
          draft.
        </p>
      )}
      {item.report_history.length > 0 && (
        <section>
          <h3 className="mb-2 text-[11px] font-bold tracking-[0.08em] text-ink-muted uppercase">
            Superseded reports
          </h3>
          <ul className="space-y-2">
            {item.report_history.map((entry) => (
              <li
                key={entry.id}
                className="rounded-lg border border-dashed border-border bg-surface-muted/40 p-3"
              >
                <p className="text-[11px] font-bold tracking-wide text-ink-faint uppercase">
                  Version {entry.version} — superseded
                </p>
                <p className="mt-1 text-[12.5px] font-semibold text-ink-muted">
                  {entry.conclusion}
                </p>
                <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
                  {entry.findings}
                </p>
                <p className="mt-1.5 text-[11px] text-ink-faint">
                  {entry.reported_by} · {dateAndTime(entry.reported_at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {can('imaging.change_imagingorderitem') &&
        item.allowed_transitions.includes('cancelled') && (
          <CancelForm item={item} onDone={onDone} />
        )}
    </div>
  )
}

function ScheduleForm({ item }: { item: ImagingOrderItemRow }) {
  const schedule = useScheduleImaging()
  const [when, setWhen] = useState('')

  return (
    <form
      className="space-y-3 rounded-xl bg-surface-muted/50 p-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (when) schedule.mutate({ id: item.id, scheduled_for: new Date(when).toISOString() })
      }}
    >
      <h3 className="text-[13px] font-semibold text-ink">Give it a slot</h3>
      {schedule.error instanceof ApiError && (
        <ErrorNotice>{schedule.error.message}</ErrorNotice>
      )}
      <Field label="Date and time" required>
        <Input
          type="datetime-local"
          value={when}
          onChange={(event) => setWhen(event.target.value)}
        />
      </Field>
      <Button type="submit" disabled={!when || schedule.isPending}>
        {schedule.isPending ? 'Scheduling…' : 'Schedule'}
      </Button>
    </form>
  )
}

function PerformForm({ item }: { item: ImagingOrderItemRow }) {
  const perform = usePerformImaging()
  const [form, setForm] = useState({
    accession_number: '',
    views_taken: '',
    technique_note: '',
    contrast_given: '',
  })

  return (
    <form
      className="space-y-3 rounded-xl bg-surface-muted/50 p-4"
      onSubmit={(event) => {
        event.preventDefault()
        perform.mutate({ id: item.id, ...form })
      }}
    >
      <h3 className="text-[13px] font-semibold text-ink">Record it as performed</h3>
      <p className="text-[11.5px] leading-relaxed text-ink-faint">
        This is what the department bills and what the patient was exposed to, so it
        records who operated the machine and when. The charge is raised here, not at
        ordering — a request that is never performed does not reach a bill.
      </p>
      {perform.error instanceof ApiError && <ErrorNotice>{perform.error.message}</ErrorNotice>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Accession number" hint="The department's own study identifier.">
          <Input
            value={form.accession_number}
            onChange={(event) =>
              setForm({ ...form, accession_number: event.target.value })
            }
            placeholder="ACC-000123"
          />
        </Field>
        <Field label="Views taken">
          <Input
            value={form.views_taken}
            onChange={(event) => setForm({ ...form, views_taken: event.target.value })}
            placeholder="PA erect"
          />
        </Field>
        <Field label="Technique note">
          <Input
            value={form.technique_note}
            onChange={(event) => setForm({ ...form, technique_note: event.target.value })}
          />
        </Field>
        <Field label="Contrast given">
          <Input
            value={form.contrast_given}
            onChange={(event) => setForm({ ...form, contrast_given: event.target.value })}
            placeholder="Omnipaque 100 mL IV"
          />
        </Field>
      </div>
      <Button type="submit" disabled={perform.isPending}>
        {perform.isPending ? 'Recording…' : 'Mark performed'}
      </Button>
    </form>
  )
}

function ReportForm({ item }: { item: ImagingOrderItemRow }) {
  const write = useWriteImagingReport()
  const [findings, setFindings] = useState('')
  const [conclusion, setConclusion] = useState('')
  const [comparison, setComparison] = useState('')
  const [critical, setCritical] = useState(false)
  const [finding, setFinding] = useState('')

  const fieldErrors = write.error instanceof ApiError ? write.error.fields : {}

  return (
    <form
      className="space-y-3 rounded-xl bg-surface-muted/50 p-4"
      onSubmit={(event) => {
        event.preventDefault()
        write.mutate({
          id: item.id,
          findings,
          conclusion,
          comparison,
          is_critical: critical,
          critical_finding: finding,
        })
      }}
    >
      <h3 className="text-[13px] font-semibold text-ink">Write the report</h3>
      <p className="text-[11.5px] leading-relaxed text-ink-faint">
        Saved unverified. Until a radiologist releases it, the requesting clinician
        is told a report exists and is not shown its text.
      </p>
      {write.error instanceof ApiError && Object.keys(fieldErrors).length === 0 && (
        <ErrorNotice>{write.error.message}</ErrorNotice>
      )}
      <Field label="Findings" error={fieldErrors.findings} required>
        <Textarea
          value={findings}
          onChange={(event) => setFindings(event.target.value)}
          className="min-h-28"
          placeholder="Right lower lobe airspace opacification. Heart size normal. No effusion."
        />
      </Field>
      <Field
        label="Conclusion"
        hint="What the clinician acts on, and what goes in a discharge summary. Kept separate so it cannot be buried in the findings."
        error={fieldErrors.conclusion}
        required
      >
        <Textarea
          value={conclusion}
          onChange={(event) => setConclusion(event.target.value)}
          placeholder="Right lower lobe consolidation."
        />
      </Field>
      <Field label="Compared against">
        <Input
          value={comparison}
          onChange={(event) => setComparison(event.target.value)}
          placeholder="CXR 12 Aug 2026"
        />
      </Field>
      <label className="flex items-start gap-2 text-[12.5px] font-medium text-ink">
        <input
          type="checkbox"
          checked={critical}
          onChange={(event) => setCritical(event.target.checked)}
          className="mt-0.5 size-4 rounded border-border"
        />
        <span>
          This is a critical finding
          <span className="mt-0.5 block text-[11px] font-normal text-ink-faint">
            Somebody has to act on it now. It goes on the department&apos;s chase
            list until they record what they did.
          </span>
        </span>
      </label>
      {critical && (
        <Field
          label="What has to be acted on"
          hint="One line. This is what reaches the clinician."
          error={fieldErrors.critical_finding}
          required
        >
          <Input
            value={finding}
            onChange={(event) => setFinding(event.target.value)}
            placeholder="Tension pneumothorax — decompress now"
          />
        </Field>
      )}
      <Button
        type="submit"
        disabled={
          !findings.trim() ||
          !conclusion.trim() ||
          (critical && !finding.trim()) ||
          write.isPending
        }
      >
        {write.isPending ? 'Saving…' : 'Save report'}
      </Button>
    </form>
  )
}

function ReportView({
  item,
  report,
}: {
  item: ImagingOrderItemRow
  /* Already narrowed by the caller's `isWithheld` guard, which is why the
     withheld shape is a different type rather than a report with blank text. */
  report: ImagingReportRow
}) {
  const { can } = useAuth()
  const verify = useVerifyImagingReport()
  const amend = useAmendImagingReport()
  const [amending, setAmending] = useState(false)
  const [reason, setReason] = useState('')
  const [findings, setFindings] = useState(report.findings)
  const [conclusion, setConclusion] = useState(report.conclusion)

  const fieldErrors = amend.error instanceof ApiError ? amend.error.fields : {}

  return (
    <section className="space-y-3">
      <div
        className={`rounded-xl border p-4 ${
          report.is_verified ? 'border-border bg-surface' : 'border-abnormal/40 bg-abnormal-muted/30'
        }`}
      >
        <p
          className={`text-[11px] font-bold tracking-[0.08em] uppercase ${
            report.is_verified
              ? report.is_amended
                ? 'text-abnormal'
                : 'text-normal'
              : 'text-abnormal'
          }`}
        >
          {report.status_label}
        </p>
        {report.is_critical && (
          <p className="mt-2 rounded bg-critical-muted px-2.5 py-1.5 text-[12px] font-bold text-critical">
            <span aria-hidden>▲ </span>
            {report.critical_finding}
          </p>
        )}
        <p className="mt-2.5 text-[13px] font-semibold text-ink">{report.conclusion}</p>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
          {report.findings}
        </p>
        {report.comparison && (
          <p className="mt-1.5 text-[11.5px] text-ink-faint">
            Compared against {report.comparison}
          </p>
        )}
        {report.amendment_reason && (
          <p className="mt-2 text-[11.5px] text-ink-muted">
            Amended because: {report.amendment_reason}
          </p>
        )}
        <p className="mt-2 text-[11px] text-ink-faint">
          Reported by {report.reported_by_name}, {dateAndTime(report.reported_at)}
          {report.verified_by_name &&
            ` · verified by ${report.verified_by_name}, ${dateAndTime(report.verified_at as string)}`}
        </p>
        {report.acknowledgements.length > 0 && (
          <ul className="mt-2.5 space-y-1.5 border-t border-border pt-2.5">
            {report.acknowledgements.map((entry) => (
              <li key={entry.id} className="text-[11.5px] text-ink">
                <span className="font-semibold">{entry.acknowledged_by_name}</span> acted
                after {entry.minutes_to_acknowledge} min: {entry.action_taken}
              </li>
            ))}
          </ul>
        )}
      </div>

      {!report.is_verified && can('imaging.verify_imagingreport') && (
        <div className="space-y-2">
          {verify.error instanceof ApiError && (
            <ErrorNotice>{verify.error.message}</ErrorNotice>
          )}
          <Button disabled={verify.isPending} onClick={() => verify.mutate(report.id)}>
            {verify.isPending ? 'Releasing…' : 'Verify and release'}
          </Button>
          <p className="text-[11px] text-ink-faint">
            Typing a report and standing behind it are different acts. Releasing it
            sends it to {'the requesting clinician'}.
          </p>
        </div>
      )}

      {report.is_verified && can('imaging.amend_imagingreport') && (
        <div>
          {!amending ? (
            <button
              type="button"
              onClick={() => setAmending(true)}
              className="text-[12px] font-medium text-ink-muted hover:text-accent"
            >
              Amend this report
            </button>
          ) : (
            <form
              className="space-y-3 rounded-xl bg-surface-muted/50 p-4"
              onSubmit={(event) => {
                event.preventDefault()
                amend.mutate(
                  { id: report.id, reason, findings, conclusion },
                  { onSuccess: () => setAmending(false) },
                )
              }}
            >
              <h3 className="text-[13px] font-semibold text-ink">Amend the report</h3>
              <p className="text-[11.5px] leading-relaxed text-ink-faint">
                Appends a version. The report above stays exactly as written and prints
                as superseded — somebody may have made a decision on it. The requesting
                clinician is told, urgently.
              </p>
              {amend.error instanceof ApiError &&
                Object.keys(fieldErrors).length === 0 && (
                  <ErrorNotice>{amend.error.message}</ErrorNotice>
                )}
              <Field
                label="Why does it need amending?"
                error={fieldErrors.reason}
                required
              >
                <Input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Undisplaced fracture visible on review with the prior film."
                />
              </Field>
              <Field label="Findings" required>
                <Textarea
                  value={findings}
                  onChange={(event) => setFindings(event.target.value)}
                  className="min-h-24"
                />
              </Field>
              <Field label="Conclusion" required>
                <Textarea
                  value={conclusion}
                  onChange={(event) => setConclusion(event.target.value)}
                />
              </Field>
              <div className="flex gap-2">
                <Button
                  type="submit"
                  disabled={!reason.trim() || !conclusion.trim() || amend.isPending}
                >
                  Append the amendment
                </Button>
                <Button variant="ghost" onClick={() => setAmending(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  )
}

function CancelForm({
  item,
  onDone,
}: {
  item: ImagingOrderItemRow
  onDone: () => void
}) {
  const cancel = useCancelImagingItem()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[12px] font-medium text-ink-muted hover:text-critical"
      >
        Cancel this examination
      </button>
    )
  }
  return (
    <div className="space-y-2 rounded-xl border border-critical/30 bg-critical-muted/20 p-4">
      {cancel.error instanceof ApiError && <ErrorNotice>{cancel.error.message}</ErrorNotice>}
      <Field label="Why?" hint="Recorded against the examination." required>
        <Input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Patient discharged before the slot."
        />
      </Field>
      <div className="flex gap-2">
        <Button
          variant="danger"
          disabled={!reason.trim() || cancel.isPending}
          onClick={() =>
            cancel.mutate({ id: item.id, reason: reason.trim() }, { onSuccess: onDone })
          }
        >
          Cancel it
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Keep it
        </Button>
      </div>
    </div>
  )
}
