'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertIcon } from '@/components/icons'
import { LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Badge, Panel, PanelHeader, StatTile } from '@/components/ui'
import { request } from '@/lib/api'

type Entry = {
  area: string
  check: string
  active: boolean
  reviewed: boolean
  detail: string
}

type Limitations = {
  clinical_content_reviewed: boolean
  clinical_content_reviewer: string
  entries: Entry[]
  summary: { not_running: number; running_unreviewed: number; running_reviewed: number }
}

/**
 * What this software does not check.
 *
 * One page, because the promise — that nobody infers a check which is not
 * running — holds only if the whole picture is in one place. Scattered across
 * a dozen screens it holds on the ones somebody remembered.
 *
 * The two categories are ordered deliberately. "Runs, but nobody qualified
 * has signed off the numbers" comes first, because it is the more dangerous
 * of the two: something happens, so it looks handled.
 */
export default function LimitationsPage() {
  const data = useQuery({
    queryKey: ['limitations'],
    queryFn: () => request<Limitations>('/limitations/'),
    staleTime: 5 * 60_000,
  })

  if (data.isPending) return <PageShell><LoadingNotice /></PageShell>
  const report = data.data
  if (!report) return <PageShell><LoadingNotice /></PageShell>

  const unreviewed = report.entries.filter((e) => e.active && !e.reviewed)
  const absent = report.entries.filter((e) => !e.active)
  const running = report.entries.filter((e) => e.active && e.reviewed)

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Safety
      </div>
      <PageHeading
        title="What this software does not check"
        subtitle="Read this before relying on anything here. A check you assume is running and is not is more dangerous than one you know is absent."
      />

      {!report.clinical_content_reviewed && (
        <div className="mt-4 rounded-lg border border-critical/40 bg-critical/5 px-4 py-3">
          <p className="flex items-start gap-2 text-[13px] leading-relaxed text-critical">
            <AlertIcon className="mt-0.5 size-4 shrink-0" />
            <span>
              <span className="font-semibold">No clinician has signed off the
              clinical content of this deployment.</span>{' '}
              Medication round times, overdue windows, escalation thresholds, triage
              targets and consent wording are defaults chosen by the people who built
              the software. Treat every figure below as unverified until a named
              clinician has reviewed it.
            </span>
          </p>
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile
          label="Runs, but unreviewed"
          value={report.summary.running_unreviewed}
          tone={report.summary.running_unreviewed ? 'critical' : 'normal'}
          hint="Something happens, so it looks handled."
        />
        <StatTile
          label="Not running at all"
          value={report.summary.not_running}
          tone="abnormal"
        />
        <StatTile
          label="Runs and reviewed"
          value={report.summary.running_reviewed}
          tone="normal"
        />
      </div>

      {unreviewed.length > 0 && (
        <Panel className="mt-6">
          <PanelHeader
            title="Runs, but nobody qualified has signed off the numbers"
            hint="The more dangerous kind: something happens, so it looks checked."
            action={<Badge tone="critical">{unreviewed.length}</Badge>}
          />
          <ul className="grid gap-3 p-5">
            {unreviewed.map((entry) => (
              <li key={`${entry.area}-${entry.check}`}>
                <p className="text-[13px] font-semibold text-ink">
                  {entry.check}{' '}
                  <span className="font-normal text-ink-muted">· {entry.area}</span>
                </p>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">
                  {entry.detail}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel className="mt-5">
        <PanelHeader
          title="Not running"
          hint="Absent, unlicensed, or needing a configuration this deployment does not have."
          action={<Badge tone="abnormal">{absent.length}</Badge>}
        />
        <ul className="grid gap-3 p-5">
          {absent.map((entry) => (
            <li key={`${entry.area}-${entry.check}`}>
              <p className="text-[13px] font-semibold text-ink">
                {entry.check}{' '}
                <span className="font-normal text-ink-muted">· {entry.area}</span>
              </p>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">
                {entry.detail}
              </p>
            </li>
          ))}
        </ul>
      </Panel>

      {running.length > 0 && (
        <Panel className="mt-5">
          <PanelHeader title="Running, and reviewed" />
          <ul className="grid gap-3 p-5">
            {running.map((entry) => (
              <li key={`${entry.area}-${entry.check}`}>
                <p className="text-[13px] font-semibold text-ink">
                  {entry.check}{' '}
                  <span className="font-normal text-ink-muted">· {entry.area}</span>
                </p>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">
                  {entry.detail}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </PageShell>
  )
}
