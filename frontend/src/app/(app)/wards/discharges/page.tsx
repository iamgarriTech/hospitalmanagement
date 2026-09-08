'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, EmptyState, Field, Panel, PanelHeader, Select } from '@/components/ui'
import { useAdmissions, useWards } from '@/lib/inpatient'
import { admissionLabel, admissionTone, dateAndTime, dayAndMonth } from '@/lib/workflow'

/**
 * The ward's discharge list.
 *
 * Two lists, deliberately: patients with a plan recorded, and everyone else
 * still in. The plan is what the pharmacy and the cash desk work towards, so
 * it is worth being able to see who has one — a discharge nobody saw coming is
 * a discharge with no medication ready and an unsettled bill.
 */
export default function DischargesPage() {
  const wards = useWards()
  const [wardId, setWardId] = useState<number | null>(null)

  const base: Record<string, string> = wardId ? { ward: String(wardId) } : {}
  const planned = useAdmissions({ ...base, discharge_planned: 'true' })
  const open = useAdmissions({ ...base, open: 'true' })

  const plannedRows = planned.data ?? []
  const stillIn = (open.data ?? []).filter((row) => row.status !== 'discharge_planned')

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Inpatient
      </div>
      <PageHeading
        title="Discharges"
        subtitle="Who is going home, and what has to happen before they can."
        action={
          <Link
            href="/wards"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Bed board
          </Link>
        }
      />

      <div className="mb-5 max-w-xs">
        <Field label="Ward">
          <Select
            value={wardId ?? ''}
            onChange={(event) =>
              setWardId(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">All wards</option>
            {wards.data?.map((ward) => (
              <option key={ward.id} value={ward.id}>
                {ward.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {(planned.isError || open.isError) && (
        <ErrorNotice>Could not load the discharge lists.</ErrorNotice>
      )}

      <div className="space-y-5">
        <Panel>
          <PanelHeader
            title="Discharge planned"
            hint="A plan has been recorded. The pharmacy and cash desk work to these."
            action={
              plannedRows.length > 0 ? (
                <Badge tone="progress">{plannedRows.length}</Badge>
              ) : undefined
            }
          />
          {planned.isLoading && (
            <div className="p-5">
              <LoadingNotice>Loading…</LoadingNotice>
            </div>
          )}
          {!planned.isLoading && plannedRows.length === 0 && (
            <div className="p-5">
              <EmptyState>
                Nobody has a discharge plan recorded. A ward doctor records one from the
                patient&apos;s chart.
              </EmptyState>
            </div>
          )}
          {plannedRows.length > 0 && (
            <TableFrame minWidth={860}>
              <thead>
                <tr>
                  <Th>Patient</Th>
                  <Th>Bed</Th>
                  <Th>Expected</Th>
                  <Th>Destination</Th>
                  <Th>What has to happen first</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {plannedRows.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <Link
                        href={`/wards/${row.id}`}
                        className="font-semibold text-ink hover:text-accent"
                      >
                        {row.patient_detail.full_name}
                      </Link>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.patient_detail.hospital_number} · {row.admission_number}
                      </span>
                    </Td>
                    <Td>
                      <span className="font-medium text-ink">
                        {row.bed?.label ?? '—'}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.bed?.ward_name ?? ''}
                      </span>
                    </Td>
                    <Td className="text-ink">
                      {row.expected_discharge_date
                        ? dayAndMonth(row.expected_discharge_date)
                        : 'Not set'}
                    </Td>
                    <Td className="text-ink-muted">{row.destination_display || '—'}</Td>
                    <Td className="max-w-72 text-[12px] text-ink-muted">
                      {row.discharge_plan_notes || '—'}
                    </Td>
                    <Td>
                      <Link
                        href={`/wards/${row.id}`}
                        className="text-[12px] font-semibold text-accent hover:underline"
                      >
                        Open
                      </Link>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="Still in, no plan yet"
            hint="Longest stay first — a stay nobody is planning to end is worth a look."
            action={
              stillIn.length > 0 ? <Badge tone="idle">{stillIn.length}</Badge> : undefined
            }
          />
          {stillIn.length === 0 ? (
            <div className="p-5">
              <EmptyState>Every inpatient has a discharge plan.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={760}>
              <thead>
                <tr>
                  <Th>Patient</Th>
                  <Th>Bed</Th>
                  <Th>Nights</Th>
                  <Th>Diagnosis</Th>
                  <Th>Admitted</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {[...stillIn]
                  .sort((a, b) => b.length_of_stay_nights - a.length_of_stay_nights)
                  .map((row) => (
                    <tr key={row.id} className="border-t border-border">
                      <Td>
                        <Link
                          href={`/wards/${row.id}`}
                          className="font-semibold text-ink hover:text-accent"
                        >
                          {row.patient_detail.full_name}
                        </Link>
                        <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                          {row.patient_detail.hospital_number}
                        </span>
                      </Td>
                      <Td className="text-ink">{row.bed?.label ?? '—'}</Td>
                      <Td>
                        <Badge
                          tone={row.length_of_stay_nights > 10 ? 'abnormal' : 'idle'}
                        >
                          {row.length_of_stay_nights}
                        </Badge>
                      </Td>
                      <Td className="max-w-64 text-[12px] text-ink-muted">
                        {row.admission_diagnosis}
                      </Td>
                      <Td className="text-[12px] text-ink-muted">
                        {dateAndTime(row.admitted_at)}
                      </Td>
                      <Td>
                        <Badge tone={admissionTone(row.status)}>
                          {admissionLabel(row.status)}
                        </Badge>
                      </Td>
                    </tr>
                  ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}
