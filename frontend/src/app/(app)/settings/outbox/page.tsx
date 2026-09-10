'use client'

import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import { Badge, Button, EmptyState, Panel, PanelHeader, StatTile } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useOutbox, useOutboxSummary, useRetryMessage } from '@/lib/notifications'
import { dateAndTime } from '@/lib/workflow'

/**
 * The outbound message queue.
 *
 * Two things a hospital needs to be able to see, and neither is visible
 * anywhere else: whether messages are getting out, and which ones gave up.
 *
 * A failed message stays here. It is never deleted, because "the patient was
 * told" and "we tried to tell the patient and could not" have to be different
 * answers when somebody asks later.
 *
 * The message body is deliberately absent from this screen. Chasing a stuck
 * queue does not require reading what a result notification said.
 */
export default function OutboxPage() {
  const { can } = useAuth()
  const summary = useOutboxSummary()
  const messages = useOutbox()
  const retry = useRetryMessage()
  const [error, setError] = useState<string | null>(null)

  const rows = messages.data ?? []
  const failed = rows.filter((row) => row.status === 'failed')

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That action could not be completed.',
      )
    }
  }

  const tone = (status: string) =>
    status === 'sent' ? 'normal'
      : status === 'failed' ? 'critical'
        : status === 'cancelled' ? 'idle' : 'progress'

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Outbound messages"
        subtitle="SMS and email leave through a queue, so a provider being down never affects a clinical or financial record."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 rounded-lg border border-abnormal/30 bg-abnormal-muted px-4 py-3">
        <p className="flex items-start gap-2 text-[12.5px] leading-relaxed text-abnormal">
          <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            <span className="font-semibold">No SMS or email provider is configured
            in this build.</span>{' '}
            Messages are written to the server log and marked sent with a note saying
            nothing actually left the building. Do not rely on a patient having been
            contacted until a real provider is connected.
          </span>
        </p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-4">
        <StatTile
          label="Waiting"
          value={summary.data?.pending ?? 0}
          tone={(summary.data?.pending ?? 0) > 0 ? 'progress' : 'normal'}
        />
        <StatTile label="Sent" value={summary.data?.sent ?? 0} tone="normal" />
        <StatTile
          label="Gave up"
          value={summary.data?.failed ?? 0}
          tone={(summary.data?.failed ?? 0) > 0 ? 'critical' : 'normal'}
        />
        <StatTile
          label="Oldest waiting"
          value={
            summary.data?.oldest_pending
              ? dateAndTime(summary.data.oldest_pending)
              : '—'
          }
          hint="A growing figure here means the worker has stopped."
        />
      </div>

      {failed.length > 0 && (
        <Panel className="mt-6">
          <PanelHeader
            title="Gave up"
            hint="Retrying resets the attempt count — do it once you have fixed the cause."
            action={<Badge tone="critical">{failed.length}</Badge>}
          />
          <TableFrame minWidth={680}>
            <thead>
              <tr>
                <Th>To</Th>
                <Th>What triggered it</Th>
                <Th>Why it failed</Th>
                <Th>Failed</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {failed.map((message) => (
                <tr key={message.id}>
                  <Td>
                    <span className="font-medium text-ink">{message.to_address}</span>
                    <div className="text-[11px] text-ink-faint">
                      {message.channel_display}
                      {message.patient_reference && ` · ${message.patient_reference}`}
                    </div>
                  </Td>
                  <Td className="text-ink-muted">
                    {message.source_type || <span className="text-ink-faint">—</span>}
                  </Td>
                  <Td className="max-w-[28ch] text-[12px] leading-relaxed text-critical">
                    {message.last_error}
                    <div className="text-[11px] text-ink-faint">
                      after {message.attempts} attempts
                    </div>
                  </Td>
                  <Td className="text-ink-muted">
                    {message.failed_at ? dateAndTime(message.failed_at) : '—'}
                  </Td>
                  <Td>
                    {can('notifications.retry_outbound_message') && (
                      <button
                        type="button"
                        disabled={retry.isPending}
                        onClick={() => run(() => retry.mutateAsync(message.id))}
                        className="text-[12px] font-medium text-accent hover:underline disabled:opacity-50"
                      >
                        Try again
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        </Panel>
      )}

      <Panel className="mt-5">
        <PanelHeader
          title="The queue"
          hint="Newest first. Refreshes every minute."
        />
        {messages.isPending ? (
          <div className="p-5"><LoadingNotice /></div>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>
              Nothing has been queued. Nothing in this build sends a message
              automatically yet.
            </EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={700}>
            <thead>
              <tr>
                <Th>To</Th>
                <Th>Channel</Th>
                <Th>Status</Th>
                <Th className="text-right">Attempts</Th>
                <Th>Next try</Th>
                <Th>Queued</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((message) => (
                <tr key={message.id}>
                  <Td>
                    <span className="font-medium text-ink">{message.to_address}</span>
                    {message.subject && (
                      <div className="text-[11px] text-ink-faint">
                        {message.subject}
                      </div>
                    )}
                  </Td>
                  <Td className="text-ink-muted">{message.channel_display}</Td>
                  <Td>
                    <Badge tone={tone(message.status)}>{message.status_display}</Badge>
                    {message.provider_reference && (
                      <div className="text-[11px] text-ink-faint">
                        {message.provider_reference}
                      </div>
                    )}
                  </Td>
                  <Td className="text-right tabular-nums text-ink-muted">
                    {message.attempts}/{message.max_attempts}
                  </Td>
                  <Td className="text-ink-muted">
                    {message.status === 'pending'
                      ? dateAndTime(message.next_attempt_at)
                      : '—'}
                  </Td>
                  <Td className="text-ink-muted">{dateAndTime(message.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}
