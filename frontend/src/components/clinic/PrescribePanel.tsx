'use client'

import { useMemo, useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice } from '@/components/PageShell'
import { Badge, Button, Field, Input, Panel, PanelHeader, Select, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type MedicationOption, type PrescriptionItemInput, type SafetyWarning,
  useMedications, useSafetyCapabilities, useScreenMedication, useWritePrescription,
} from '@/lib/clinical'

/**
 * Prescribing, with the safety screen in front of it.
 *
 * Three things here are deliberate and not negotiable in a hospital:
 *
 * 1. The drug is screened against this patient *before* it joins the
 *    prescription, so the warning arrives while the decision is still being
 *    made rather than after the whole script is written.
 * 2. A serious warning cannot be clicked away. Proceeding needs the override
 *    permission and a typed reason, which is stored against the line — a
 *    warning that can be dismissed without trace is not a safety control.
 * 3. The panel states which checks are running and, plainly, that drug–drug
 *    interaction checking is not. A clinician who believes a check happened
 *    prescribes as though it did, so an absent check must be visible.
 */

const ROUTES = ['oral', 'iv', 'im', 'sc', 'topical', 'rectal', 'inhaled', 'ophthalmic']

type Draft = {
  medication: MedicationOption | null
  dose: string
  dose_unit: string
  route: string
  frequency_per_day: string
  duration_days: string
  quantity_prescribed: string
  instructions: string
}

const EMPTY: Draft = {
  medication: null, dose: '', dose_unit: 'mg', route: 'oral',
  frequency_per_day: '3', duration_days: '5', quantity_prescribed: '', instructions: '',
}

type StagedLine = PrescriptionItemInput & { label: string; warnings: SafetyWarning[] }

