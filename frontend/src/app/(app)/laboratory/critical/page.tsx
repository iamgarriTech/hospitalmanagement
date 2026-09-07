'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Button, EmptyState, Field, Panel, PanelHeader, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useAcknowledgeCritical } from '@/lib/laboratory'
import { useCriticalResults } from '@/lib/queries'
import { dateAndTime } from '@/lib/workflow'

/**
 * Critical results awaiting acknowledgement.
 *
 * This list must not be allowed to grow quietly — a critical value nobody acted
 * on is the classic laboratory harm. Acknowledging requires saying what was
 * done, not just ticking a box, because "acknowledged" without an action is not
 * evidence that anything happened.
 *
 * Rows are oldest first: the one that has been waiting longest is the dangerous
 * one.
 */
export default function CriticalResultsPage() {
  const { can } = useAuth()
  const criticals = useCriticalResults()
  const acknowledge = useAcknowledgeCritical()
  const [openId, setOpenId] = useState<number | null>(null)
  const [action, setAction] = useState('')
  const [error, setError] = useState<string | null>(null)

  const rows = criticals.data ?? []
  const canAcknowledge = can('laboratory.acknowledge_critical_result')

  async function submit(id: number) {
    setError(null)
    try {
      await acknowledge.mutateAsync({ id, action_taken: action.trim() })
      setOpenId(null)
      setAction('')
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not record the acknowledgement.',
      )
    }
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-critical uppercase">
        Critical results
      </div>
      <PageHeading
        title={
          rows.length === 0
            ? 'No critical results outstanding'
            : `${rows.length} critical result${rows.length === 1 ? '' : 's'} awaiting acknowledgement`
        }
        subtitle="Raised when the value is entered, before verification. Someone has to act and say what they did."
        action={
          <div className="flex gap-2">
            <Link
              href="/laboratory"
              className="inline-flex items-center rounded-lg border border-border px-3 py-2 text-[13px] font-medium text-ink hover:bg-surface-muted"
            >
              Worklist
            </Link>
            <Button variant="secondary" onClick={() => criticals.refetch()} disabled={criticals.isFetching}>
              {criticals.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <Panel className={`mt-6 ${rows.length > 0 ? 'border-critical/40' : ''}`}>
        <PanelHeader
          title="Outstanding"
          hint={rows.length > 0 ? 'Oldest first — the longest wait is the dangerous one' : undefined}
        />
        {criticals.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
            Loading…
          </p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>
              Nothing outstanding. Critical values appear here the moment they are entered.
            </EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={940}>
            <thead>
              <tr>
                <Th>Patient</Th>
                <Th>Test</Th>
                <Th>Measurement</Th>
                <Th className="text-right">Value</Th>
                <Th>Reference</Th>
                <Th>Entered</Th>
                <Th>Requested by</Th>
                {canAcknowledge && <Th className="text-right">Acknowledge</Th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.result_id} className="bg-critical-muted/30">
                  <Td>
                    <span className="font-semibold text-ink">{row.patient_name}</span>
                    <div className="text-[11px] text-ink-faint">{row.hospital_number}</div>
                  </Td>
                  <Td className="text-[12px]">{row.test}</Td>
                  <Td className="text-[12px]">{row.parameter}</Td>
                  <Td className="text-right">
                    <span className="font-bold text-critical">{row.value}</span>
                    <div className="mt-0.5 inline-flex items-center gap-1 text-[10.5px] font-bold text-critical">
                      <AlertIcon className="size-3" />
                      {row.flag_label}
                    </div>
                  </Td>
                  <Td className="text-ink-muted">{row.reference || '—'}</Td>
                  <Td className="text-[11.5px] text-ink-muted">{dateAndTime(row.entered_at)}</Td>
                  <Td className="text-[11.5px] text-ink-muted">{row.ordered_by}</Td>
                  {canAcknowledge && (
                    <Td className="text-right align-top">
                      {openId === row.result_id ? (
                        <div className="grid w-64 gap-2 text-left">
                          <Field label="What was done?" required>
                            <Textarea
                              value={action}
                              onChange={(event) => setAction(event.target.value)}
                              autoFocus
                              className="min-h-16"
                              placeholder="Patient reviewed, two units cross-matched, admitted"
                            />
                          </Field>
                          <div className="flex gap-1.5">
                            <Button
                              disabled={!action.trim() || acknowledge.isPending}
                              onClick={() => submit(row.result_id)}
                            >
                              {acknowledge.isPending ? 'Saving…' : 'Acknowledge'}
                            </Button>
                            <Button variant="ghost" onClick={() => setOpenId(null)}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <Button
                          variant="danger"
                          onClick={() => {
                            setOpenId(row.result_id)
                            setAction('')
                          }}
                        >
                          Acknowledge
                        </Button>
                      )}
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      {!canAcknowledge && rows.length > 0 && (
        <p className="mt-4 text-[12.5px] text-ink-muted">
          You can see these but do not hold the permission to acknowledge them. The requesting
          clinician has been notified.
        </p>
      )}
    </PageShell>
  )
}
