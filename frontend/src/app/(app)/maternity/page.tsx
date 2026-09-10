'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, StatTile,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useStaff } from '@/lib/config'
import {
  type Pregnancy,
  useAntenatalVisit, useBookPregnancy, useDueSoon, usePregnancies,
  useRecordDelivery, useReviseEdd,
} from '@/lib/maternity'
import { dateAndTime, fullDate } from '@/lib/workflow'

/**
 * Maternity.
 *
 * The estimated delivery date always appears with *how it was arrived at*.
 * The three usual bases — last period, dating scan, examination — disagree by
 * up to a fortnight, and every decision about prematurity turns on which one
 * is in use. A date without its basis is a number somebody will act on
 * wrongly.
 *
 * A hospital that does not provide maternity grants none of these
 * permissions, and this whole section never appears.
 */
export default function MaternityPage() {
  const { can, facility } = useAuth()
  const facilityId = facility?.id ?? null

  const ongoing = usePregnancies('?open=true')
  const due = useDueSoon(facilityId)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  const pregnancies = ongoing.data ?? []
  const overdue = due.data?.overdue ?? []
  const soon = (due.data?.due ?? []).filter(
    (p) => !overdue.some((o) => o.id === p.id),
  )

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      return true
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'That action could not be completed.',
      )
      return false
    }
  }

  const current = pregnancies.find((p) => p.id === selected) ?? null

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Maternity
      </div>
      <PageHeading
        title="Maternity"
        subtitle="Every estimated delivery date shows how it was worked out — the three usual bases disagree by up to a fortnight."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Pregnancies booked" value={pregnancies.length} />
        <StatTile
          label="Due within four weeks"
          value={soon.length}
          tone={soon.length ? 'progress' : 'normal'}
        />
        <StatTile
          label="Past their date"
          value={overdue.length}
          tone={overdue.length ? 'abnormal' : 'normal'}
        />
      </div>

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.3fr_1fr]">
        <Panel>
          <PanelHeader
            title="Booked pregnancies"
            hint="Gestation counted back from the estimated date, so a re-dated pregnancy reads correctly."
          />
          {ongoing.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : pregnancies.length === 0 ? (
            <div className="p-5"><EmptyState>Nothing booked.</EmptyState></div>
          ) : (
            <TableFrame minWidth={660}>
              <thead>
                <tr>
                  <Th>Patient</Th>
                  <Th>Gestation</Th>
                  <Th>Due</Th>
                  <Th>History</Th>
                  <Th>Visits</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {pregnancies.map((pregnancy) => {
                  const past = overdue.some((o) => o.id === pregnancy.id)
                  return (
                    <tr
                      key={pregnancy.id}
                      className={pregnancy.id === selected ? 'bg-accent/5' : ''}
                    >
                      <Td>
                        <Link
                          href={`/patients/${pregnancy.patient}`}
                          className="font-medium text-ink hover:text-accent"
                        >
                          {pregnancy.patient_name}
                        </Link>
                        <div className="text-[11px] text-ink-faint">
                          {pregnancy.hospital_number}
                        </div>
                      </Td>
                      <Td>
                        {pregnancy.gestation ? (
                          <span className="font-semibold tabular-nums">
                            {pregnancy.gestation.weeks}
                            <span className="text-ink-muted">+{pregnancy.gestation.days}</span>
                          </span>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </Td>
                      <Td>
                        <span className={past ? 'font-medium text-abnormal' : ''}>
                          {fullDate(pregnancy.estimated_delivery_date)}
                        </span>
                        <div className="text-[11px] text-ink-faint">
                          by {pregnancy.edd_basis_display.toLowerCase()}
                        </div>
                        {past && (
                          <div className="flex items-center gap-1 text-[11px] font-semibold text-abnormal">
                            <AlertIcon className="size-3" />
                            past the date
                          </div>
                        )}
                      </Td>
                      <Td className="text-ink-muted tabular-nums">
                        G{pregnancy.gravida} P{pregnancy.parity}
                        {pregnancy.previous_losses > 0 && `+${pregnancy.previous_losses}`}
                      </Td>
                      <Td className="text-right text-ink-muted">
                        {pregnancy.antenatal_visits.length}
                      </Td>
                      <Td>
                        <button
                          type="button"
                          onClick={() =>
                            setSelected(pregnancy.id === selected ? null : pregnancy.id)
                          }
                          className="text-[12px] font-medium text-accent hover:underline"
                        >
                          {pregnancy.id === selected ? 'Close' : 'Open'}
                        </button>
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <div className="grid gap-5">
          {current ? (
            <PregnancyPanel
              pregnancy={current}
              canRecord={can('maternity.record_antenatal_visit')}
              canDeliver={can('maternity.record_delivery')}
              canRevise={can('maternity.book_pregnancy')}
              run={run}
            />
          ) : (
            <Panel>
              <PanelHeader title="Antenatal record" />
              <div className="p-5">
                <EmptyState>Open a pregnancy to see its record.</EmptyState>
              </div>
            </Panel>
          )}

          {can('maternity.book_pregnancy') && facilityId && (
            <BookPanel facilityId={facilityId} run={run} />
          )}
        </div>
      </div>
    </PageShell>
  )
}

function PregnancyPanel({
  pregnancy, canRecord, canDeliver, canRevise, run,
}: {
  pregnancy: Pregnancy
  canRecord: boolean
  canDeliver: boolean
  canRevise: boolean
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const [tab, setTab] = useState<'record' | 'visit' | 'deliver' | 'redate'>('record')

  const tabs = [
    { key: 'record' as const, label: 'Record', show: true },
    { key: 'visit' as const, label: 'Antenatal visit', show: canRecord },
    { key: 'deliver' as const, label: 'Delivery', show: canDeliver },
    { key: 'redate' as const, label: 'Re-date', show: canRevise },
  ].filter((entry) => entry.show)

  return (
    <Panel>
      <PanelHeader
        title={pregnancy.patient_name}
        hint={
          pregnancy.gestation
            ? `${pregnancy.gestation.weeks}+${pregnancy.gestation.days} weeks · G${pregnancy.gravida} P${pregnancy.parity}`
            : `G${pregnancy.gravida} P${pregnancy.parity}`
        }
        action={<Badge tone="progress">{pregnancy.status_display}</Badge>}
      />
      <div className="flex gap-1 border-b border-border px-3 pt-3">
        {tabs.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={`rounded-t-md px-3 py-2 text-[12.5px] font-medium transition ${
              tab === entry.key
                ? 'bg-surface text-accent shadow-[inset_0_-2px_0_0_var(--color-accent)]'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="p-5">
        {tab === 'record' && (
          <div className="grid gap-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[12.5px]">
              <dt className="text-ink-muted">Estimated delivery</dt>
              <dd className="text-ink">
                {fullDate(pregnancy.estimated_delivery_date)}{' '}
                <span className="text-ink-muted">
                  ({pregnancy.edd_basis_display.toLowerCase()})
                </span>
              </dd>
              {pregnancy.edd_basis_note && (
                <>
                  <dt className="text-ink-muted">Basis</dt>
                  <dd className="text-ink">{pregnancy.edd_basis_note}</dd>
                </>
              )}
              {pregnancy.last_menstrual_period && (
                <>
                  <dt className="text-ink-muted">Last period</dt>
                  <dd className="text-ink">
                    {fullDate(pregnancy.last_menstrual_period)}
                  </dd>
                </>
              )}
              <dt className="text-ink-muted">Booked</dt>
              <dd className="text-ink">
                {fullDate(pregnancy.booked_at)} by {pregnancy.booked_by_name}
              </dd>
            </dl>

            {pregnancy.risk_factors && (
              <div className="rounded-lg border border-abnormal/30 bg-abnormal-muted px-3 py-2.5">
                <p className="text-[11px] font-medium tracking-[0.08em] text-abnormal uppercase">
                  Risk factors, as recorded
                </p>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-abnormal">
                  {pregnancy.risk_factors}
                </p>
                <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-muted">
                  Recorded by a clinician. This software does not score risk and does
                  not decide what these mean.
                </p>
              </div>
            )}

            {pregnancy.antenatal_visits.length === 0 ? (
              <EmptyState>No antenatal visits recorded.</EmptyState>
            ) : (
              <TableFrame minWidth={480}>
                <thead>
                  <tr>
                    <Th>#</Th>
                    <Th>Weeks</Th>
                    <Th>BP</Th>
                    <Th>Hb</Th>
                    <Th>Fundal</Th>
                    <Th>FH</Th>
                  </tr>
                </thead>
                <tbody>
                  {pregnancy.antenatal_visits.map((visit) => {
                    const high =
                      (visit.systolic_bp ?? 0) >= 140 || (visit.diastolic_bp ?? 0) >= 90
                    return (
                      <tr key={visit.id}>
                        <Td className="text-ink-muted">{visit.sequence}</Td>
                        <Td className="tabular-nums">{visit.gestation_weeks ?? '—'}</Td>
                        <Td className={high ? 'font-semibold text-critical' : ''}>
                          {visit.systolic_bp ? `${visit.systolic_bp}/${visit.diastolic_bp}` : '—'}
                        </Td>
                        <Td className="tabular-nums">{visit.haemoglobin ?? '—'}</Td>
                        <Td className="tabular-nums">{visit.fundal_height_cm ?? '—'}</Td>
                        <Td className="tabular-nums">{visit.fetal_heart_rate ?? '—'}</Td>
                      </tr>
                    )
                  })}
                </tbody>
              </TableFrame>
            )}
          </div>
        )}

        {tab === 'visit' && <VisitForm pregnancy={pregnancy} run={run} />}
        {tab === 'deliver' && <DeliveryForm pregnancy={pregnancy} run={run} />}
        {tab === 'redate' && <RedateForm pregnancy={pregnancy} run={run} />}
      </div>
    </Panel>
  )
}

function VisitForm({
  pregnancy, run,
}: {
  pregnancy: Pregnancy
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const record = useAntenatalVisit()
  const [form, setForm] = useState({
    weight_kg: '', systolic_bp: '', diastolic_bp: '', fundal_height_cm: '',
    fetal_heart_rate: '', presentation: '', urine_protein: '', urine_glucose: '',
    haemoglobin: '', notes: '', next_appointment: '',
  })

  const numeric = (value: string) => (value === '' ? null : Number(value))

  return (
    <div className="grid gap-4">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        The gestation is worked out from the estimated delivery date, so it does not
        need typing.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Weight (kg)">
          <Input
            type="number" step="0.1" min={0} value={form.weight_kg}
            onChange={(e) => setForm({ ...form, weight_kg: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Haemoglobin (g/dL)">
          <Input
            type="number" step="0.1" min={0} value={form.haemoglobin}
            onChange={(e) => setForm({ ...form, haemoglobin: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Systolic BP">
          <Input
            type="number" min={0} value={form.systolic_bp}
            onChange={(e) => setForm({ ...form, systolic_bp: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Diastolic BP">
          <Input
            type="number" min={0} value={form.diastolic_bp}
            onChange={(e) => setForm({ ...form, diastolic_bp: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Fundal height (cm)">
          <Input
            type="number" min={0} value={form.fundal_height_cm}
            onChange={(e) => setForm({ ...form, fundal_height_cm: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Fetal heart rate">
          <Input
            type="number" min={0} value={form.fetal_heart_rate}
            onChange={(e) => setForm({ ...form, fetal_heart_rate: e.target.value })}
            className="text-right"
          />
        </Field>
        <Field label="Presentation">
          <Input
            value={form.presentation} maxLength={40}
            onChange={(e) => setForm({ ...form, presentation: e.target.value })}
            placeholder="Cephalic"
          />
        </Field>
        <Field label="Urine protein">
          <Input
            value={form.urine_protein} maxLength={20}
            onChange={(e) => setForm({ ...form, urine_protein: e.target.value })}
            placeholder="nil"
          />
        </Field>
      </div>
      <Field label="Notes">
        <Textarea
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
      </Field>
      <Field label="Next appointment">
        <Input
          type="date" value={form.next_appointment}
          onChange={(e) => setForm({ ...form, next_appointment: e.target.value })}
        />
      </Field>
      <div>
        <Button
          disabled={record.isPending}
          onClick={async () => {
            const ok = await run(() =>
              record.mutateAsync({
                id: pregnancy.id,
                weight_kg: form.weight_kg || null,
                haemoglobin: form.haemoglobin || null,
                systolic_bp: numeric(form.systolic_bp),
                diastolic_bp: numeric(form.diastolic_bp),
                fundal_height_cm: numeric(form.fundal_height_cm),
                fetal_heart_rate: numeric(form.fetal_heart_rate),
                presentation: form.presentation,
                urine_protein: form.urine_protein,
                urine_glucose: form.urine_glucose,
                notes: form.notes,
                next_appointment: form.next_appointment || null,
              }),
            )
            if (ok) {
              setForm({
                weight_kg: '', systolic_bp: '', diastolic_bp: '',
                fundal_height_cm: '', fetal_heart_rate: '', presentation: '',
                urine_protein: '', urine_glucose: '', haemoglobin: '', notes: '',
                next_appointment: '',
              })
            }
          }}
          className="px-4 py-2.5"
        >
          {record.isPending ? 'Recording…' : 'Record the visit'}
        </Button>
      </div>
    </div>
  )
}

type BabyDraft = {
  given_name: string
  sex: string
  outcome: string
  birth_weight_grams: string
  apgar_one_minute: string
  apgar_five_minutes: string
  resuscitation: string
}

function DeliveryForm({
  pregnancy, run,
}: {
  pregnancy: Pregnancy
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const staff = useStaff()
  const deliver = useRecordDelivery()
  const [form, setForm] = useState({
    delivered_at: '', mode: 'svd', delivered_by: '', onset_of_labour: '',
    duration_of_labour_minutes: '', estimated_blood_loss_ml: '',
    perineal_tear: '', complications: '',
  })
  const [babies, setBabies] = useState<BabyDraft[]>([{
    given_name: 'Baby', sex: 'unknown', outcome: 'live',
    birth_weight_grams: '', apgar_one_minute: '', apgar_five_minutes: '',
    resuscitation: '',
  }])

  const ready = form.delivered_at !== '' && form.delivered_by !== ''

  return (
    <div className="grid gap-4">
      <p className="rounded-lg border border-accent/20 bg-accent/5 px-3 py-2.5 text-[12.5px] leading-relaxed text-ink">
        Each baby gets their own patient record, created now — not registered
        afterwards. A newborn who needs help needs a chart from the first minute.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Delivered at" required>
          <Input
            type="datetime-local" value={form.delivered_at}
            onChange={(e) => setForm({ ...form, delivered_at: e.target.value })}
          />
        </Field>
        <Field label="Mode" required>
          <Select
            value={form.mode}
            onChange={(e) => setForm({ ...form, mode: e.target.value })}
          >
            <option value="svd">Spontaneous vaginal delivery</option>
            <option value="assisted">Assisted vaginal delivery</option>
            <option value="lscs_elective">Caesarean section, elective</option>
            <option value="lscs_emergency">Caesarean section, emergency</option>
          </Select>
        </Field>
      </div>
      <Field label="Delivered by" required>
        <Select
          value={form.delivered_by}
          onChange={(e) => setForm({ ...form, delivered_by: e.target.value })}
        >
          <option value="">Choose…</option>
          {(staff.data ?? []).map((person) => (
            <option key={person.id} value={person.id}>{person.full_name}</option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Onset of labour">
          <Input
            value={form.onset_of_labour} maxLength={40}
            onChange={(e) => setForm({ ...form, onset_of_labour: e.target.value })}
            placeholder="Spontaneous"
          />
        </Field>
        <Field label="Duration (minutes)">
          <Input
            type="number" min={0} value={form.duration_of_labour_minutes}
            onChange={(e) =>
              setForm({ ...form, duration_of_labour_minutes: e.target.value })
            }
            className="text-right"
          />
        </Field>
        <Field label="Estimated blood loss (mL)">
          <Input
            type="number" min={0} value={form.estimated_blood_loss_ml}
            onChange={(e) =>
              setForm({ ...form, estimated_blood_loss_ml: e.target.value })
            }
            className="text-right"
          />
        </Field>
        <Field label="Perineal tear">
          <Input
            value={form.perineal_tear} maxLength={40}
            onChange={(e) => setForm({ ...form, perineal_tear: e.target.value })}
          />
        </Field>
      </div>
      <Field label="Complications">
        <Textarea
          value={form.complications}
          onChange={(e) => setForm({ ...form, complications: e.target.value })}
        />
      </Field>

      <div className="grid gap-3 border-t border-border pt-4">
        <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
          Babies
        </p>
        {babies.map((baby, index) => (
          <div
            key={index}
            className="rounded-lg border border-border bg-surface-sunken/40 p-3"
          >
            <p className="mb-2.5 text-[12px] font-semibold text-ink">
              Baby {index + 1}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Given name">
                <Input
                  value={baby.given_name} maxLength={100}
                  onChange={(e) => {
                    const next = [...babies]
                    next[index] = { ...baby, given_name: e.target.value }
                    setBabies(next)
                  }}
                />
              </Field>
              <Field label="Sex">
                <Select
                  value={baby.sex}
                  onChange={(e) => {
                    const next = [...babies]
                    next[index] = { ...baby, sex: e.target.value }
                    setBabies(next)
                  }}
                >
                  <option value="unknown">Unknown</option>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                </Select>
              </Field>
              <Field label="Outcome">
                <Select
                  value={baby.outcome}
                  onChange={(e) => {
                    const next = [...babies]
                    next[index] = { ...baby, outcome: e.target.value }
                    setBabies(next)
                  }}
                >
                  <option value="live">Live birth</option>
                  <option value="stillbirth_fresh">Fresh stillbirth</option>
                  <option value="stillbirth_macerated">Macerated stillbirth</option>
                </Select>
              </Field>
              <Field label="Birth weight (g)">
                <Input
                  type="number" min={0} value={baby.birth_weight_grams}
                  onChange={(e) => {
                    const next = [...babies]
                    next[index] = { ...baby, birth_weight_grams: e.target.value }
                    setBabies(next)
                  }}
                  className="text-right"
                />
              </Field>
              {baby.outcome === 'live' && (
                <>
                  <Field label="Apgar at 1 minute">
                    <Input
                      type="number" min={0} max={10} value={baby.apgar_one_minute}
                      onChange={(e) => {
                        const next = [...babies]
                        next[index] = { ...baby, apgar_one_minute: e.target.value }
                        setBabies(next)
                      }}
                      className="text-right"
                    />
                  </Field>
                  <Field label="Apgar at 5 minutes">
                    <Input
                      type="number" min={0} max={10} value={baby.apgar_five_minutes}
                      onChange={(e) => {
                        const next = [...babies]
                        next[index] = { ...baby, apgar_five_minutes: e.target.value }
                        setBabies(next)
                      }}
                      className="text-right"
                    />
                  </Field>
                </>
              )}
            </div>
            <div className="mt-3">
              <Field label="Resuscitation">
                <Input
                  value={baby.resuscitation} maxLength={255}
                  onChange={(e) => {
                    const next = [...babies]
                    next[index] = { ...baby, resuscitation: e.target.value }
                    setBabies(next)
                  }}
                  placeholder="Bag-mask for 30 seconds."
                />
              </Field>
            </div>
          </div>
        ))}
        <div>
          <Button
            variant="ghost"
            onClick={() =>
              setBabies([...babies, {
                given_name: `Baby ${babies.length + 1}`, sex: 'unknown',
                outcome: 'live', birth_weight_grams: '', apgar_one_minute: '',
                apgar_five_minutes: '', resuscitation: '',
              }])
            }
          >
            Another baby
          </Button>
        </div>
      </div>

      <div>
        <Button
          disabled={!ready || deliver.isPending}
          onClick={() =>
            run(() =>
              deliver.mutateAsync({
                id: pregnancy.id,
                delivered_at: new Date(form.delivered_at).toISOString(),
                mode: form.mode,
                delivered_by: Number(form.delivered_by),
                onset_of_labour: form.onset_of_labour,
                duration_of_labour_minutes:
                  form.duration_of_labour_minutes === ''
                    ? null : Number(form.duration_of_labour_minutes),
                estimated_blood_loss_ml:
                  form.estimated_blood_loss_ml === ''
                    ? null : Number(form.estimated_blood_loss_ml),
                perineal_tear: form.perineal_tear,
                complications: form.complications,
                babies: babies.map((baby) => ({
                  given_name: baby.given_name,
                  sex: baby.sex,
                  outcome: baby.outcome,
                  birth_weight_grams:
                    baby.birth_weight_grams === ''
                      ? null : Number(baby.birth_weight_grams),
                  apgar_one_minute:
                    baby.apgar_one_minute === '' ? null : Number(baby.apgar_one_minute),
                  apgar_five_minutes:
                    baby.apgar_five_minutes === ''
                      ? null : Number(baby.apgar_five_minutes),
                  resuscitation: baby.resuscitation,
                })),
              }),
            )
          }
          className="px-4 py-2.5"
        >
          {deliver.isPending ? 'Recording…' : 'Record the delivery'}
        </Button>
      </div>
    </div>
  )
}

function RedateForm({
  pregnancy, run,
}: {
  pregnancy: Pregnancy
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const revise = useReviseEdd()
  const [date, setDate] = useState(pregnancy.estimated_delivery_date)
  const [basis, setBasis] = useState('ultrasound')
  const [note, setNote] = useState('')

  return (
    <div className="grid gap-4">
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        Currently {fullDate(pregnancy.estimated_delivery_date)}, by{' '}
        {pregnancy.edd_basis_display.toLowerCase()}. A re-dated pregnancy with no
        explanation cannot be judged later, so the note is required.
      </p>
      <Field label="New estimated delivery date" required>
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </Field>
      <Field label="Based on" required>
        <Select value={basis} onChange={(e) => setBasis(e.target.value)}>
          <option value="ultrasound">Ultrasound dating scan</option>
          <option value="lmp">Last menstrual period</option>
          <option value="examination">Clinical examination</option>
          <option value="uncertain">Uncertain</option>
        </Select>
      </Field>
      <Field label="Which scan, at what gestation" required>
        <Input
          value={note} maxLength={255}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Dating scan at 12+3, crown-rump length 58 mm."
        />
      </Field>
      <div>
        <Button
          disabled={revise.isPending || !note.trim()}
          onClick={async () => {
            const ok = await run(() =>
              revise.mutateAsync({
                id: pregnancy.id, estimated_delivery_date: date, basis, note,
              }),
            )
            if (ok) setNote('')
          }}
        >
          Re-date the pregnancy
        </Button>
      </div>
    </div>
  )
}

function BookPanel({
  facilityId, run,
}: {
  facilityId: number
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const book = useBookPregnancy()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    patient: '', last_menstrual_period: '', edd_basis: 'lmp', edd_basis_note: '',
    gravida: '1', parity: '0', previous_losses: '0', risk_factors: '',
  })

  const ready = form.patient !== '' && form.last_menstrual_period !== ''
  const impossible =
    Number(form.parity) + Number(form.previous_losses) >= Number(form.gravida)

  return (
    <Panel>
      <PanelHeader title="Book a pregnancy" hint="The estimated date is calculated." />
      <div className="p-5">
        {!open ? (
          <Button variant="secondary" onClick={() => setOpen(true)}>New booking</Button>
        ) : (
          <div className="grid gap-4">
            <Field label="Patient" required hint="Their patient number.">
              <Input
                type="number" value={form.patient}
                onChange={(e) => setForm({ ...form, patient: e.target.value })}
              />
            </Field>
            <Field
              label="First day of the last menstrual period"
              required
              hint="The estimated delivery date is 280 days from this — Naegele's rule."
            >
              <Input
                type="date" value={form.last_menstrual_period}
                onChange={(e) =>
                  setForm({ ...form, last_menstrual_period: e.target.value })
                }
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Gravida" required>
                <Input
                  type="number" min={1} value={form.gravida}
                  onChange={(e) => setForm({ ...form, gravida: e.target.value })}
                  className="text-right"
                />
              </Field>
              <Field label="Parity" required>
                <Input
                  type="number" min={0} value={form.parity}
                  onChange={(e) => setForm({ ...form, parity: e.target.value })}
                  className="text-right"
                />
              </Field>
              <Field label="Losses">
                <Input
                  type="number" min={0} value={form.previous_losses}
                  onChange={(e) =>
                    setForm({ ...form, previous_losses: e.target.value })
                  }
                  className="text-right"
                />
              </Field>
            </div>
            {impossible && (
              <p className="flex items-start gap-2 text-[12px] font-medium text-critical">
                <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
                Gravida counts this pregnancy too, so it has to exceed the births
                plus losses.
              </p>
            )}
            <Field
              label="Risk factors"
              hint="As you assess them. This software does not score risk."
            >
              <Textarea
                value={form.risk_factors}
                onChange={(e) => setForm({ ...form, risk_factors: e.target.value })}
                placeholder="Previous caesarean section."
              />
            </Field>
            <div className="flex gap-2">
              <Button
                disabled={!ready || impossible || book.isPending}
                onClick={async () => {
                  const ok = await run(() =>
                    book.mutateAsync({
                      patient: Number(form.patient),
                      facility: facilityId,
                      last_menstrual_period: form.last_menstrual_period,
                      edd_basis: form.edd_basis,
                      edd_basis_note: form.edd_basis_note,
                      gravida: Number(form.gravida),
                      parity: Number(form.parity),
                      previous_losses: Number(form.previous_losses),
                      risk_factors: form.risk_factors,
                    }),
                  )
                  if (ok) setOpen(false)
                }}
              >
                {book.isPending ? 'Booking…' : 'Book it'}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
