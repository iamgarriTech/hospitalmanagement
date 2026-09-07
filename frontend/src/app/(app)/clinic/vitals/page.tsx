'use client'

import { useSearchParams } from 'next/navigation'
import { useMemo, useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { PatientHeader } from '@/components/PatientHeader'
import { AlertIcon } from '@/components/icons'
import { Badge, Button, EmptyState, Field, Input, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useRecordVitals, useVitals } from '@/lib/clinical'
import { type QueueRow, usePatient, useQueue } from '@/lib/queries'
import { dateAndTime, queueLabel, queueTone, waitedFor } from '@/lib/workflow'

/**
 * Vitals at triage.
 *
 * Two panes on purpose: the queue stays on screen while observations are typed,
 * because a nurse works through a list of people rather than opening one record
 * at a time.
 *
 * BMI is shown but never typed — it is derived from height and weight, and the
 * server refuses it as an input. Out-of-range values are refused rather than
 * warned about: a slipped decimal point in a temperature is a clinical safety
 * problem, not a formatting preference.
 */

type FormState = {
  temperature_c: string
  systolic_bp: string
  diastolic_bp: string
  pulse_bpm: string
  respiratory_rate: string
  oxygen_saturation: string
  weight_kg: string
  height_cm: string
  blood_glucose_mmol: string
  pain_score: string
}

const EMPTY: FormState = {
  temperature_c: '', systolic_bp: '', diastolic_bp: '', pulse_bpm: '',
  respiratory_rate: '', oxygen_saturation: '', weight_kg: '', height_cm: '',
  blood_glucose_mmol: '', pain_score: '',
}

/** Plausible ranges, matching the server's. Flagged here so the person typing
 *  finds out immediately rather than after a round trip. */
const BOUNDS: Record<keyof FormState, [number, number, string]> = {
  temperature_c: [25, 45, '°C'],
  systolic_bp: [40, 300, 'mmHg'],
  diastolic_bp: [20, 200, 'mmHg'],
  pulse_bpm: [20, 250, 'bpm'],
  respiratory_rate: [4, 80, '/min'],
  oxygen_saturation: [40, 100, '%'],
  weight_kg: [0.3, 400, 'kg'],
  height_cm: [20, 260, 'cm'],
  blood_glucose_mmol: [0.5, 50, 'mmol/L'],
  pain_score: [0, 10, '/10'],
}

export default function VitalsPage() {
  const search = useSearchParams()
  const { facility, can } = useAuth()
  const queue = useQueue({ status: 'waiting,called,in_consultation' })
  const record = useRecordVitals()

  const [selectedId, setSelectedId] = useState<number | null>(
    search.get('visit') ? Number(search.get('visit')) : null,
  )
  const [form, setForm] = useState<FormState>(EMPTY)
  const [fields, setFields] = useState<Record<string, string[]>>({})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const rows = queue.data ?? []
  const selected = rows.find((row) => row.id === selectedId) ?? null
  const patient = usePatient(selected?.patient.id ?? null)
  const history = useVitals({ patient: selected?.patient.id, enabled: Boolean(selected) })

  const bmi = useMemo(() => {
    const weight = Number(form.weight_kg)
    const height = Number(form.height_cm)
    if (!weight || !height) return null
    const metres = height / 100
    return Math.round((weight / (metres * metres)) * 10) / 10
  }, [form.weight_kg, form.height_cm])

  const localErrors = useMemo(() => {
    const problems: Record<string, string[]> = {}
    for (const [key, value] of Object.entries(form) as [keyof FormState, string][]) {
      if (!value) continue
      const numeric = Number(value)
      const [low, high, unit] = BOUNDS[key]
      if (!Number.isFinite(numeric)) problems[key] = ['Enter a number.']
      else if (numeric < low || numeric > high) {
        problems[key] = [`Expected between ${low} and ${high} ${unit}. Check the value.`]
      }
    }
    const systolic = Number(form.systolic_bp)
    const diastolic = Number(form.diastolic_bp)
    if (systolic && diastolic && systolic <= diastolic) {
      problems.systolic_bp = ['Systolic must be higher than diastolic.']
    }
    return problems
  }, [form])

  const hasLocalErrors = Object.keys(localErrors).length > 0
  const hasAnyValue = Object.values(form).some((value) => value !== '')

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: value }))
    setSaved(null)
  }

  function choose(row: QueueRow) {
    setSelectedId(row.id)
    setForm(EMPTY)
    setFields({})
    setError(null)
    setSaved(null)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!selected || !facility) return
    setError(null)
    setFields({})

    const numeric = (value: string) => (value === '' ? undefined : Number(value))
    try {
      await record.mutateAsync({
        patient: selected.patient.id,
        visit: selected.id,
        facility: facility.id,
        temperature_c: form.temperature_c || undefined,
        systolic_bp: numeric(form.systolic_bp),
        diastolic_bp: numeric(form.diastolic_bp),
        pulse_bpm: numeric(form.pulse_bpm),
        respiratory_rate: numeric(form.respiratory_rate),
        oxygen_saturation: numeric(form.oxygen_saturation),
        weight_kg: form.weight_kg || undefined,
        height_cm: form.height_cm || undefined,
        blood_glucose_mmol: form.blood_glucose_mmol || undefined,
        pain_score: numeric(form.pain_score),
      })
      setForm(EMPTY)
      setSaved(`Observations recorded for ${selected.patient.full_name}.`)
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFields(caught.fields)
        setError(caught.message)
      } else {
        setError('Could not reach the hospital server. Nothing was recorded.')
      }
    }
  }

  if (!can('clinical.add_vitalsigns')) {
    return (
      <PageShell>
        <Panel className="p-5">
          <p className="text-[13px] text-ink-muted">
            You do not hold the permission to record observations.
          </p>
        </Panel>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Triage
      </div>
      <PageHeading
        title="Record vital signs"
        subtitle="Pick a patient from the queue, then record their observations."
        action={
          <Button variant="secondary" onClick={() => queue.refetch()} disabled={queue.isFetching}>
            {queue.isFetching ? 'Refreshing…' : 'Refresh queue'}
          </Button>
        }
      />

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[360px_1fr]">
        <Panel>
          <PanelHeader title="Queue" hint={`${rows.length} waiting or in clinic`} />
          {queue.isLoading ? (
            <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
              Loading…
            </p>
          ) : rows.length === 0 ? (
            <div className="p-5">
              <EmptyState>Nobody is waiting.</EmptyState>
            </div>
          ) : (
            <ul className="max-h-[560px] divide-y divide-border overflow-y-auto">
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    onClick={() => choose(row)}
                    aria-current={row.id === selectedId}
                    className={`block w-full px-5 py-3 text-left transition-colors ${
                      row.id === selectedId ? 'bg-accent-muted' : 'hover:bg-surface-muted'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-semibold text-ink">
                        {row.patient.full_name}
                      </span>
                      <Badge tone={queueTone(row.status)}>{queueLabel(row.status)}</Badge>
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-faint">
                      {row.patient.hospital_number}
                      {row.patient.age_years !== null && ` · ${row.patient.age_years}y`}
                      {` · ${row.patient.sex} · waited ${waitedFor(row.waiting_minutes)}`}
                    </span>
                    {row.allergies.length > 0 && (
                      <span className="mt-1 inline-flex items-center gap-1 text-[10.5px] font-bold text-critical">
                        <AlertIcon className="size-3" />
                        {row.allergies.join(', ')}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid gap-5">
          {!selected ? (
            <Panel className="p-5">
              <EmptyState>Select a patient from the queue to record observations.</EmptyState>
            </Panel>
          ) : (
            <>
              {patient.data && <PatientHeader patient={patient.data} />}

              <form onSubmit={submit}>
                <Panel>
                  <PanelHeader
                    title="Observations"
                    hint="Leave anything not measured blank. Nothing here is mandatory."
                  />
                  <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
                    <Measurement
                      label="Temperature" unit="°C" step="0.1" value={form.temperature_c}
                      onChange={(value) => set('temperature_c', value)}
                      error={localErrors.temperature_c ?? fields.temperature_c}
                    />
                    <Measurement
                      label="Systolic BP" unit="mmHg" value={form.systolic_bp}
                      onChange={(value) => set('systolic_bp', value)}
                      error={localErrors.systolic_bp ?? fields.systolic_bp}
                    />
                    <Measurement
                      label="Diastolic BP" unit="mmHg" value={form.diastolic_bp}
                      onChange={(value) => set('diastolic_bp', value)}
                      error={localErrors.diastolic_bp ?? fields.diastolic_bp}
                    />
                    <Measurement
                      label="Pulse" unit="bpm" value={form.pulse_bpm}
                      onChange={(value) => set('pulse_bpm', value)}
                      error={localErrors.pulse_bpm ?? fields.pulse_bpm}
                    />
                    <Measurement
                      label="Respiratory rate" unit="/min" value={form.respiratory_rate}
                      onChange={(value) => set('respiratory_rate', value)}
                      error={localErrors.respiratory_rate ?? fields.respiratory_rate}
                    />
                    <Measurement
                      label="Oxygen saturation" unit="%" value={form.oxygen_saturation}
                      onChange={(value) => set('oxygen_saturation', value)}
                      error={localErrors.oxygen_saturation ?? fields.oxygen_saturation}
                    />
                    <Measurement
                      label="Weight" unit="kg" step="0.01" value={form.weight_kg}
                      onChange={(value) => set('weight_kg', value)}
                      error={localErrors.weight_kg ?? fields.weight_kg}
                    />
                    <Measurement
                      label="Height" unit="cm" step="0.1" value={form.height_cm}
                      onChange={(value) => set('height_cm', value)}
                      error={localErrors.height_cm ?? fields.height_cm}
                    />
                    {/* Derived, not entered. The server rejects a supplied BMI. */}
                    <Field label="BMI" hint="Calculated from height and weight">
                      <div className="flex h-[38px] items-center rounded-md border border-border bg-surface-muted px-2.5 text-[13px] font-semibold text-ink">
                        {bmi ?? <span className="font-normal text-ink-faint">—</span>}
                      </div>
                    </Field>
                    <Measurement
                      label="Blood glucose" unit="mmol/L" step="0.1"
                      value={form.blood_glucose_mmol}
                      onChange={(value) => set('blood_glucose_mmol', value)}
                      error={localErrors.blood_glucose_mmol ?? fields.blood_glucose_mmol}
                    />
                    <Measurement
                      label="Pain score" unit="/10" value={form.pain_score}
                      onChange={(value) => set('pain_score', value)}
                      error={localErrors.pain_score ?? fields.pain_score}
                    />
                  </div>

                  <div className="border-t border-border px-5 py-4">
                    {error && <ErrorNotice>{error}</ErrorNotice>}
                    {saved && (
                      <p
                        role="status"
                        className="mb-3 rounded-md border border-normal/30 bg-normal-muted px-3 py-2 text-[12.5px] font-medium text-normal"
                      >
                        {saved}
                      </p>
                    )}
                    {hasLocalErrors && (
                      <p className="mb-3 text-[12px] font-medium text-critical">
                        Check the highlighted values before saving.
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="submit"
                        disabled={record.isPending || hasLocalErrors || !hasAnyValue}
                        className="px-4 py-2.5"
                      >
                        {record.isPending ? 'Recording…' : 'Record observations'}
                      </Button>
                      <Button variant="secondary" onClick={() => setForm(EMPTY)} disabled={!hasAnyValue}>
                        Clear
                      </Button>
                    </div>
                  </div>
                </Panel>
              </form>

              <Panel>
                <PanelHeader title="Earlier observations for this patient" hint="Most recent first" />
                {(history.data?.results ?? []).length === 0 ? (
                  <div className="p-5">
                    <EmptyState>Nothing recorded yet.</EmptyState>
                  </div>
                ) : (
                  <TableFrame minWidth={760}>
                    <thead>
                      <tr>
                        <Th>When</Th>
                        <Th className="text-right">Temp</Th>
                        <Th className="text-right">BP</Th>
                        <Th className="text-right">Pulse</Th>
                        <Th className="text-right">SpO₂</Th>
                        <Th className="text-right">BMI</Th>
                        <Th>By</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.data!.results.map((entry) => (
                        <tr key={entry.id}>
                          <Td className="text-ink-muted">{dateAndTime(entry.recorded_at)}</Td>
                          <Td className="text-right">{entry.temperature_c ?? '—'}</Td>
                          <Td className="text-right">{entry.blood_pressure ?? '—'}</Td>
                          <Td className="text-right">{entry.pulse_bpm ?? '—'}</Td>
                          <Td className="text-right">{entry.oxygen_saturation ?? '—'}</Td>
                          <Td className="text-right">{entry.bmi ?? '—'}</Td>
                          <Td className="text-[11.5px] text-ink-faint">{entry.recorded_by_email}</Td>
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

function Measurement({
  label,
  unit,
  value,
  onChange,
  error,
  step = '1',
}: {
  label: string
  unit: string
  value: string
  onChange: (value: string) => void
  error?: string[]
  step?: string
}) {
  return (
    <Field label={label} error={error}>
      <div className="relative">
        <Input
          type="number"
          inputMode="decimal"
          step={step}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="pr-14 text-right"
        />
        <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-[11px] text-ink-faint">
          {unit}
        </span>
      </div>
    </Field>
  )
}
