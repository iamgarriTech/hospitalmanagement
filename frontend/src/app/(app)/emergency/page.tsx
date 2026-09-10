'use client'

import { useState } from 'react'
import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, StatTile,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type BoardRow,
  useCloseEpisode, useEmergencyBoard, useRegisterArrival, useSeedTriageScale,
  useTriage, useTriageScales, useUnidentified,
} from '@/lib/emergency'
import { timeOfDay, waitedFor } from '@/lib/workflow'

/**
 * The emergency board.
 *
 * Ordered by severity before arrival time — that is the whole difference
 * between this and a clinic queue. An untriaged patient sits at the very top,
 * because an unknown severity is the most urgent state on the board, not the
 * least: nobody has looked at them yet.
 *
 * A patient past their level's target time is marked as breaching. The
 * software reports it and does nothing about it; what a department should do
 * is a matter of its own policy, and inventing one here would be pretending
 * to clinical authority this software does not have.
 */
export default function EmergencyPage() {
  const { can, facility } = useAuth()
  const facilityId = facility?.id ?? null

  const board = useEmergencyBoard(facilityId)
  const scales = useTriageScales()
  const unidentified = useUnidentified(facilityId)
  const seed = useSeedTriageScale()
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(null)

  const rows = board.data ?? []
  const scale = (scales.data ?? []).find(
    (s) => s.is_active && s.facility === facilityId,
  )
  const untriaged = rows.filter((r) => r.level === null)
  const breaching = rows.filter((r) => r.breaching)

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

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Emergency
      </div>
      <PageHeading
        title="Emergency board"
        subtitle="Sickest first, then longest waiting. Nobody who has not been triaged waits behind somebody who has."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {!scale && !scales.isPending && (
        <div className="mt-4 rounded-lg border border-abnormal/30 bg-abnormal-muted p-4">
          <p className="text-[13px] leading-relaxed text-abnormal">
            <span className="font-semibold">No triage scale is configured.</span>{' '}
            Patients can be registered but not triaged, so the board cannot order
            itself.
          </p>
          {can('visits.add_triagescale') && facilityId && (
            <div className="mt-3">
              <Button
                variant="secondary"
                disabled={seed.isPending}
                onClick={() => run(() => seed.mutateAsync(facilityId))}
              >
                Create a starting four-level scale
              </Button>
              <p className="mt-2 text-[12px] leading-relaxed text-ink-muted">
                Four levels with default target times. <strong>They are not
                clinically approved</strong> — they are a starting point for your own
                clinicians to replace.
              </p>
            </div>
          )}
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Waiting" value={rows.length} />
        <StatTile
          label="Not yet triaged"
          value={untriaged.length}
          tone={untriaged.length ? 'critical' : 'normal'}
        />
        <StatTile
          label="Past their target time"
          value={breaching.length}
          tone={breaching.length ? 'abnormal' : 'normal'}
        />
      </div>

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1.5fr_1fr]">
        <Panel>
          <PanelHeader
            title="The board"
            hint="Refreshes every minute."
            action={<Badge tone="idle">{rows.length} waiting</Badge>}
          />
          {board.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : rows.length === 0 ? (
            <div className="p-5"><EmptyState>The department is empty.</EmptyState></div>
          ) : (
            <div className="grid gap-2.5 p-5">
              {rows.map((row) => (
                <BoardCard
                  key={row.episode.id}
                  row={row}
                  open={selected === row.episode.id}
                  onToggle={() =>
                    setSelected(selected === row.episode.id ? null : row.episode.id)
                  }
                  levels={scale?.levels ?? []}
                  canTriage={can('visits.triage_patient')}
                  canClose={can('visits.close_emergency_episode')}
                  run={run}
                />
              ))}
            </div>
          )}
        </Panel>

        <div className="grid gap-5">
          {can('visits.add_emergencyepisode') && facilityId && (
            <Arrival facilityId={facilityId} run={run} />
          )}

          {(unidentified.data ?? []).length > 0 && (
            <Panel>
              <PanelHeader
                title="Still unidentified"
                hint="A temporary identity nobody merges becomes a permanent duplicate."
                action={<Badge tone="abnormal">{unidentified.data!.length}</Badge>}
              />
              <div className="grid gap-2 p-5">
                {(unidentified.data ?? []).map((row) => (
                  <Link
                    key={row.id}
                    href={`/patients/${row.id}`}
                    className="block rounded-lg border border-border bg-surface-sunken/40 p-3 transition hover:border-accent/50"
                  >
                    <span className="text-[12.5px] font-semibold text-ink">
                      {row.name}
                    </span>
                    <p className="text-[11.5px] text-ink-faint">
                      {row.hospital_number} · registered{' '}
                      {timeOfDay(row.registered_at)}
                    </p>
                    <span className="mt-1 inline-block text-[12px] font-medium text-accent">
                      Merge once identified →
                    </span>
                  </Link>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </PageShell>
  )
}

function BoardCard({
  row, open, onToggle, levels, canTriage, canClose, run,
}: {
  row: BoardRow
  open: boolean
  onToggle: () => void
  levels: { id: number; rank: number; name: string; colour: string }[]
  canTriage: boolean
  canClose: boolean
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const triage = useTriage()
  const close = useCloseEpisode()
  const [mode, setMode] = useState<'triage' | 'close' | null>(null)
  const [level, setLevel] = useState('')
  const [observations, setObservations] = useState('')
  const [reason, setReason] = useState('')
  const [outcome, setOutcome] = useState('discharged')
  const [note, setNote] = useState('')

  const episode = row.episode
  const current = episode.current_triage
  const isRetriage = episode.triage_assessments.length > 0

  const tone =
    row.level === null ? 'critical'
      : row.rank === 1 ? 'critical'
        : row.rank === 2 ? 'abnormal'
          : row.rank === 3 ? 'progress' : 'normal'

  return (
    <div
      className={`rounded-lg border p-4 ${
        row.level === null
          ? 'border-critical/40 bg-critical/5'
          : row.breaching
            ? 'border-abnormal/40 bg-abnormal-muted/40'
            : 'border-border bg-surface-sunken/40'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-[13.5px] font-semibold text-ink">
            {episode.patient_name}
          </span>
          {episode.is_unidentified && (
            <span className="ml-2 text-[11px] font-medium text-abnormal">
              unidentified
            </span>
          )}
          <p className="mt-0.5 text-[11.5px] text-ink-faint">
            {episode.hospital_number} · {episode.arrival_mode_display} ·{' '}
            arrived {timeOfDay(episode.arrived_at)}
          </p>
        </div>
        <div className="text-right">
          <Badge tone={tone}>{row.level?.name ?? 'NOT TRIAGED'}</Badge>
          <p
            className={`mt-1 text-[11.5px] font-medium ${
              row.breaching ? 'text-critical' : 'text-ink-muted'
            }`}
          >
            {waitedFor(row.waited)}
            {row.breaching && ' · over target'}
          </p>
        </div>
      </div>

      <p className="mt-2 text-[12.5px] leading-relaxed text-ink">
        {episode.presenting_complaint}
      </p>
      {episode.circumstances && (
        <p className="mt-1 text-[12px] leading-relaxed text-ink-muted">
          {episode.circumstances}
        </p>
      )}

      {open && episode.triage_assessments.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="mb-1.5 text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Triage history
          </p>
          <ul className="grid gap-1">
            {episode.triage_assessments.map((a) => (
              <li key={a.id} className="text-[12px] text-ink-muted">
                <span className="font-medium text-ink">{a.sequence}. {a.level_name}</span>
                {' '}· {a.assessed_by_name} · {timeOfDay(a.assessed_at)}
                {a.reason_for_retriage && (
                  <span className="block pl-4 text-ink-faint">
                    {a.reason_for_retriage}
                  </span>
                )}
                {a.observations && (
                  <span className="block pl-4 text-ink-faint">{a.observations}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="text-[12px] font-medium text-accent hover:underline"
        >
          {open ? 'Hide history' : 'History'}
        </button>
        {canTriage && mode !== 'triage' && (
          <button
            type="button"
            onClick={() => { setMode('triage'); setLevel(''); setReason('') }}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            {isRetriage ? 'Re-triage' : 'Triage'}
          </button>
        )}
        {canClose && mode !== 'close' && (
          <button
            type="button"
            onClick={() => setMode('close')}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            Record the outcome
          </button>
        )}
      </div>

      {mode === 'triage' && (
        <div className="mt-3 grid gap-3 border-t border-border pt-3">
          {isRetriage && (
            <p className="text-[12px] leading-relaxed text-ink-muted">
              This appends a new assessment. The earlier one stays — a patient who
              went from green to red deteriorated, and the time that happened is the
              clinically interesting fact.
            </p>
          )}
          <Field label="Severity" required>
            <Select value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">Choose…</option>
              {levels.map((l) => (
                <option key={l.id} value={l.id}>{l.rank}. {l.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="Observations">
            <Input
              value={observations}
              onChange={(e) => setObservations(e.target.value)}
              placeholder="GCS 8, BP 90/50, pulse 120."
            />
          </Field>
          {isRetriage && (
            <Field label="Why the severity changed" required>
              <Input
                value={reason}
                maxLength={255}
                onChange={(e) => setReason(e.target.value)}
                placeholder="GCS fell to 6, airway at risk."
              />
            </Field>
          )}
          <div className="flex gap-2">
            <Button
              disabled={
                triage.isPending || level === '' || (isRetriage && !reason.trim())
              }
              onClick={async () => {
                const ok = await run(() =>
                  triage.mutateAsync({
                    id: episode.id, level: Number(level),
                    complaint: '', observations,
                    reason_for_retriage: isRetriage ? reason : '',
                  }),
                )
                if (ok) { setMode(null); setObservations(''); setReason('') }
              }}
            >
              Record it
            </Button>
            <Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button>
          </div>
        </div>
      )}

      {mode === 'close' && (
        <div className="mt-3 grid gap-3 border-t border-border pt-3">
          <p className="text-[12px] leading-relaxed text-ink-muted">
            An episode ends once. This cannot be changed afterwards from here.
          </p>
          <Field label="How it ended" required>
            <Select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="admitted">Admitted</option>
              <option value="discharged">Discharged</option>
              <option value="referred">Referred on</option>
              <option value="transferred">Transferred to another hospital</option>
              <option value="lwbs">Left without being seen</option>
              <option value="died">Died</option>
            </Select>
          </Field>
          <Field
            label="Note"
            required={outcome === 'lwbs' && current !== null}
            hint={
              outcome === 'lwbs' && current !== null
                ? 'Somebody assessed them as needing care and they went home instead.'
                : 'Optional.'
            }
          >
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button
              disabled={
                close.isPending ||
                (outcome === 'lwbs' && current !== null && !note.trim())
              }
              onClick={async () => {
                const ok = await run(() =>
                  close.mutateAsync({ id: episode.id, outcome, note }),
                )
                if (ok) { setMode(null); setNote('') }
              }}
            >
              Close the episode
            </Button>
            <Button variant="ghost" onClick={() => setMode(null)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Registering an arrival.
 *
 * Deliberately short. A nurse fills this in beside a moving trolley, and
 * every extra field is a reason to write it on paper instead. An unconscious
 * patient with no wallet is registered with no name at all — the record is
 * merged into their real one once somebody identifies them, and nothing
 * recorded under the temporary identity is lost.
 */
function Arrival({
  facilityId, run,
}: {
  facilityId: number
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const register = useRegisterArrival()
  const [complaint, setComplaint] = useState('')
  const [unidentified, setUnidentified] = useState(false)
  const [sex, setSex] = useState('unknown')
  const [age, setAge] = useState('')
  const [mode, setMode] = useState('walk_in')
  const [broughtBy, setBroughtBy] = useState('')
  const [circumstances, setCircumstances] = useState('')

  return (
    <Panel>
      <PanelHeader
        title="Register an arrival"
        hint="As few fields as it takes. The rest can wait."
      />
      <div className="grid gap-4 p-5">
        <Field label="Why they are here" required>
          <Input
            value={complaint}
            maxLength={255}
            onChange={(e) => setComplaint(e.target.value)}
            placeholder="Collapsed in the street."
          />
        </Field>
        <Field label="How they arrived" required>
          <Select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="walk_in">Walked in</option>
            <option value="ambulance">Ambulance</option>
            <option value="police">Police</option>
            <option value="referred">Referred by another clinician</option>
            <option value="transfer">Transferred from another hospital</option>
          </Select>
        </Field>

        <div>
          <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
            <input
              type="checkbox"
              checked={unidentified}
              onChange={(e) => setUnidentified(e.target.checked)}
              className="size-4 rounded border-border"
            />
            Nobody can say who they are
          </label>
          <p className="mt-1 pl-6.5 text-[12px] leading-relaxed text-ink-muted">
            Creates a record under a temporary identity so they can be treated now.
            Merge it into their real record once somebody identifies them — nothing
            recorded under the temporary one is lost.
          </p>
        </div>

        {unidentified ? (
          <>
            <Field label="Apparent sex">
              <Select value={sex} onChange={(e) => setSex(e.target.value)}>
                <option value="unknown">Unknown</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </Select>
            </Field>
            <Field
              label="Estimated age"
              hint="Good enough to calculate a dose from. Recorded as an estimate."
            >
              <Input
                type="number"
                min={0}
                max={130}
                value={age}
                onChange={(e) => setAge(e.target.value)}
                className="text-right"
              />
            </Field>
            <Field
              label="Anything that identifies them"
              hint="What they were wearing, where they were found. Often the only thing that lets a relative confirm it is them."
            >
              <Textarea
                value={circumstances}
                onChange={(e) => setCircumstances(e.target.value)}
                placeholder="Blue shirt, no wallet. Found by traders at the motor park around 06:20."
              />
            </Field>
          </>
        ) : (
          <p className="flex items-start gap-2 rounded-lg border border-border bg-surface-sunken/40 px-3 py-2.5 text-[12px] leading-relaxed text-ink-muted">
            <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
            For a patient you can identify, find them in{' '}
            <Link href="/patients" className="font-medium text-accent hover:underline">
              Patients
            </Link>{' '}
            and register the arrival from their record, so this attendance joins the
            one chart they already have.
          </p>
        )}

        <Field label="Brought in by">
          <Input
            value={broughtBy}
            maxLength={200}
            onChange={(e) => setBroughtBy(e.target.value)}
            placeholder="State ambulance 12"
          />
        </Field>

        <div>
          <Button
            disabled={register.isPending || !complaint.trim() || !unidentified}
            onClick={async () => {
              const ok = await run(() =>
                register.mutateAsync({
                  facility: facilityId,
                  presenting_complaint: complaint,
                  unidentified: true,
                  sex,
                  estimated_age_years: age === '' ? null : Number(age),
                  arrival_mode: mode,
                  brought_in_by: broughtBy,
                  circumstances,
                }),
              )
              if (ok) {
                setComplaint(''); setAge(''); setBroughtBy('')
                setCircumstances(''); setUnidentified(false)
              }
            }}
            className="px-4 py-2.5"
          >
            {register.isPending ? 'Registering…' : 'Register the arrival'}
          </Button>
        </div>
      </div>
    </Panel>
  )
}