export function PrescribePanel({
  patientId,
  visitId,
  encounterId,
  onWritten,
}: {
  patientId: number
  visitId: number
  encounterId: number | null
  onWritten?: () => void
}) {
  const { can } = useAuth()
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [lines, setLines] = useState<StagedLine[]>([])
  const [warnings, setWarnings] = useState<SafetyWarning[] | null>(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [written, setWritten] = useState<string | null>(null)

  const medications = useMedications(search)
  const capabilities = useSafetyCapabilities()
  const screen = useScreenMedication()
  const write = useWritePrescription()

  const canOverride = can('pharmacy.override_safety_warning')
  const interaction = capabilities.data?.drug_drug_interaction

  const blocking = useMemo(
    () => (warnings ?? []).filter((warning) => warning.requires_reason),
    [warnings],
  )

  /** Suggested pack size, so the quantity field is not busywork. */
  const suggestedQuantity = useMemo(() => {
    const frequency = Number(draft.frequency_per_day)
    const days = Number(draft.duration_days)
    if (!frequency || !days) return ''
    return String(frequency * days)
  }, [draft.frequency_per_day, draft.duration_days])

  function chooseMedication(option: MedicationOption) {
    const range = option.dose_ranges.find((entry) => entry.route === option.default_route)
    setDraft({
      ...EMPTY,
      medication: option,
      route: option.default_route,
      dose_unit: range?.dose_unit ?? 'mg',
      dose: range ? String(Number(range.max_single_dose)) : '',
    })
    setWarnings(null)
    setError(null)
    setSearch('')
  }

  async function runScreen() {
    if (!draft.medication) return
    setError(null)
    try {
      const result = await screen.mutateAsync({
        patient: patientId,
        medication: draft.medication.id,
        dose: draft.dose || undefined,
        route: draft.route,
        frequency_per_day: Number(draft.frequency_per_day) || undefined,
      })
      setWarnings(result.warnings)
    } catch {
      setError('Could not run the safety checks. The drug was not added.')
    }
  }

  function addLine() {
    if (!draft.medication) return
    setLines((current) => [
      ...current,
      {
        medication: draft.medication!.id,
        label: draft.medication!.label,
        dose: draft.dose,
        dose_unit: draft.dose_unit,
        route: draft.route,
        frequency_per_day: Number(draft.frequency_per_day) || 1,
        duration_days: Number(draft.duration_days) || 1,
        quantity_prescribed: Number(draft.quantity_prescribed || suggestedQuantity) || 1,
        instructions: draft.instructions,
        warnings: warnings ?? [],
      },
    ])
    setDraft(EMPTY)
    setWarnings(null)
  }

  async function submit(acknowledge: boolean) {
    setError(null)
    try {
      await write.mutateAsync({
        visit: visitId,
        encounter: encounterId,
        items: lines.map(({ label, warnings: _ignored, ...item }) => item),
        acknowledge_warnings: acknowledge,
        override_reason: acknowledge ? overrideReason.trim() : undefined,
      })
      setLines([])
      setOverrideReason('')
      setWritten('Prescription sent to the pharmacy.')
      onWritten?.()
    } catch (caught) {
      if (!(caught instanceof ApiError)) {
        setError('Could not reach the hospital server. Nothing was prescribed.')
        return
      }
      if (caught.status === 409) {
        const body = caught.body as { warnings?: (SafetyWarning & { medication: string })[] } | null
        setWarnings(body?.warnings ?? [])
        setError(null)
        return
      }
      setError(caught.message)
    }
  }

  const stagedBlocking = lines.flatMap((line) =>
    line.warnings.filter((warning) => warning.requires_reason),
  )
  const needsReason = stagedBlocking.length > 0 || blocking.length > 0

  return (
    <Panel>
      <PanelHeader
        title="Prescribe"
        hint={`${lines.length} item${lines.length === 1 ? '' : 's'} staged`}
      />

      {/* What is and is not being checked. Stated before anything is typed. */}
      {interaction && !interaction.active && (
        <p className="flex items-start gap-2 border-b border-abnormal/25 bg-abnormal-muted px-5 py-2.5 text-[12px] leading-relaxed text-abnormal">
          <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>
            <strong className="font-bold">Drug–drug interaction checking is not active.</strong>{' '}
            Allergies, duplicate therapy, dose range and recorded contraindications are
            checked. Interactions are not — check them independently.
          </span>
        </p>
      )}

      <div className="grid gap-4 p-5">
        {!draft.medication ? (
          <Field label="Medication" hint="Search the hospital formulary.">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Amoxicillin, paracetamol…"
            />
            {search.length > 1 && (
              <div className="mt-2 max-h-60 overflow-y-auto rounded-lg border border-border">
                {(medications.data ?? []).length === 0 ? (
                  <p className="px-3 py-4 text-center text-[12px] text-ink-faint">
                    Nothing in the formulary matches. The pharmacy has to add it before it can
                    be prescribed.
                  </p>
                ) : (
                  medications.data!.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => chooseMedication(option)}
                      className="block w-full border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-surface-muted"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-[12.5px] font-semibold text-ink">{option.label}</span>
                        <span
                          className={`text-[11px] ${
                            option.stock_on_hand > 0 ? 'text-ink-faint' : 'font-semibold text-critical'
                          }`}
                        >
                          {option.stock_on_hand > 0
                            ? `${option.stock_on_hand} in stock`
                            : 'Out of stock'}
                        </span>
                      </span>
                      <span className="mt-0.5 block text-[11px] text-ink-faint">
                        {option.category_name}
                        {option.caution_note && ` · ${option.caution_note}`}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </Field>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-muted px-3 py-2">
              <span className="text-[13px] font-semibold text-ink">{draft.medication.label}</span>
              <div className="flex items-center gap-2">
                <span
                  className={`text-[11.5px] ${
                    draft.medication.stock_on_hand > 0 ? 'text-ink-muted' : 'font-semibold text-critical'
                  }`}
                >
                  {draft.medication.stock_on_hand > 0
                    ? `${draft.medication.stock_on_hand} in stock`
                    : 'Out of stock'}
                </span>
                <Button variant="ghost" onClick={() => { setDraft(EMPTY); setWarnings(null) }}>
                  Change
                </Button>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Dose">
                <div className="flex gap-1.5">
                  <Input
                    value={draft.dose}
                    onChange={(event) => {
                      setDraft({ ...draft, dose: event.target.value })
                      setWarnings(null)
                    }}
                    inputMode="decimal"
                    className="text-right"
                  />
                  <Input
                    value={draft.dose_unit}
                    onChange={(event) => setDraft({ ...draft, dose_unit: event.target.value })}
                    className="w-20"
                  />
                </div>
              </Field>
              <Field label="Route">
                <Select
                  value={draft.route}
                  onChange={(event) => {
                    setDraft({ ...draft, route: event.target.value })
                    setWarnings(null)
                  }}
                >
                  {ROUTES.map((route) => (
                    <option key={route} value={route}>
                      {route}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Times a day">
                <Input
                  type="number"
                  min={1}
                  value={draft.frequency_per_day}
                  onChange={(event) => {
                    setDraft({ ...draft, frequency_per_day: event.target.value })
                    setWarnings(null)
                  }}
                  className="text-right"
                />
              </Field>
              <Field label="Days">
                <Input
                  type="number"
                  min={1}
                  value={draft.duration_days}
                  onChange={(event) => setDraft({ ...draft, duration_days: event.target.value })}
                  className="text-right"
                />
              </Field>
              <Field label="Quantity" hint={suggestedQuantity ? `Suggested ${suggestedQuantity}` : undefined}>
                <Input
                  type="number"
                  min={1}
                  value={draft.quantity_prescribed || suggestedQuantity}
                  onChange={(event) =>
                    setDraft({ ...draft, quantity_prescribed: event.target.value })
                  }
                  className="text-right"
                />
              </Field>
              <Field label="Directions">
                <Input
                  value={draft.instructions}
                  onChange={(event) => setDraft({ ...draft, instructions: event.target.value })}
                  placeholder="After food"
                />
              </Field>
            </div>

            {warnings === null ? (
              <div>
                <Button onClick={runScreen} disabled={screen.isPending}>
                  {screen.isPending ? 'Checking…' : 'Check against this patient'}
                </Button>
                <p className="mt-1.5 text-[11.5px] text-ink-faint">
                  Runs before the drug is added, so a warning arrives while the decision is
                  still open.
                </p>
              </div>
            ) : (
              <>
                <WarningList warnings={warnings} />
                <div className="flex flex-wrap gap-2">
                  <Button onClick={addLine} variant={blocking.length > 0 ? 'danger' : 'primary'}>
                    {blocking.length > 0 ? 'Add despite the warning' : 'Add to prescription'}
                  </Button>
                  <Button variant="secondary" onClick={() => setWarnings(null)}>
                    Change the order
                  </Button>
                </div>
              </>
            )}
          </>
        )}
      </div>

      {lines.length > 0 && (
        <div className="border-t border-border">
          <ul className="divide-y divide-border">
            {lines.map((line, index) => (
              <li key={`${line.medication}-${index}`} className="px-5 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-ink">{line.label}</p>
                    <p className="mt-0.5 text-[12px] text-ink-muted">
                      {line.dose} {line.dose_unit} · {line.route} · {line.frequency_per_day}×/day
                      · {line.duration_days} days · {line.quantity_prescribed} to dispense
                      {line.instructions && ` · ${line.instructions}`}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() => setLines((current) => current.filter((_, i) => i !== index))}
                  >
                    Remove
                  </Button>
                </div>
                {line.warnings.filter((w) => w.requires_reason).length > 0 && (
                  <p className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-critical-muted px-2 py-0.5 text-[11px] font-bold text-critical">
                    <AlertIcon className="size-3" />
                    {line.warnings.filter((w) => w.requires_reason).length} warning
                    {line.warnings.filter((w) => w.requires_reason).length === 1 ? '' : 's'} to
                    justify
                  </p>
                )}
              </li>
            ))}
          </ul>

          <div className="border-t border-border p-5">
            {error && <ErrorNotice>{error}</ErrorNotice>}
            {written && (
              <p
                role="status"
                className="mb-3 rounded-md border border-normal/30 bg-normal-muted px-3 py-2 text-[12.5px] font-medium text-normal"
              >
                {written}
              </p>
            )}

            {needsReason && (
              <div className="mb-4 rounded-lg border border-critical/30 bg-critical-muted p-4">
                <p className="mb-2 text-[12.5px] font-bold text-critical">
                  This prescription overrides a safety warning
                </p>
                {canOverride ? (
                  <Field label="Why is this appropriate for this patient?" required>
                    <Textarea
                      value={overrideReason}
                      onChange={(event) => setOverrideReason(event.target.value)}
                      placeholder="Documented rash was non-urticarial; benefit outweighs the risk. Discussed with the patient."
                    />
                  </Field>
                ) : (
                  <p className="text-[12.5px] leading-relaxed text-critical">
                    You do not hold the permission to prescribe past a safety warning. Remove
                    the flagged item, or ask a consultant to prescribe it.
                  </p>
                )}
              </div>
            )}

            <Button
              onClick={() => submit(needsReason)}
              disabled={
                write.isPending ||
                (needsReason && (!canOverride || !overrideReason.trim()))
              }
              className="px-4 py-2.5"
            >
              {write.isPending ? 'Sending…' : 'Send to pharmacy'}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  )
}

/** Worst first, each with its severity in words as well as colour. */
function WarningList({ warnings }: { warnings: SafetyWarning[] }) {
  if (warnings.length === 0) {
    return (
      <p
        role="status"
        className="rounded-lg border border-normal/30 bg-normal-muted px-3 py-2.5 text-[12.5px] font-medium text-normal"
      >
        No warnings from the checks that are active.
      </p>
    )
  }

  const TONE = {
    critical: 'border-critical/30 bg-critical-muted text-critical',
    warning: 'border-abnormal/30 bg-abnormal-muted text-abnormal',
    advisory: 'border-border bg-surface-muted text-ink-muted',
  } as const

  const LABEL = { critical: 'Critical', warning: 'Warning', advisory: 'Advisory' } as const

  return (
    <ul className="grid gap-2">
      {warnings.map((warning, index) => (
        <li
          key={`${warning.kind}-${index}`}
          className={`rounded-lg border px-3 py-2.5 ${TONE[warning.severity]}`}
        >
          <div className="flex items-start gap-2">
            {warning.severity !== 'advisory' && (
              <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
            )}
            <div className="min-w-0">
              <p className="text-[11px] font-bold tracking-wide uppercase">
                {LABEL[warning.severity]} · {warning.kind.replace(/_/g, ' ')}
              </p>
              <p className="mt-0.5 text-[12.5px] leading-relaxed">{warning.detail}</p>
              {warning.requires_reason && (
                <p className="mt-1 text-[11px] font-semibold">
                  Proceeding requires a stated reason.
                </p>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function SafetyCapabilitySummary() {
  const capabilities = useSafetyCapabilities()
  if (!capabilities.data) return null
  return (
    <ul className="grid gap-1.5">
      {Object.entries(capabilities.data).map(([kind, capability]) => (
        <li key={kind} className="flex items-start gap-2 text-[12px]">
          <Badge tone={capability.active ? 'normal' : 'critical'}>
            {capability.active ? 'Active' : 'Not active'}
          </Badge>
          <span className="min-w-0">
            <span className="font-semibold text-ink capitalize">
              {kind.replace(/_/g, ' ')}
            </span>
            <span className="mt-0.5 block text-ink-muted">{capability.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}
