'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { OrderTestsPanel } from '@/components/clinic/OrderTestsPanel'
import { PrescribePanel } from '@/components/clinic/PrescribePanel'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { PatientHeader } from '@/components/PatientHeader'
import {
  Badge, Button, ClinicalFlag, EmptyState, Field, Input, Panel, PanelHeader, Select, Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type DiagnosisInput, type Narrative, NARRATIVE_FIELDS, useAmendEncounter, useEncounter,
  useEncounterVersions, useFinaliseEncounter, useSaveDraft, useVitals,
} from '@/lib/clinical'
import { clearDraft, draftKey, readDraft, writeDraft } from '@/lib/draft'
import { useLabOrders, usePatient, usePrescriptions, useMoveVisit } from '@/lib/queries'
import { dateAndTime, labLabel, labTone, timeOfDay } from '@/lib/workflow'

/**
 * The consultation workspace.
 *
 * A draft is editable in place and autosaves; finalising locks it, and every
 * change after that is an amendment that appends a version and requires a
 * reason. That is the difference between a record and a notepad: correcting
 * today's entry must never quietly rewrite what was written before.
 *
 * Typed content is also stashed on this device on every keystroke, so a dropped
 * connection cannot cost a half-written note — the alternative is a clinician
 * rewriting it from memory, which is a worse record.
 */

const LABELS: Record<string, { label: string; hint?: string; rows?: number }> = {
  presenting_complaint: { label: 'Presenting complaint', rows: 2 },
  history_of_presenting_complaint: { label: 'History of presenting complaint', rows: 4 },
  past_medical_history: { label: 'Past medical history', rows: 2 },
  surgical_history: { label: 'Surgical history', rows: 2 },
  family_history: { label: 'Family history', rows: 2 },
  social_history: { label: 'Social history', rows: 2 },
  medication_history: { label: 'Medication history', rows: 2 },
  examination_findings: { label: 'Examination findings', rows: 4 },
  clinical_notes: { label: 'Clinical notes', rows: 4 },
  treatment_plan: { label: 'Treatment plan', rows: 3 },
  follow_up_plan: { label: 'Follow-up plan', rows: 2 },
}

const BLANK: Narrative = NARRATIVE_FIELDS.reduce(
  (all, field) => ({ ...all, [field]: '' }),
  {} as Narrative,
)

type SaveState = 'idle' | 'saving' | 'saved' | 'local-only'

