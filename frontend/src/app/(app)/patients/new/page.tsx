'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, PageHeading, PageShell } from '@/components/PageShell'
import { Button, Field, Input, Panel, PanelHeader, Select, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type DuplicateCandidate, useRegisterPatient } from '@/lib/queries'

/**
 * Registration.
 *
 * The important behaviour here is what happens when the server thinks this
 * person already has a chart. A duplicate record splits a patient's history,
 * allergies and results across two files, so the server refuses the first
 * attempt and returns the candidates — and this screen puts them in front of
 * the user with the reasons for the match, and makes opening the existing
 * record the easiest thing to do.
 *
 * It is a warning, not a wall: twins get registered together and fathers and
 * sons share names and phone numbers. Someone holding the override permission
 * can proceed, but only with a reason, which is stored.
 */

const SEXES = [
  { value: '', label: 'Select…' },
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
  { value: 'other', label: 'Other' },
  { value: 'unknown', label: 'Unknown' },
]
const BLOOD_GROUPS = ['', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const GENOTYPES = ['', 'AA', 'AS', 'AC', 'SS', 'SC', 'CC']

type Form = {
  given_name: string
  family_name: string
  other_names: string
  date_of_birth: string
  date_of_birth_is_estimated: boolean
  sex: string
  phone_primary: string
  phone_alternate: string
  email: string
  address_line: string
  city: string
  state: string
  blood_group: string
  genotype: string
  allergy_substance: string
  allergy_reaction: string
  allergy_severity: string
  chronic_condition: string
  kin_name: string
  kin_relationship: string
  kin_phone: string
}

const EMPTY: Form = {
  given_name: '', family_name: '', other_names: '', date_of_birth: '',
  date_of_birth_is_estimated: false, sex: '', phone_primary: '', phone_alternate: '',
  email: '', address_line: '', city: '', state: '', blood_group: '', genotype: '',
  allergy_substance: '', allergy_reaction: '', allergy_severity: 'moderate',
  chronic_condition: '', kin_name: '', kin_relationship: '', kin_phone: '',
}

export default function RegisterPatientPage() {
  const router = useRouter()
  const { facility, can } = useAuth()
  const register = useRegisterPatient()

  const [form, setForm] = useState<Form>(EMPTY)
  const [fields, setFields] = useState<Record<string, string[]>>({})
  const [error, setError] = useState<string | null>(null)
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[] | null>(null)
  const [overrideReason, setOverrideReason] = useState('')

  const canOverride = can('patients.register_duplicate_patient')

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function payload(acknowledge: boolean) {
    const body: Record<string, unknown> = {
      given_name: form.given_name.trim(),
      family_name: form.family_name.trim(),
      other_names: form.other_names.trim(),
      date_of_birth: form.date_of_birth || null,
      date_of_birth_is_estimated: form.date_of_birth_is_estimated,
      sex: form.sex,
      phone_primary: form.phone_primary.trim(),
      phone_alternate: form.phone_alternate.trim(),
      email: form.email.trim(),
      address_line: form.address_line.trim(),
      city: form.city.trim(),
      state: form.state.trim(),
      blood_group: form.blood_group,
      genotype: form.genotype,
      facility: facility?.id,
    }
    if (form.allergy_substance.trim()) {
      body.allergies = [
        {
          substance: form.allergy_substance.trim(),
          reaction: form.allergy_reaction.trim(),
          severity: form.allergy_severity,
        },
      ]
    }
    if (form.chronic_condition.trim()) {
      body.chronic_conditions = [{ condition: form.chronic_condition.trim() }]
    }
    if (form.kin_name.trim()) {
      body.next_of_kin = [
        {
          full_name: form.kin_name.trim(),
          relationship: form.kin_relationship.trim(),
          phone: form.kin_phone.trim(),
        },
      ]
    }
    if (acknowledge) {
      body.acknowledge_duplicate = true
      body.duplicate_reason = overrideReason.trim()
    }
    return body
  }

  async function submit(event: React.FormEvent, acknowledge = false) {
    event.preventDefault()
    setError(null)
    setFields({})
    try {
      const created = await register.mutateAsync(payload(acknowledge))
      router.replace(`/patients/${created.id}`)
    } catch (caught) {
      if (!(caught instanceof ApiError)) {
        setError('Could not reach the hospital server. Nothing was saved.')
        return
      }
      if (caught.status === 409) {
        const body = caught.body as { duplicates?: DuplicateCandidate[] } | null
        setDuplicates(body?.duplicates ?? [])
        return
      }
      setFields(caught.fields)
      setError(caught.message)
    }
  }

  if (duplicates) {
    return (
      <PageShell>
        <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-critical uppercase">
          Possible duplicate
        </div>
        <PageHeading
          title="This patient may already have a record"
          subtitle="Registering a second chart splits a patient's history, allergies and results across two files. Check these before continuing."
        />

        <Panel className="mt-6 border-critical/40">
          <PanelHeader
            title={`${duplicates.length} existing record${duplicates.length === 1 ? '' : 's'} matched`}
            hint="Opening the existing record is almost always the right action."
          />
          <ul className="divide-y divide-border">
            {duplicates.map((candidate) => (
              <li key={candidate.patient.id} className="flex flex-wrap items-start justify-between gap-3 p-5">
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold text-ink">{candidate.patient.full_name}</p>
                  <p className="mt-0.5 font-mono text-[11.5px] text-ink-muted">
                    {candidate.patient.hospital_number}
                    <span className="ml-2 font-sans capitalize">{candidate.patient.sex}</span>
                    {candidate.patient.age_years !== null && (
                      <span className="ml-2 font-sans">{candidate.patient.age_years}y</span>
                    )}
                    {candidate.patient.phone_primary && (
                      <span className="ml-2 font-sans">{candidate.patient.phone_primary}</span>
                    )}
                  </p>
                  <ul className="mt-2 space-y-0.5">
                    {candidate.reasons.map((reason) => (
                      <li key={reason} className="flex items-start gap-1.5 text-[12px] text-critical">
                        <AlertIcon className="mt-0.5 size-3 shrink-0" />
                        {reason}
                      </li>
                    ))}
                  </ul>
                </div>
                <Link
                  href={`/patients/${candidate.patient.id}`}
                  className="inline-flex shrink-0 items-center justify-center rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
                >
                  Open this patient
                </Link>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel className="mt-5">
          <PanelHeader
            title="None of these is the same person"
            hint={
              canOverride
                ? 'Say why, and the new record will be created. Your reason is stored on the record.'
                : 'This needs someone with the records permission to confirm.'
            }
          />
          <div className="p-5">
            {canOverride ? (
              <form onSubmit={(event) => submit(event, true)}>
                <Field
                  label="Why is this a different person?"
                  required
                  error={fields.duplicate_reason}
                  hint="For example: twin sister registered at the same time; father and son share a name and phone."
                >
                  <Textarea
                    value={overrideReason}
                    onChange={(event) => setOverrideReason(event.target.value)}
                    required
                    autoFocus
                  />
                </Field>
                {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    type="submit"
                    variant="danger"
                    disabled={register.isPending || !overrideReason.trim()}
                  >
                    {register.isPending ? 'Registering…' : 'Register anyway'}
                  </Button>
                  <Button variant="secondary" onClick={() => setDuplicates(null)}>
                    Back to the form
                  </Button>
                </div>
              </form>
            ) : (
              <>
                <p className="text-[13px] leading-relaxed text-ink-muted">
                  You do not hold the permission to register a patient despite a suspected
                  duplicate. Ask a medical records officer to confirm, or open the existing
                  record above if it is the same person.
                </p>
                <div className="mt-4">
                  <Button variant="secondary" onClick={() => setDuplicates(null)}>
                    Back to the form
                  </Button>
                </div>
              </>
            )}
          </div>
        </Panel>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Medical records
      </div>
      <PageHeading
        title="Register a patient"
        subtitle={facility ? `New record at ${facility.name}` : 'No facility selected'}
        action={
          <Link
            href="/patients"
            className="inline-flex items-center justify-center rounded-lg border border-border px-3 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-muted"
          >
            Cancel
          </Link>
        }
      />

      {error && <div className="mt-5"><ErrorNotice>{error}</ErrorNotice></div>}

      <form onSubmit={(event) => submit(event)} className="mt-6 grid gap-5 xl:grid-cols-[1.3fr_1fr]">
        <div className="grid gap-5">
          <Panel>
            <PanelHeader title="Identity" hint="Only name and sex are required to open a record." />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Given name" required error={fields.given_name}>
                <Input
                  value={form.given_name}
                  onChange={(event) => set('given_name', event.target.value)}
                  required
                  autoFocus
                  autoComplete="off"
                />
              </Field>
              <Field label="Family name" required error={fields.family_name}>
                <Input
                  value={form.family_name}
                  onChange={(event) => set('family_name', event.target.value)}
                  required
                  autoComplete="off"
                />
              </Field>
              <Field label="Other names" error={fields.other_names}>
                <Input
                  value={form.other_names}
                  onChange={(event) => set('other_names', event.target.value)}
                  autoComplete="off"
                />
              </Field>
              <Field label="Sex" required error={fields.sex} hint="Used for laboratory reference ranges.">
                <Select value={form.sex} onChange={(event) => set('sex', event.target.value)} required>
                  {SEXES.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Date of birth" error={fields.date_of_birth}>
                <Input
                  type="date"
                  value={form.date_of_birth}
                  onChange={(event) => set('date_of_birth', event.target.value)}
                />
              </Field>
              <div className="flex items-end">
                {/* Plenty of patients do not know an exact date. Recording an
                    estimate as if it were exact is worse than recording that it
                    is an estimate. */}
                <label className="flex items-center gap-2 pb-2 text-[12.5px] text-ink">
                  <input
                    type="checkbox"
                    checked={form.date_of_birth_is_estimated}
                    onChange={(event) => set('date_of_birth_is_estimated', event.target.checked)}
                    className="size-4 rounded border-border"
                  />
                  Date of birth is estimated
                </label>
              </div>
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Contact" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Phone number" error={fields.phone_primary} hint="Used to find returning patients.">
                <Input
                  type="tel"
                  value={form.phone_primary}
                  onChange={(event) => set('phone_primary', event.target.value)}
                  placeholder="08031234567"
                  autoComplete="off"
                />
              </Field>
              <Field label="Alternate phone" error={fields.phone_alternate}>
                <Input
                  type="tel"
                  value={form.phone_alternate}
                  onChange={(event) => set('phone_alternate', event.target.value)}
                  autoComplete="off"
                />
              </Field>
              <Field label="Email" error={fields.email}>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(event) => set('email', event.target.value)}
                  autoComplete="off"
                />
              </Field>
              <Field label="Address" error={fields.address_line}>
                <Input
                  value={form.address_line}
                  onChange={(event) => set('address_line', event.target.value)}
                  autoComplete="off"
                />
              </Field>
              <Field label="Town or city" error={fields.city}>
                <Input value={form.city} onChange={(event) => set('city', event.target.value)} />
              </Field>
              <Field label="State" error={fields.state}>
                <Input value={form.state} onChange={(event) => set('state', event.target.value)} />
              </Field>
            </div>
          </Panel>
        </div>

        <div className="grid content-start gap-5">
          <Panel className="border-critical/30">
            <PanelHeader
              title="Allergies"
              hint="Shown on every clinical screen and checked at prescribing."
            />
            <div className="grid gap-4 p-5">
              <Field label="Allergic to" hint="Leave blank if none are known.">
                <Input
                  value={form.allergy_substance}
                  onChange={(event) => set('allergy_substance', event.target.value)}
                  placeholder="Penicillin"
                />
              </Field>
              <Field label="Reaction">
                <Input
                  value={form.allergy_reaction}
                  onChange={(event) => set('allergy_reaction', event.target.value)}
                  placeholder="Rash, swelling, anaphylaxis"
                />
              </Field>
              <Field label="Severity">
                <Select
                  value={form.allergy_severity}
                  onChange={(event) => set('allergy_severity', event.target.value)}
                >
                  <option value="mild">Mild</option>
                  <option value="moderate">Moderate</option>
                  <option value="severe">Severe</option>
                </Select>
              </Field>
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Clinical background" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Blood group">
                <Select
                  value={form.blood_group}
                  onChange={(event) => set('blood_group', event.target.value)}
                >
                  {BLOOD_GROUPS.map((entry) => (
                    <option key={entry} value={entry}>
                      {entry || 'Unknown'}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Genotype">
                <Select value={form.genotype} onChange={(event) => set('genotype', event.target.value)}>
                  {GENOTYPES.map((entry) => (
                    <option key={entry} value={entry}>
                      {entry || 'Unknown'}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="sm:col-span-2">
                <Field label="Chronic condition" hint="Checked against prescribing contraindications.">
                  <Input
                    value={form.chronic_condition}
                    onChange={(event) => set('chronic_condition', event.target.value)}
                    placeholder="Hypertension"
                  />
                </Field>
              </div>
            </div>
          </Panel>

          <Panel>
            <PanelHeader title="Next of kin" />
            <div className="grid gap-4 p-5">
              <Field label="Full name">
                <Input value={form.kin_name} onChange={(event) => set('kin_name', event.target.value)} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Relationship">
                  <Input
                    value={form.kin_relationship}
                    onChange={(event) => set('kin_relationship', event.target.value)}
                    placeholder="Brother"
                  />
                </Field>
                <Field label="Phone">
                  <Input
                    type="tel"
                    value={form.kin_phone}
                    onChange={(event) => set('kin_phone', event.target.value)}
                  />
                </Field>
              </div>
            </div>
          </Panel>

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={register.isPending} className="px-4 py-2.5">
              {register.isPending ? 'Checking for duplicates…' : 'Register patient'}
            </Button>
            <Link
              href="/patients"
              className="inline-flex items-center justify-center rounded-lg border border-border px-3 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-muted"
            >
              Cancel
            </Link>
          </div>
        </div>
      </form>
    </PageShell>
  )
}
