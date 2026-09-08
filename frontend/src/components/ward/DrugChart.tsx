'use client'

import { useState } from 'react'
import { ErrorNotice, LoadingNotice } from '@/components/PageShell'
import { Button, EmptyState, Field, Panel, PanelHeader, Select, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type ChartCell,
  type ChartRow,
  useBedsideWarnings,
  useDiscontinueMedication,
  useDrugChart,
  useRecordDose,
} from '@/lib/inpatient'
import { useStockBatches } from '@/lib/pharmacy'
import { dateAndTime, doseLabel, doseMark, doseTone, timeOfDay, waitedFor } from '@/lib/workflow'

/**
 * The MAR, laid out as a chart.
 *
 * Rows are medications and columns are due times, because that is how a drug
 * chart is read: across a row to see whether a course is being given, and down
 * a column to see what is due at this round. Every cell carries the state as a
 * word as well as a colour — a ward monitor is not colour-calibrated, some
 * staff have colour-vision deficiency, and this prints.
 *
 * Recording a dose opens a panel rather than acting on a click. A single tap
 * that gives a drug is one misplaced finger away from a wrong administration,
 * and the batch and any override reason have to be captured anyway.
 */
export function DrugChart({ admissionId }: { admissionId: number }) {
  const { can } = useAuth()
  const [days, setDays] = useState(3)
  const chart = useDrugChart(admissionId, days)
  const [selected, setSelected] = useState<{ row: ChartRow; cell: ChartCell } | null>(null)

  const columns = chart.data?.columns ?? []
  const rows = chart.data?.rows ?? []

  return (
    <div className="space-y-5">
      <Panel>
        <PanelHeader
          title="Drug chart"
          hint="A dose with no outcome recorded is indistinguishable from a dose nobody gave, so it shows as overdue rather than blank."
          action={
            <Field label="Window">
              <Select
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
                className="py-1.5 text-[12.5px]"
              >
                <option value={1}>Today</option>
                <option value={3}>3 days</option>
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
              </Select>
            </Field>
          }
        />
        {chart.isError && (
          <div className="p-5">
            <ErrorNotice>Could not load the chart.</ErrorNotice>
          </div>
        )}
        {chart.isLoading && (
          <div className="p-5">
            <LoadingNotice>Loading the chart…</LoadingNotice>
          </div>
        )}
        {chart.data && rows.length === 0 && (
          <div className="p-5">
            <EmptyState>
              Nothing is on the chart. An inpatient prescription generates its due
              doses when it is written.
            </EmptyState>
          </div>
        )}

        {rows.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <caption className="sr-only">
                  Medication administration record: medications down, due times across.
                </caption>
                <thead>
                  <tr>
                    <th
                      scope="col"
                      className="sticky left-0 z-10 min-w-56 border-b border-border bg-surface-muted px-4 py-2.5 text-[11px] font-semibold tracking-[0.06em] text-ink-muted uppercase"
                    >
                      Medication
                    </th>
                    {columns.map((column) => (
                      <th
                        key={column}
                        scope="col"
                        className="border-b border-border bg-surface-muted px-2 py-2.5 text-center text-[11px] font-semibold text-ink-muted"
                      >
                        <span className="block">{timeOfDay(column)}</span>
                        <span className="block text-[10px] font-normal text-ink-faint">
                          {new Date(column).toLocaleDateString('en-GB', {
                            day: '2-digit',
                            month: 'short',
                          })}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.item_id} className="border-b border-border">
                      <th
                        scope="row"
                        className="sticky left-0 z-10 bg-surface px-4 py-3 text-left align-top"
                      >
                        <span className="block text-[13px] font-semibold text-ink">
                          {row.medication}
                        </span>
                        <span className="mt-0.5 block text-[11.5px] font-normal text-ink-muted">
                          {row.directions}
                        </span>
                        {row.status === 'cancelled' && (
                          <span className="mt-1 inline-block text-[10.5px] font-bold tracking-wide text-ink-faint uppercase">
                            Discontinued
                          </span>
                        )}
                      </th>
                      {columns.map((column) => {
                        const cell = row.cells[column]
                        if (!cell) {
                          return (
                            <td key={column} className="px-2 py-3 text-center">
                              <span className="text-ink-faint" aria-label="Not due">
                                ·
                              </span>
                            </td>
                          )
                        }
                        const actionable =
                          can('inpatient.add_medicationadministration') &&
                          ['due', 'overdue', 'scheduled'].includes(cell.status)
                        return (
                          <td key={column} className="px-2 py-3 text-center align-top">
                            <ChartCellButton
                              cell={cell}
                              actionable={actionable}
                              onSelect={() => setSelected({ row, cell })}
                            />
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap gap-3 border-t border-border px-4 py-3">
              {['administered', 'delayed', 'refused', 'withheld', 'missed', 'overdue', 'due'].map(
                (state) => (
                  <span key={state} className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className={`inline-flex size-5 items-center justify-center rounded text-[10px] font-bold ${cellClass(state)}`}
                    >
                      {doseMark(state)}
                    </span>
                    <span className="text-[11px] text-ink-muted">{doseLabel(state)}</span>
                  </span>
                ),
              )}
            </div>
          </>
        )}
      </Panel>

      {selected && (
        <RecordDosePanel
          row={selected.row}
          cell={selected.cell}
          onClose={() => setSelected(null)}
        />
      )}

      {rows.length > 0 && can('inpatient.change_scheduleddose') && (
        <DiscontinuePanel rows={rows} />
      )}
    </div>
  )
}

function cellClass(status: string) {
  const tone = doseTone(status)
  return {
    normal: 'bg-normal-muted text-normal',
    progress: 'bg-progress-muted text-progress',
    abnormal: 'bg-abnormal-muted text-abnormal',
    critical: 'bg-critical-muted text-critical',
    accent: 'bg-accent-muted text-accent',
    idle: 'bg-surface-muted text-ink-faint',
  }[tone]
}

function ChartCellButton({
  cell,
  actionable,
  onSelect,
}: {
  cell: ChartCell
  actionable: boolean
  onSelect: () => void
}) {
  /* The accessible name is the whole story of the cell, because the glyph is
     shorthand and a screen reader gets no colour at all. */
  const name = [
    doseLabel(cell.status),
    `due ${timeOfDay(cell.due_at)}`,
    cell.by ? `by ${cell.by}` : null,
    cell.minutes_late !== null && cell.minutes_late > 0
      ? `${waitedFor(cell.minutes_late)} late`
      : null,
    cell.reason || null,
  ]
    .filter(Boolean)
    .join(', ')

  const mark = (
    <span
      className={`inline-flex min-h-7 min-w-7 items-center justify-center rounded px-1 text-[10.5px] font-bold ${cellClass(cell.status)}`}
    >
      {doseMark(cell.status)}
    </span>
  )

  if (!actionable) {
    return (
      <span title={name} aria-label={name} className="inline-block">
        {mark}
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`Record: ${name}`}
      title={name}
      className="rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {mark}
    </button>
  )
}

const OUTCOMES = [
  { value: 'administered', label: 'Given', needsBatch: true, needsReason: false },
  { value: 'delayed', label: 'Given late', needsBatch: true, needsReason: false },
  { value: 'refused', label: 'Refused by patient', needsBatch: false, needsReason: true },
  { value: 'withheld', label: 'Withheld', needsBatch: false, needsReason: true },
  { value: 'missed', label: 'Missed', needsBatch: false, needsReason: true },
] as const

function RecordDosePanel({
  row,
  cell,
  onClose,
}: {
  row: ChartRow
  cell: ChartCell
  onClose: () => void
}) {
  const record = useRecordDose()
  const warnings = useBedsideWarnings(cell.dose_id)
  const batches = useStockBatches({ medication: row.medication_id, available: true })
  const [state, setState] = useState<string>('administered')
  const [batchId, setBatchId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [override, setOverride] = useState('')

  const outcome = OUTCOMES.find((entry) => entry.value === state)
  const hasWarnings = (warnings.data?.warnings.length ?? 0) > 0
  const fieldErrors = record.error instanceof ApiError ? record.error.fields : {}
  const detail =
    record.error instanceof ApiError && Object.keys(fieldErrors).length === 0
      ? record.error.message
      : null

  const ready =
    (!outcome?.needsBatch || batchId !== null) &&
    (!outcome?.needsReason || reason.trim().length > 0) &&
    (!hasWarnings || !outcome?.needsBatch || override.trim().length > 0)

  return (
    <Panel>
      <PanelHeader
        title={`Record: ${row.medication}`}
        hint={`Due ${dateAndTime(cell.due_at)} — ${row.directions}`}
        action={
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      />
      <div className="space-y-4 p-5">
        {detail && <ErrorNotice>{detail}</ErrorNotice>}
        {record.isSuccess && (
          <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            Recorded. The chart above has been updated.
          </p>
        )}

        {hasWarnings && (
          <div
            role="alert"
            className="rounded-lg border border-critical/40 bg-critical-muted px-4 py-3"
          >
            <p className="text-[12.5px] font-bold text-critical">
              <span aria-hidden>▲ </span>
              Checked again at the bedside
            </p>
            <ul className="mt-1.5 space-y-1">
              {warnings.data?.warnings.map((warning) => (
                <li key={warning.detail} className="text-[12px] text-critical">
                  {warning.detail}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] leading-relaxed text-critical/90">
              The prescriber may have overridden this, the allergy may have been
              recorded since, or this may be the wrong patient&apos;s trolley.
            </p>
          </div>
        )}

        <Field label="What happened to this dose?" required>
          <Select value={state} onChange={(event) => setState(event.target.value)}>
            {OUTCOMES.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </Select>
        </Field>

        {outcome?.needsBatch && (
          <Field
            label="Batch"
            hint="Which pack the dose came from. An expired batch is refused."
            error={fieldErrors.batch}
            required
          >
            <Select
              value={batchId ?? ''}
              onChange={(event) =>
                setBatchId(event.target.value ? Number(event.target.value) : null)
              }
            >
              <option value="">Choose a batch…</option>
              {(batches.data ?? []).map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {batch.batch_number} — expires {batch.expiry_date} (
                  {batch.quantity_on_hand} left)
                </option>
              ))}
            </Select>
          </Field>
        )}

        {outcome?.needsReason && (
          <Field
            label="Why did this dose not reach the patient?"
            hint="Required. A gap with no explanation is not a record."
            error={fieldErrors.reason}
            required
          >
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Patient declined, felt nauseated."
            />
          </Field>
        )}

        {hasWarnings && outcome?.needsBatch && (
          <Field
            label="Reason for giving it anyway"
            hint="Recorded against the administration and audited."
            error={fieldErrors.override_reason}
            required
          >
            <Textarea
              value={override}
              onChange={(event) => setOverride(event.target.value)}
              placeholder="Documented mild rash only; prescriber aware, first dose tolerated."
            />
          </Field>
        )}

        <div className="flex gap-2">
          <Button
            disabled={!ready || record.isPending}
            onClick={() =>
              record.mutate(
                {
                  id: cell.dose_id,
                  state,
                  batch: outcome?.needsBatch ? batchId : null,
                  reason: reason.trim(),
                  override_reason: override.trim(),
                },
                { onSuccess: onClose },
              )
            }
          >
            {record.isPending ? 'Recording…' : 'Record this dose'}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
        <p className="text-[11px] text-ink-faint">
          Recording twice produces one administration, not two — the dose can
          only have one outcome.
        </p>
      </div>
    </Panel>
  )
}

function DiscontinuePanel({ rows }: { rows: ChartRow[] }) {
  const discontinue = useDiscontinueMedication()
  const [itemId, setItemId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const active = rows.filter((row) => row.status !== 'cancelled')

  if (active.length === 0) return null

  return (
    <Panel>
      <PanelHeader
        title="Stop a medication"
        hint="Future doses are cancelled. Doses already given stay on the chart exactly as they were."
      />
      <div className="space-y-4 p-5">
        {discontinue.error instanceof ApiError && (
          <ErrorNotice>{discontinue.error.message}</ErrorNotice>
        )}
        {discontinue.isSuccess && discontinue.data && (
          <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            Stopped. {discontinue.data.future_doses_cancelled} future dose
            {discontinue.data.future_doses_cancelled === 1 ? '' : 's'} cancelled;{' '}
            {discontinue.data.doses_already_given} already given and kept on the record.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Medication" required>
            <Select
              value={itemId ?? ''}
              onChange={(event) =>
                setItemId(event.target.value ? Number(event.target.value) : null)
              }
            >
              <option value="">Choose…</option>
              {active.map((row) => (
                <option key={row.item_id} value={row.item_id}>
                  {row.medication}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Reason" hint="Recorded and audited." required>
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Widespread rash, switching to azithromycin."
            />
          </Field>
        </div>
        <Button
          variant="danger"
          disabled={itemId === null || !reason.trim() || discontinue.isPending}
          onClick={() =>
            discontinue.mutate(
              { prescription_item: itemId as number, reason: reason.trim() },
              { onSuccess: () => { setItemId(null); setReason('') } },
            )
          }
        >
          Stop this medication
        </Button>
      </div>
    </Panel>
  )
}