export default function ConsultationPage() {
  const params = useParams<{ id: string }>()
  const encounterId = Number(params.id)
  const { can } = useAuth()

  const encounter = useEncounter(Number.isFinite(encounterId) ? encounterId : null)
  const saveDraft = useSaveDraft(encounterId)
  const finalise = useFinaliseEncounter(encounterId)
  const amend = useAmendEncounter(encounterId)
  const move = useMoveVisit()

  const record = encounter.data
  const patient = usePatient(record?.patient ?? null)
  const vitals = useVitals({ visit: record?.visit, enabled: Boolean(record) })
  const labs = useLabOrders({ visit: record?.visit, enabled: Boolean(record) && can('laboratory.view_laborder') })
  const prescriptions = usePrescriptions({ visit: record?.visit, enabled: Boolean(record) && can('pharmacy.view_prescription') })
  const versions = useEncounterVersions(encounterId, (record?.version_count ?? 1) > 1)

  const [narrative, setNarrative] = useState<Narrative>(BLANK)
  const [diagnoses, setDiagnoses] = useState<DiagnosisInput[]>([])
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [amendReason, setAmendReason] = useState('')
  const [amending, setAmending] = useState(false)
  const [restored, setRestored] = useState(false)
  const loadedFor = useRef<number | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isDraft = record?.status === 'draft'
  const key = draftKey(encounterId)

  /* Load the server copy once, then prefer a newer local stash if one exists —
     that is the note someone typed and lost the connection on. */
  useEffect(() => {
    if (!record?.current || loadedFor.current === record.id) return
    loadedFor.current = record.id

    const fromServer = NARRATIVE_FIELDS.reduce(
      (all, field) => ({ ...all, [field]: record.current![field] ?? '' }),
      {} as Narrative,
    )
    const stashed = readDraft<Narrative>(key)
    const stashedIsNewer =
      stashed && new Date(stashed.at) > new Date(record.current.authored_at)

    setNarrative(stashedIsNewer ? stashed!.value : fromServer)
    setRestored(Boolean(stashedIsNewer))
    setDiagnoses(
      record.current.diagnoses.map((entry) => ({
        description: entry.description,
        certainty: entry.certainty,
        is_primary: entry.is_primary,
      })),
    )
  }, [record, key])

  const persistToServer = useCallback(
    async (value: Narrative, nextDiagnoses: DiagnosisInput[]) => {
      setSaveState('saving')
      try {
        await saveDraft.mutateAsync({ ...value, diagnoses: nextDiagnoses })
        clearDraft(key)
        setSaveState('saved')
        setSavedAt(new Date().toISOString())
        setRestored(false)
      } catch {
        // Kept locally instead. The indicator has to say so: a clinician who
        // believes a note is saved will close the tab.
        setSaveState('local-only')
      }
    },
    [saveDraft, key],
  )

  function edit(field: keyof Narrative, value: string) {
    const next = { ...narrative, [field]: value }
    setNarrative(next)
    writeDraft(key, next)
    setSaveState('idle')
    if (!isDraft) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => persistToServer(next, diagnoses), 1200)
  }

  function updateDiagnoses(next: DiagnosisInput[]) {
    setDiagnoses(next)
    if (!isDraft) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => persistToServer(narrative, next), 600)
  }

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  async function doFinalise() {
    setError(null)
    if (timer.current) clearTimeout(timer.current)
    try {
      await persistToServer(narrative, diagnoses)
      await finalise.mutateAsync()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not finalise the record.')
    }
  }

  async function doAmend() {
    setError(null)
    try {
      await amend.mutateAsync({ reason: amendReason.trim(), ...narrative, diagnoses })
      setAmending(false)
      setAmendReason('')
      clearDraft(key)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not amend the record.')
    }
  }

  if (encounter.isLoading) {
    return (
      <PageShell>
        <p role="status" className="py-10 text-[13px] text-ink-muted">Loading the record…</p>
      </PageShell>
    )
  }
  if (encounter.isError || !record) {
    return (
      <PageShell>
        <Panel className="p-5">
          <p role="alert" className="text-[13px] text-ink-muted">
            This consultation record is not available to you.
          </p>
          <Link href="/clinic" className="mt-3 inline-block text-[13px] font-semibold text-accent">
            Back to clinic
          </Link>
        </Panel>
      </PageShell>
    )
  }

  const latestVitals = vitals.data?.results?.[0]
  const canEdit = isDraft && can('clinical.change_encounter')
  const canAmend = !isDraft && can('clinical.amend_encounter')
  const editable = canEdit || (canAmend && amending)

  return (
    <PageShell>
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
          Consultation
        </span>
        <Link href="/clinic" className="text-[12px] font-semibold text-accent hover:underline">
          Back to clinic
        </Link>
      </div>

      {patient.data && (
        <PatientHeader
          patient={patient.data}
          action={
            <div className="flex flex-wrap items-center gap-2">
              {record.status === 'draft' && <Badge tone="abnormal">Draft</Badge>}
              {record.status === 'final' && <Badge tone="normal">Final</Badge>}
              {record.status === 'amended' && (
                <Badge tone="progress">Amended · {record.version_count} versions</Badge>
              )}
              {can('visits.move_queue') && record.status !== 'draft' && (
                <>
                  <Button
                    variant="secondary"
                    onClick={() => move.mutate({ id: record.visit, to: 'sent_to_pharmacy' })}
                  >
                    Send to pharmacy
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => move.mutate({ id: record.visit, to: 'sent_for_billing' })}
                  >
                    Send to cash desk
                  </Button>
                </>
              )}
            </div>
          }
        />
      )}

      {latestVitals && (
        <Panel className="mt-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
            <span className="text-[10.5px] font-bold tracking-[0.09em] text-ink-faint uppercase">
              Vitals {timeOfDay(latestVitals.recorded_at)}
            </span>
            <Vital label="Temp" value={latestVitals.temperature_c} unit="°C" />
            <Vital label="BP" value={latestVitals.blood_pressure} unit="mmHg" />
            <Vital label="Pulse" value={latestVitals.pulse_bpm} unit="bpm" />
            <Vital label="Resp" value={latestVitals.respiratory_rate} unit="/min" />
            <Vital label="SpO₂" value={latestVitals.oxygen_saturation} unit="%" />
            <Vital label="Weight" value={latestVitals.weight_kg} unit="kg" />
            <Vital label="BMI" value={latestVitals.bmi} />
          </div>
        </Panel>
      )}

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {restored && (
        <p
          role="status"
          className="mt-4 flex items-start gap-2 rounded-lg border border-abnormal/30 bg-abnormal-muted px-4 py-2.5 text-[12.5px] text-abnormal"
        >
          <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
          Restored a newer copy of this note that was held on this device — it had not reached
          the server. Check it, then save.
        </p>
      )}

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[1.35fr_1fr]">
        <div className="grid gap-5">
          <Panel>
            <PanelHeader
              title="Record"
              hint={
                isDraft
                  ? 'Editable while it is a draft. Finalising locks it.'
                  : 'Finalised. Changes append a new version with a reason.'
              }
              action={isDraft ? <SaveIndicator state={saveState} at={savedAt} /> : null}
            />
            <div className="grid gap-4 p-5">
              {NARRATIVE_FIELDS.map((field) => {
                const meta = LABELS[field]
                const value = narrative[field]
                if (!editable && !value) return null
                return (
                  <Field key={field} label={meta.label} hint={meta.hint}>
                    {editable ? (
                      <Textarea
                        value={value}
                        rows={meta.rows ?? 2}
                        onChange={(event) => edit(field, event.target.value)}
                      />
                    ) : (
                      <p className="rounded-md bg-surface-muted px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
                        {value}
                      </p>
                    )}
                  </Field>
                )
              })}
              {!editable && NARRATIVE_FIELDS.every((field) => !narrative[field]) && (
                <EmptyState>Nothing was recorded in this consultation.</EmptyState>
              )}
            </div>
          </Panel>

          <DiagnosisEditor
            diagnoses={diagnoses}
            editable={editable}
            onChange={updateDiagnoses}
          />

          {isDraft ? (
            <Panel className="p-5">
              <p className="text-[12.5px] leading-relaxed text-ink-muted">
                Finalising locks this version. Anything you change afterwards is recorded as an
                amendment with your reason, and the version you are locking now stays on the
                record unchanged.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  onClick={doFinalise}
                  disabled={finalise.isPending || !can('clinical.finalise_encounter')}
                  className="px-4 py-2.5"
                >
                  {finalise.isPending ? 'Finalising…' : 'Finalise record'}
                </Button>
                {!can('clinical.finalise_encounter') && (
                  <p className="self-center text-[12px] text-ink-muted">
                    You can write this record but not finalise it.
                  </p>
                )}
              </div>
            </Panel>
          ) : canAmend ? (
            <Panel className="p-5">
              {amending ? (
                <>
                  <Field label="Why are you amending this record?" required>
                    <Textarea
                      value={amendReason}
                      onChange={(event) => setAmendReason(event.target.value)}
                      autoFocus
                      placeholder="Rapid test result arrived after the consultation"
                    />
                  </Field>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      onClick={doAmend}
                      disabled={amend.isPending || !amendReason.trim()}
                      className="px-4 py-2.5"
                    >
                      {amend.isPending ? 'Saving amendment…' : 'Save amendment'}
                    </Button>
                    <Button variant="secondary" onClick={() => setAmending(false)}>
                      Cancel
                    </Button>
                  </div>
                </>
              ) : (
                <Button variant="secondary" onClick={() => setAmending(true)}>
                  Amend this record
                </Button>
              )}
            </Panel>
          ) : null}

          {(record.version_count ?? 1) > 1 && (
            <Panel>
              <PanelHeader
                title="Version history"
                hint="Earlier versions are kept exactly as they were written"
              />
              <ul className="divide-y divide-border">
                {(versions.data ?? []).map((version) => (
                  <li key={version.id} className="p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-[12.5px] font-semibold text-ink">
                        Version {version.version_number}
                        {version.is_current && (
                          <span className="ml-2 text-[11px] font-normal text-normal">current</span>
                        )}
                      </p>
                      <p className="text-[11.5px] text-ink-faint">
                        {version.authored_by} · {dateAndTime(version.authored_at)}
                      </p>
                    </div>
                    {version.amendment_reason && (
                      <p className="mt-1.5 rounded-md bg-abnormal-muted px-3 py-1.5 text-[12px] text-abnormal">
                        Reason: {version.amendment_reason}
                      </p>
                    )}
                    {version.diagnoses.length > 0 && (
                      <p className="mt-2 text-[12px] text-ink-muted">
                        {version.diagnoses.map((entry) => entry.description).join(', ')}
                      </p>
                    )}
                    {version.clinical_notes && (
                      <p className="mt-1.5 text-[12px] leading-relaxed whitespace-pre-wrap text-ink-muted">
                        {version.clinical_notes}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>

        <div className="grid gap-5">
          {can('laboratory.add_laborder') && (
            <OrderTestsPanel visitId={record.visit} onOrdered={() => labs.refetch()} />
          )}

          {(labs.data?.results ?? []).length > 0 && (
            <Panel>
              <PanelHeader title="Results this visit" hint="Verified results only appear as findings" />
              {labs.data!.results.map((order) =>
                order.items.map((item) => (
                  <div key={item.id} className="border-b border-border last:border-b-0">
                    <div className="flex items-center justify-between gap-2 bg-surface-muted/40 px-5 py-2">
                      <span className="text-[12.5px] font-semibold text-ink">{item.test_name}</span>
                      <Badge tone={labTone(item.status)}>{labLabel(item.status)}</Badge>
                    </div>
                    {item.status === 'verified' && item.results.length > 0 ? (
                      <TableFrame minWidth={420}>
                        <thead>
                          <tr>
                            <Th>Measurement</Th>
                            <Th className="text-right">Result</Th>
                            <Th>Flag</Th>
                            <Th>Reference</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {item.results.map((result) => (
                            <tr key={result.id}>
                              <Td>{result.parameter_name}</Td>
                              <Td
                                className={`text-right font-semibold ${
                                  result.is_critical
                                    ? 'text-critical'
                                    : result.is_abnormal
                                      ? 'text-abnormal'
                                      : ''
                                }`}
                              >
                                {result.display_value} {result.unit}
                              </Td>
                              <Td>
                                <ClinicalFlag flag={result.flag} label={result.flag_label} />
                              </Td>
                              <Td className="text-ink-muted">{result.reference_text || '—'}</Td>
                            </tr>
                          ))}
                        </tbody>
                      </TableFrame>
                    ) : (
                      <p className="px-5 py-3 text-[12px] text-ink-faint">
                        Not yet verified — no findings to read.
                      </p>
                    )}
                  </div>
                )),
              )}
            </Panel>
          )}

          {can('pharmacy.add_prescription') && patient.data && (
            <PrescribePanel
              patientId={record.patient}
              visitId={record.visit}
              encounterId={record.id}
              onWritten={() => prescriptions.refetch()}
            />
          )}

          {(prescriptions.data?.results ?? []).length > 0 && (
            <Panel>
              <PanelHeader title="Prescribed this visit" />
              <ul className="divide-y divide-border">
                {prescriptions.data!.results.flatMap((prescription) =>
                  prescription.items.map((item) => (
                    <li key={item.id} className="px-5 py-3">
                      <p className="text-[12.5px] font-semibold text-ink">{item.medication_label}</p>
                      <p className="mt-0.5 text-[11.5px] text-ink-muted">
                        {Number(item.dose)} {item.dose_unit} · {item.route} ·{' '}
                        {item.frequency_per_day}×/day · {item.duration_days} days
                      </p>
                      {item.overrides.length > 0 && (
                        <p className="mt-1 text-[11px] font-semibold text-critical">
                          Override: {item.overrides[0].reason}
                        </p>
                      )}
                    </li>
                  )),
                )}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </PageShell>
  )
}

function Vital({ label, value, unit }: { label: string; value?: string | number | null; unit?: string }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <span className="text-[12.5px]">
      <span className="text-ink-muted">{label} </span>
      <span className="font-semibold text-ink">{value}</span>
      {unit && <span className="ml-0.5 text-[11px] text-ink-faint">{unit}</span>}
    </span>
  )
}

/** Never ambiguous about whether the note has reached the server. */
function SaveIndicator({ state, at }: { state: SaveState; at: string | null }) {
  if (state === 'saving') {
    return <span role="status" className="text-[11.5px] text-ink-muted">Saving…</span>
  }
  if (state === 'local-only') {
    return (
      <span role="status" className="flex items-center gap-1 text-[11.5px] font-semibold text-critical">
        <AlertIcon className="size-3.5" />
        Not saved — kept on this device
      </span>
    )
  }
  if (state === 'saved' && at) {
    return <span role="status" className="text-[11.5px] text-normal">Saved {timeOfDay(at)}</span>
  }
  return <span className="text-[11.5px] text-ink-faint">Unsaved changes</span>
}

function DiagnosisEditor({
  diagnoses,
  editable,
  onChange,
}: {
  diagnoses: DiagnosisInput[]
  editable: boolean
  onChange: (next: DiagnosisInput[]) => void
}) {
  const [description, setDescription] = useState('')
  const [certainty, setCertainty] = useState('provisional')

  function add() {
    if (!description.trim()) return
    onChange([
      ...diagnoses,
      { description: description.trim(), certainty, is_primary: diagnoses.length === 0 },
    ])
    setDescription('')
  }

  return (
    <Panel>
      <PanelHeader
        title="Diagnoses"
        hint="Attached to this version, so an amendment cannot rewrite an earlier one"
      />
      <div className="p-5">
        {diagnoses.length === 0 ? (
          <EmptyState>No diagnosis recorded.</EmptyState>
        ) : (
          <ul className="grid gap-2">
            {diagnoses.map((entry, index) => (
              <li
                key={`${entry.description}-${index}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="text-[13px] font-semibold text-ink">{entry.description}</span>
                  <span className="ml-2 text-[11.5px] text-ink-muted capitalize">
                    {entry.certainty}
                  </span>
                  {entry.is_primary && (
                    <Badge tone="accent">Primary</Badge>
                  )}
                </span>
                {editable && (
                  <span className="flex gap-1">
                    {!entry.is_primary && (
                      <Button
                        variant="ghost"
                        onClick={() =>
                          onChange(
                            diagnoses.map((item, i) => ({ ...item, is_primary: i === index })),
                          )
                        }
                      >
                        Make primary
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      onClick={() => onChange(diagnoses.filter((_, i) => i !== index))}
                    >
                      Remove
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}

        {editable && (
          <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_160px_auto]">
            <Input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  add()
                }
              }}
              placeholder="Malaria"
              aria-label="Diagnosis"
            />
            <Select
              value={certainty}
              onChange={(event) => setCertainty(event.target.value)}
              aria-label="Certainty"
            >
              <option value="provisional">Provisional</option>
              <option value="confirmed">Confirmed</option>
              <option value="differential">Differential</option>
            </Select>
            <Button variant="secondary" onClick={add} disabled={!description.trim()}>
              Add
            </Button>
          </div>
        )}
      </div>
    </Panel>
  )
}
