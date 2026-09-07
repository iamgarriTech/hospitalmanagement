'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import {
  Badge, Button, ClinicalFlag, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useLabTests } from '@/lib/clinical'
import {
  type SpecimenLabel, useAmendResult, useCollectSpecimen, useEnterResults, useLabOrderItem,
  useStartProcessing, useVerifyResults,
} from '@/lib/laboratory'
import { useCriticalResults, useLabWorklist } from '@/lib/queries'
import { dateAndTime, labLabel, labTone } from '@/lib/workflow'

/**
 * The laboratory bench.
 *
 * Worklist on the left, the selected specimen's workspace on the right, because
 * a scientist works through a list rather than searching for one order at a
 * time. Urgent first, then oldest.
 *
 * The stages advance in sequence and the server refuses skipping — you cannot
 * enter a result for a specimen nobody has collected.
 */
export default function LaboratoryPage() {
  const { can } = useAuth()
  const worklist = useLabWorklist()
  const criticals = useCriticalResults()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState('all')

  const rows = (worklist.data ?? []).filter((row) =>
    filter === 'all' ? true : filter === 'urgent' ? row.priority === 'urgent' : row.status === filter,
  )
  const counts = {
    ordered: (worklist.data ?? []).filter((row) => row.status === 'ordered').length,
    bench: (worklist.data ?? []).filter((row) =>
      ['collected', 'processing'].includes(row.status),
    ).length,
    resulted: (worklist.data ?? []).filter((row) => row.status === 'resulted').length,
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Laboratory
      </div>
      <PageHeading
        title="Worklist"
        subtitle="Specimens to collect, samples on the bench, results to verify."
        action={
          <div className="flex gap-2">
            <Link
              href="/laboratory/critical"
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-[13px] font-semibold ${
                (criticals.data?.length ?? 0) > 0
                  ? 'bg-critical text-white hover:opacity-90'
                  : 'border border-border text-ink hover:bg-surface-muted'
              }`}
            >
              {(criticals.data?.length ?? 0) > 0 && <AlertIcon className="size-4" />}
              Critical results
              {(criticals.data?.length ?? 0) > 0 && ` (${criticals.data!.length})`}
            </Link>
            <Button variant="secondary" onClick={() => worklist.refetch()} disabled={worklist.isFetching}>
              {worklist.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      <div className="mt-6 grid grid-cols-3 gap-3">
        <Stat label="To collect" value={counts.ordered} />
        <Stat label="On the bench" value={counts.bench} tone="progress" />
        <Stat label="To verify" value={counts.resulted} tone="abnormal" />
      </div>

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[380px_1fr]">
        <Panel>
          <PanelHeader
            title="Worklist"
            hint={`${rows.length} of ${(worklist.data ?? []).length}`}
            action={
              <Select
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                aria-label="Filter worklist"
                className="w-auto py-1 text-[12px]"
              >
                <option value="all">All</option>
                <option value="urgent">Urgent only</option>
                <option value="ordered">To collect</option>
                <option value="collected">Collected</option>
                <option value="processing">Processing</option>
                <option value="resulted">To verify</option>
              </Select>
            }
          />
          {worklist.isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
              Loading…
            </p>
          ) : rows.length === 0 ? (
            <div className="p-5">
              <EmptyState>Nothing on the worklist.</EmptyState>
            </div>
          ) : (
            <ul className="max-h-[620px] divide-y divide-border overflow-y-auto">
              {rows.map((row) => (
                <li key={row.item_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(row.item_id)}
                    aria-current={row.item_id === selectedId}
                    className={`block w-full px-5 py-3 text-left transition-colors ${
                      row.item_id === selectedId ? 'bg-accent-muted' : 'hover:bg-surface-muted'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[12.5px] font-semibold text-ink">
                        {row.test}
                      </span>
                      {row.priority === 'urgent' ? (
                        <Badge tone="critical">Urgent</Badge>
                      ) : (
                        <Badge tone={labTone(row.status)}>{labLabel(row.status)}</Badge>
                      )}
                    </span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-ink-muted">
                      {row.patient_name} · {row.hospital_number}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-faint">
                      {row.order_number} · {dateAndTime(row.ordered_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {selectedId === null ? (
          <Panel className="p-5">
            <EmptyState>Select a specimen from the worklist.</EmptyState>
          </Panel>
        ) : (
          <BenchWorkspace itemId={selectedId} canVerify={can('laboratory.verify_labresult')} />
        )}
      </div>
    </PageShell>
  )
}

function Stat({ label, value, tone = 'idle' }: { label: string; value: number; tone?: 'idle' | 'progress' | 'abnormal' }) {
  const colour =
    value === 0 ? 'text-ink' : tone === 'abnormal' ? 'text-abnormal' : tone === 'progress' ? 'text-progress' : 'text-ink'
  return (
    <Panel className="px-5 py-4">
      <p className="text-[11.5px] text-ink-muted">{label}</p>
      <p className={`mt-1.5 text-[24px] leading-none font-semibold ${colour}`}>{value}</p>
    </Panel>
  )
}

/**
 * Collect → process → result → verify, with only the legal next action offered.
 */
function BenchWorkspace({ itemId, canVerify }: { itemId: number; canVerify: boolean }) {
  const item = useLabOrderItem(itemId)
  const tests = useLabTests()
  const collect = useCollectSpecimen()
  const startProcessing = useStartProcessing()
  const enterResults = useEnterResults()
  const verify = useVerifyResults()

  const [condition, setCondition] = useState('acceptable')
  const [values, setValues] = useState<Record<number, string>>({})
  const [comment, setComment] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [label, setLabel] = useState<SpecimenLabel | null>(null)

  const record = item.data
  const test = tests.data?.find((entry) => entry.id === record?.test)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That action could not be completed.')
    }
  }

  if (item.isLoading || !record) {
    return (
      <Panel className="p-5">
        <p role="status" className="text-[13px] text-ink-muted">Loading the specimen…</p>
      </Panel>
    )
  }

  return (
    <div className="grid gap-5">
      <Panel>
        <PanelHeader
          title={record.test_name}
          hint={record.specimen ? `Specimen ${record.specimen.specimen_id}` : 'No specimen yet'}
          action={<Badge tone={labTone(record.status)}>{labLabel(record.status)}</Badge>}
        />

        {error && <div className="p-5 pb-0"><ErrorNotice>{error}</ErrorNotice></div>}

        {label && (
          <div className="m-5 rounded-lg border-2 border-dashed border-border p-4">
            <p className="text-[10.5px] font-bold tracking-[0.09em] text-ink-faint uppercase">
              Specimen label
            </p>
            <p className="mt-1.5 font-mono text-[18px] font-bold text-ink">{label.specimen_id}</p>
            <p className="mt-1 text-[13px] font-semibold text-ink">{label.patient_name}</p>
            <p className="text-[12px] text-ink-muted">
              {label.hospital_number} · {label.test}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">{dateAndTime(label.collected_at)}</p>
            <div className="mt-3 flex gap-2 no-print">
              <Button variant="secondary" onClick={() => window.print()}>Print label</Button>
              <Button variant="ghost" onClick={() => setLabel(null)}>Dismiss</Button>
            </div>
          </div>
        )}

        <div className="p-5">
          {record.status === 'ordered' && (
            <div className="grid gap-4 sm:grid-cols-[200px_1fr] sm:items-end">
              <Field label="Specimen condition">
                <Select value={condition} onChange={(event) => setCondition(event.target.value)}>
                  <option value="acceptable">Acceptable</option>
                  <option value="haemolysed">Haemolysed</option>
                  <option value="insufficient">Insufficient volume</option>
                  <option value="clotted">Clotted</option>
                </Select>
              </Field>
              <div>
                <Button
                  disabled={collect.isPending}
                  onClick={() =>
                    run(async () => {
                      const result = await collect.mutateAsync({ id: itemId, condition })
                      setLabel(result.label)
                    })
                  }
                  className="px-4 py-2.5"
                >
                  {collect.isPending ? 'Collecting…' : 'Collect specimen and issue label'}
                </Button>
              </div>
            </div>
          )}

          {record.status === 'collected' && (
            <Button
              disabled={startProcessing.isPending}
              onClick={() => run(() => startProcessing.mutateAsync(itemId))}
              className="px-4 py-2.5"
            >
              {startProcessing.isPending ? 'Starting…' : 'Start processing'}
            </Button>
          )}

          {record.status === 'processing' && test && (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                const entries = test.parameters
                  .filter((parameter) => values[parameter.id]?.trim())
                  .map((parameter) =>
                    parameter.value_type === 'numeric'
                      ? { parameter: parameter.id, value_numeric: values[parameter.id] }
                      : { parameter: parameter.id, value_text: values[parameter.id] },
                  )
                run(() => enterResults.mutateAsync({ id: itemId, entries }))
              }}
            >
              <p className="mb-4 text-[12.5px] text-ink-muted">
                {test.parameters.length} measurement{test.parameters.length === 1 ? '' : 's'} for
                this test. Each is flagged against this patient&apos;s own reference range.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {test.parameters.map((parameter) => (
                  <Field key={parameter.id} label={`${parameter.name}${parameter.unit ? ` (${parameter.unit})` : ''}`}>
                    {parameter.value_type === 'choice' ? (
                      <Select
                        value={values[parameter.id] ?? ''}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [parameter.id]: event.target.value }))
                        }
                      >
                        <option value="">—</option>
                        {parameter.choices_csv.split(',').filter(Boolean).map((choice) => (
                          <option key={choice} value={choice.trim()}>
                            {choice.trim()}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      <Input
                        inputMode="decimal"
                        value={values[parameter.id] ?? ''}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [parameter.id]: event.target.value }))
                        }
                        className="text-right"
                      />
                    )}
                  </Field>
                ))}
              </div>
              <div className="mt-4">
                <Button
                  type="submit"
                  disabled={
                    enterResults.isPending ||
                    !test.parameters.some((parameter) => values[parameter.id]?.trim())
                  }
                  className="px-4 py-2.5"
                >
                  {enterResults.isPending ? 'Saving…' : 'Enter results'}
                </Button>
              </div>
            </form>
          )}

          {record.status === 'resulted' && (
            <div className="grid gap-4">
              <p className="text-[12.5px] text-ink-muted">
                Entered by {record.results[0]?.entered_by_email}. Verification releases these to
                the requesting clinician — until then the report shows the test as pending.
              </p>
              <Field label="Laboratory comment" hint="Appears on the report.">
                <Textarea
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  className="min-h-[38px]"
                  placeholder="Film reviewed"
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                {canVerify ? (
                  <Button
                    disabled={verify.isPending}
                    onClick={() => run(() => verify.mutateAsync({ id: itemId, comment }))}
                    className="px-4 py-2.5"
                  >
                    {verify.isPending ? 'Verifying…' : 'Verify and release'}
                  </Button>
                ) : (
                  <p className="text-[12.5px] text-ink-muted">
                    You entered these results but do not hold the verification permission.
                    Someone else has to sign them off.
                  </p>
                )}
              </div>
            </div>
          )}

          {record.status === 'verified' && (
            <p className="text-[12.5px] text-normal">
              Verified by {record.verified_by_email}
              {record.verified_at && ` on ${dateAndTime(record.verified_at)}`}.
              {record.laboratory_comment && ` — ${record.laboratory_comment}`}
            </p>
          )}
        </div>
      </Panel>

      {record.results.length > 0 && (
        <ResultsPanel item={record} />
      )}
    </div>
  )
}

