'use client'

import { useMemo, useState } from 'react'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import { Badge, EmptyState, Field, Panel, PanelHeader, Select } from '@/components/ui'
import { useFacilities } from '@/lib/config'
import { exportUrl, useReport, useReportCatalogue } from '@/lib/reports'
import { dateAndTime, money } from '@/lib/workflow'

/**
 * Reports.
 *
 * The only screen in the system driven by a generic shape, and legitimately
 * so: a report *is* columns and rows, and hand-designing seventeen of them
 * would produce seventeen slightly different tables with no gain.
 *
 * Two things are deliberately always on screen. The **filters that produced
 * these rows**, because two people comparing printouts need to be able to see
 * why they differ. And the **facility scope**, because a figure is meaningless
 * without knowing whose it is — and a user who can see one branch must never
 * mistake their number for the group's.
 */
export default function ReportsPage() {
  const catalogue = useReportCatalogue()
  const facilities = useFacilities()

  const [selected, setSelected] = useState<string | null>(null)
  const [filters, setFilters] = useState(() => {
    const today = new Date()
    const first = new Date(today.getFullYear(), today.getMonth(), 1)
    return {
      from: first.toISOString().slice(0, 10),
      to: today.toISOString().slice(0, 10),
      facility: '',
    }
  })

  const report = useReport(selected, filters)

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof catalogue.data>()
    for (const entry of catalogue.data ?? []) {
      const list = groups.get(entry.group) ?? []
      list.push(entry)
      groups.set(entry.group, list as typeof catalogue.data)
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [catalogue.data])

  const current = (catalogue.data ?? []).find((entry) => entry.key === selected)

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Reports
      </div>
      <PageHeading
        title="Reports"
        subtitle="Every figure is a live query against the records, and scoped to the facilities you may see."
      />

      {catalogue.isError && (
        <div className="mt-4"><ErrorNotice>Reports could not be loaded.</ErrorNotice></div>
      )}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[280px_1fr]">
        <Panel>
          <PanelHeader title="Available to you" hint="Only what your roles permit." />
          {catalogue.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : (catalogue.data ?? []).length === 0 ? (
            <div className="p-5">
              <EmptyState>
                Your roles do not include any reports.
              </EmptyState>
            </div>
          ) : (
            <div className="grid gap-4 p-4">
              {grouped.map(([group, entries]) => (
                <div key={group}>
                  <p className="mb-1.5 px-1 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
                    {group}
                  </p>
                  <div className="grid gap-0.5">
                    {(entries ?? []).map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        onClick={() => setSelected(entry.key)}
                        className={`rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition ${
                          selected === entry.key
                            ? 'bg-accent/10 font-medium text-accent'
                            : 'text-ink-muted hover:bg-surface-sunken hover:text-ink'
                        }`}
                      >
                        {entry.title}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <div className="grid gap-5">
          {current === undefined ? (
            <Panel>
              <div className="p-8">
                <EmptyState>Choose a report on the left.</EmptyState>
              </div>
            </Panel>
          ) : (
            <>
              <Panel>
                <PanelHeader
                  title={current.title}
                  hint={current.description}
                  action={
                    current.is_snapshot ? (
                      <Badge tone="idle">as at now</Badge>
                    ) : (
                      <Badge tone="idle">date range</Badge>
                    )
                  }
                />
                <div className="grid gap-4 p-5 sm:grid-cols-3">
                  {!current.is_snapshot && (
                    <>
                      <Field label="From">
                        <input
                          type="date"
                          value={filters.from}
                          onChange={(e) =>
                            setFilters({ ...filters, from: e.target.value })
                          }
                          className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-[13px] text-ink"
                        />
                      </Field>
                      <Field label="To">
                        <input
                          type="date"
                          value={filters.to}
                          onChange={(e) =>
                            setFilters({ ...filters, to: e.target.value })
                          }
                          className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-[13px] text-ink"
                        />
                      </Field>
                    </>
                  )}
                  <Field label="Facility">
                    <Select
                      value={filters.facility}
                      onChange={(e) =>
                        setFilters({ ...filters, facility: e.target.value })
                      }
                    >
                      <option value="">Everything you may see</option>
                      {(facilities.data ?? []).map((facility) => (
                        <option key={facility.id} value={facility.id}>
                          {facility.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
                {current.notes && (
                  <p className="border-t border-border px-5 py-3 text-[12.5px] leading-relaxed text-ink-muted">
                    {current.notes}
                  </p>
                )}
              </Panel>

              <Panel>
                <PanelHeader
                  title="Results"
                  hint={
                    report.data
                      ? `${report.data.row_count} row${report.data.row_count === 1 ? '' : 's'}`
                      : undefined
                  }
                  action={
                    report.data && report.data.row_count > 0 ? (
                      <a
                        href={exportUrl(current.key, filters)}
                        className="rounded-md border border-border px-3 py-1.5 text-[12.5px] font-medium text-ink transition hover:border-accent hover:text-accent"
                      >
                        Export CSV
                      </a>
                    ) : null
                  }
                />

                {report.data && (
                  <dl className="grid gap-x-6 gap-y-1 border-b border-border bg-surface-sunken/40 px-5 py-3 text-[12px] sm:grid-cols-2">
                    <div className="flex gap-2">
                      <dt className="text-ink-muted">Run</dt>
                      <dd className="text-ink">{dateAndTime(report.data.run_at)}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="text-ink-muted">By</dt>
                      <dd className="text-ink">{report.data.run_by}</dd>
                    </div>
                    {!report.data.is_snapshot && (
                      <div className="flex gap-2">
                        <dt className="text-ink-muted">Period</dt>
                        <dd className="text-ink">
                          {report.data.filters.date_from} to{' '}
                          {report.data.filters.date_to}
                        </dd>
                      </div>
                    )}
                    <div className="flex gap-2">
                      <dt className="text-ink-muted">Covering</dt>
                      <dd className="text-ink">
                        {report.data.filters.facility_scope}
                      </dd>
                    </div>
                  </dl>
                )}

                {report.isPending ? (
                  <div className="p-5"><LoadingNotice /></div>
                ) : report.isError ? (
                  <div className="p-5">
                    <ErrorNotice>That report could not be run.</ErrorNotice>
                  </div>
                ) : (report.data?.rows ?? []).length === 0 ? (
                  <div className="p-8">
                    <EmptyState>
                      Nothing in that period, for the facilities you can see.
                    </EmptyState>
                  </div>
                ) : (
                  <TableFrame minWidth={640}>
                    <thead>
                      <tr>
                        {report.data!.columns.map((column) => (
                          <Th
                            key={column.key}
                            className={column.numeric ? 'text-right' : ''}
                          >
                            {column.label}
                          </Th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {report.data!.rows.map((row, index) => (
                        <tr key={index}>
                          {report.data!.columns.map((column) => {
                            const value = row[column.key]
                            return (
                              <Td
                                key={column.key}
                                className={column.numeric ? 'text-right tabular-nums' : ''}
                              >
                                {value === null || value === undefined || value === '' ? (
                                  <span className="text-ink-faint">—</span>
                                ) : column.money ? (
                                  money(value as string)
                                ) : (
                                  String(value)
                                )}
                              </Td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </TableFrame>
                )}
              </Panel>
            </>
          )}
        </div>
      </div>
    </PageShell>
  )
}
