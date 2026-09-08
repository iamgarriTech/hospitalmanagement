'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Button, EmptyState, Field, Panel, PanelHeader, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type CriticalFindingRow, useAcknowledgeFinding, useCriticalFindings } from '@/lib/imaging'
import { dateAndTime, waitedFor } from '@/lib/workflow'

/**
 * Critical findings nobody has answered for.
 *
 * A critical finding nobody acted on is the classic radiology harm, so the
 * acknowledgement is a record in its own right — who was told, when, and what
 * they did — rather than a flag somebody clears. The same requirement the
 * laboratory has for a critical result, for the same reason.
 *
 * Rows stay here until an action is recorded. There is no way to dismiss one.
 */
export default function CriticalFindingsPage() {
  const findings = useCriticalFindings()
  const rows = findings.data ?? []

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Radiology
      </div>
      <PageHeading
        title="Critical findings"
        subtitle="Verified reports with a finding that has to be acted on now."
        action={
          <Link
            href="/imaging"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Worklist
          </Link>
        }
      />

      {findings.isError && <ErrorNotice>Could not load the list.</ErrorNotice>}
      {findings.isLoading && <LoadingNotice>Loading…</LoadingNotice>}

      {!findings.isLoading && rows.length === 0 && (
        <Panel>
          <div className="p-8 text-center">
            <p className="text-[14px] font-semibold text-normal">
              Nothing outstanding.
            </p>
            <p className="mt-1.5 text-[12.5px] text-ink-muted">
              Every critical finding has an action recorded against it.
            </p>
          </div>
        </Panel>
      )}

      {rows.length > 0 && (
        <>
          <p
            role="alert"
            className="mb-5 flex items-start gap-2 rounded-lg border border-critical/40 bg-critical-muted px-4 py-3 text-[12.5px] font-medium text-critical"
          >
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>
              {rows.length} finding{rows.length === 1 ? '' : 's'} with nobody recorded as
              having acted. These stay here until an action is written down.
            </span>
          </p>
          <ul className="space-y-4">
            {rows.map((row) => (
              <li key={row.report}>
                <FindingCard row={row} />
              </li>
            ))}
          </ul>
        </>
      )}
    </PageShell>
  )
}

function FindingCard({ row }: { row: CriticalFindingRow }) {
  const { can } = useAuth()
  const acknowledge = useAcknowledgeFinding()
  const [action, setAction] = useState('')

  const fieldErrors = acknowledge.error instanceof ApiError ? acknowledge.error.fields : {}
  const minutes = Math.floor(
    (Date.now() - new Date(row.verified_at).getTime()) / 60000,
  )

  return (
    <Panel className="border-critical/40">
      <PanelHeader
        title={row.patient}
        hint={
          <>
            {row.hospital_number} · {row.procedure} · reported by {row.reported_by} ·
            released {dateAndTime(row.verified_at)}
          </>
        }
        action={
          <span className="rounded-md bg-critical-muted px-2.5 py-1 text-[11.5px] font-bold text-critical">
            {waitedFor(Math.max(minutes, 0))} unanswered
          </span>
        }
      />
      <div className="space-y-4 p-5">
        <p className="rounded-lg bg-critical-muted px-4 py-3 text-[13.5px] font-bold text-critical">
          <span aria-hidden>▲ </span>
          {row.finding}
        </p>
        <p className="text-[12.5px] leading-relaxed text-ink">{row.conclusion}</p>
        <p className="text-[11.5px] text-ink-muted">
          Requested by {row.requesting_clinician}.
        </p>

        {can('imaging.acknowledge_critical_finding') ? (
          <div className="space-y-2 border-t border-border pt-4">
            {acknowledge.error instanceof ApiError &&
              Object.keys(fieldErrors).length === 0 && (
                <ErrorNotice>{acknowledge.error.message}</ErrorNotice>
              )}
            <Field
              label="What was done about it?"
              hint="Required. An acknowledgement with no action is a tick box, not a record."
              error={fieldErrors.action_taken}
              required
            >
              <Textarea
                value={action}
                onChange={(event) => setAction(event.target.value)}
                placeholder="Needle decompression at the bedside, chest drain sited, repeat film requested."
              />
            </Field>
            <Button
              disabled={!action.trim() || acknowledge.isPending}
              onClick={() =>
                acknowledge.mutate({ id: row.report, action_taken: action.trim() })
              }
            >
              {acknowledge.isPending ? 'Recording…' : 'Record the action'}
            </Button>
          </div>
        ) : (
          <p className="border-t border-border pt-4 text-[12.5px] text-ink-muted">
            Acknowledging means &ldquo;I have acted on this&rdquo;, so it needs
            someone who can. Tell {row.requesting_clinician}.
          </p>
        )}
      </div>
    </Panel>
  )
}