function ResultsPanel({ item }: { item: NonNullable<ReturnType<typeof useLabOrderItem>['data']> }) {
  const { can } = useAuth()
  const amend = useAmendResult()
  const [amendingId, setAmendingId] = useState<number | null>(null)
  const [newValue, setNewValue] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(id: number) {
    setError(null)
    try {
      await amend.mutateAsync({ id, reason: reason.trim(), value_numeric: newValue })
      setAmendingId(null)
      setNewValue('')
      setReason('')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not amend the result.')
    }
  }

  return (
    <Panel>
      <PanelHeader title="Results" hint="Amended values keep the superseded one on the record" />
      {error && <div className="p-5 pb-0"><ErrorNotice>{error}</ErrorNotice></div>}
      <TableFrame minWidth={760}>
        <thead>
          <tr>
            <Th>Measurement</Th>
            <Th className="text-right">Result</Th>
            <Th>Flag</Th>
            <Th>Reference</Th>
            {can('laboratory.amend_labresult') && <Th className="text-right">Amend</Th>}
          </tr>
        </thead>
        <tbody>
          {item.results.map((result) => (
            <tr key={result.id}>
              <Td>{result.parameter_name}</Td>
              <Td
                className={`text-right font-semibold ${
                  result.is_critical ? 'text-critical' : result.is_abnormal ? 'text-abnormal' : ''
                }`}
              >
                {result.display_value} {result.unit}
                {result.version > 1 && (
                  <span className="ml-1.5 text-[10.5px] font-normal text-abnormal">
                    v{result.version}
                  </span>
                )}
              </Td>
              <Td>
                <ClinicalFlag flag={result.flag} label={result.flag_label} />
              </Td>
              <Td className="text-ink-muted">{result.reference_text || '—'}</Td>
              {can('laboratory.amend_labresult') && (
                <Td className="text-right">
                  {amendingId === result.id ? (
                    <div className="grid gap-2 text-left">
                      <Input
                        value={newValue}
                        onChange={(event) => setNewValue(event.target.value)}
                        placeholder="Corrected value"
                        className="text-right"
                        autoFocus
                      />
                      <Input
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="Reason (required)"
                      />
                      <div className="flex gap-1.5">
                        <Button
                          variant="danger"
                          disabled={!reason.trim() || !newValue.trim() || amend.isPending}
                          onClick={() => submit(result.id)}
                        >
                          Save
                        </Button>
                        <Button variant="ghost" onClick={() => setAmendingId(null)}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setAmendingId(result.id)
                        setNewValue(result.display_value)
                      }}
                    >
                      Amend
                    </Button>
                  )}
                </Td>
              )}
            </tr>
          ))}
        </tbody>
      </TableFrame>

      {item.superseded_results.length > 0 && (
        <div className="border-t border-border bg-abnormal-muted/40 px-5 py-3">
          <p className="text-[10.5px] font-bold tracking-[0.09em] text-abnormal uppercase">
            Superseded
          </p>
          {item.superseded_results.map((result) => (
            <p key={result.id} className="mt-1 text-[12px] text-ink-muted">
              <span className="line-through">
                {result.parameter_name} {result.display_value} {result.unit}
              </span>
              {result.amendment_reason && ` — ${result.amendment_reason}`}
              <span className="ml-1.5 text-ink-faint">
                ({result.entered_by_email}, {dateAndTime(result.entered_at)})
              </span>
            </p>
          ))}
        </div>
      )}
    </Panel>
  )
}
