'use client'

import { useState } from 'react'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select, StatTile,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useDepartments } from '@/lib/config'
import {
  type Referral, type ReferralLetter,
  useAcceptReferral, useCancelReferral, useCreateReferral, useReferralLetter,
  useReferralOutcome, useReferrals, useSendReferral,
} from '@/lib/referrals'
import { dateAndTime, fullDate } from '@/lib/workflow'

/**
 * Referrals, in and out.
 *
 * Two lists side by side, because a clinician has two relationships with a
 * referral: the ones they sent and are waiting on, and the ones sent to them
 * that somebody is waiting on. A single list sorted by date buries whichever
 * one matters today.
 *
 * The letter is generated on demand rather than stored, so a reprint is
 * identical to the original by construction — and every print, including the
 * first, is logged.
 */
export default function ReferralsPage() {
  const { can } = useAuth()
  const mine = useReferrals('?open=true')
  const toMe = useReferrals('?to_me=true')
  const closed = useReferrals('?status=seen,declined')
  const [error, setError] = useState<string | null>(null)
  const [letter, setLetter] = useState<ReferralLetter | null>(null)

  const outbound = (mine.data ?? []).filter((r) => r.status !== 'draft')
  const drafts = (mine.data ?? []).filter((r) => r.status === 'draft')
  const inbound = (toMe.data ?? []).filter((r) => r.is_open)

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
        Referrals
      </div>
      <PageHeading
        title="Referrals"
        subtitle="A referral asks a question. One that does not is a transfer of responsibility."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Waiting on somebody else" value={outbound.length} />
        <StatTile
          label="Waiting on you"
          value={inbound.length}
          tone={inbound.length ? 'abnormal' : 'normal'}
        />
        <StatTile label="Drafts" value={drafts.length} tone={drafts.length ? 'progress' : 'normal'} />
      </div>

      {letter && (
        <LetterPanel letter={letter} onClose={() => setLetter(null)} />
      )}

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
        <div className="grid gap-5">
          <Panel>
            <PanelHeader
              title="Sent to you"
              hint="Accept it, then record what you found."
            />
            {toMe.isPending ? (
              <div className="p-5"><LoadingNotice /></div>
            ) : inbound.length === 0 ? (
              <div className="p-5"><EmptyState>Nothing waiting on you.</EmptyState></div>
            ) : (
              <div className="grid gap-3 p-5">
                {inbound.map((referral) => (
                  <InboundCard
                    key={referral.id}
                    referral={referral}
                    canRespond={can('clinical.record_referral_outcome')}
                    onLetter={setLetter}
                    run={run}
                  />
                ))}
              </div>
            )}
          </Panel>

          {can('clinical.make_referral') && <NewReferral run={run} />}
        </div>

        <div className="grid gap-5">
          <Panel>
            <PanelHeader title="You are waiting on" hint="Sent, and not yet answered." />
            {mine.isPending ? (
              <div className="p-5"><LoadingNotice /></div>
            ) : outbound.length === 0 && drafts.length === 0 ? (
              <div className="p-5"><EmptyState>Nothing outstanding.</EmptyState></div>
            ) : (
              <div className="grid gap-3 p-5">
                {[...drafts, ...outbound].map((referral) => (
                  <OutboundCard
                    key={referral.id}
                    referral={referral}
                    canSend={can('clinical.make_referral')}
                    onLetter={setLetter}
                    run={run}
                  />
                ))}
              </div>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="Closed" hint="What came back." />
            {(closed.data ?? []).length === 0 ? (
              <div className="p-5"><EmptyState>Nothing closed yet.</EmptyState></div>
            ) : (
              <div className="grid gap-3 p-5">
                {(closed.data ?? []).slice(0, 10).map((referral) => (
                  <div
                    key={referral.id}
                    className="rounded-lg border border-border bg-surface-sunken/40 p-3"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[12.5px] font-semibold text-ink">
                        {referral.patient_name}
                      </span>
                      <Badge tone={referral.status === 'seen' ? 'normal' : 'abnormal'}>
                        {referral.status_display}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-[11.5px] text-ink-faint">
                      {referral.reference} → {referral.destination}
                    </p>
                    {referral.outcome && (
                      <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
                        {referral.outcome}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </PageShell>
  )
}

function urgencyTone(urgency: Referral['urgency']) {
  return urgency === 'two_week' ? 'critical' : urgency === 'urgent' ? 'abnormal' : 'idle'
}

function InboundCard({
  referral, canRespond, onLetter, run,
}: {
  referral: Referral
  canRespond: boolean
  onLetter: (letter: ReferralLetter) => void
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const accept = useAcceptReferral()
  const outcome = useReferralOutcome()
  const letter = useReferralLetter()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [declined, setDeclined] = useState(false)

  return (
    <div className="rounded-lg border border-border bg-surface-sunken/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-[13px] font-semibold text-ink">
            {referral.patient_name}
          </span>
          <p className="text-[11.5px] text-ink-faint">
            {referral.hospital_number} · from {referral.referred_by_name} ·{' '}
            {referral.reference}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Badge tone={urgencyTone(referral.urgency)}>{referral.urgency_display}</Badge>
          <Badge tone="progress">{referral.status_display}</Badge>
        </div>
      </div>

      <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
        {referral.reason}
      </p>
      <p className="mt-2 rounded-md border border-accent/20 bg-accent/5 p-2.5 text-[12.5px] leading-relaxed text-ink">
        <span className="font-medium">Asked:</span> {referral.clinical_question}
      </p>
      {referral.what_was_sent && (
        <p className="mt-1.5 text-[12px] text-ink-faint">
          Sent with it: {referral.what_was_sent}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={async () => {
            const result = await letter.mutateAsync(referral.id)
            onLetter(result)
          }}
          className="text-[12px] font-medium text-accent hover:underline"
        >
          Read the letter
        </button>
        {canRespond && referral.status === 'sent' && (
          <button
            type="button"
            onClick={() => run(() => accept.mutateAsync({ id: referral.id }))}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            Accept
          </button>
        )}
        {canRespond && !open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            Record what you found
          </button>
        )}
      </div>

      {open && (
        <div className="mt-3 grid gap-3 border-t border-border pt-3">
          <Field
            label="What came back"
            required
            hint="The referring clinician sees this. A closed referral with no outcome tells them nothing about their patient."
          >
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Seen in clinic. Gastroscopy booked for Thursday; no red flags."
            />
          </Field>
          <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
            <input
              type="checkbox"
              checked={declined}
              onChange={(e) => setDeclined(e.target.checked)}
              className="size-4 rounded border-border"
            />
            Declining rather than seeing them
          </label>
          <div className="flex gap-2">
            <Button
              disabled={outcome.isPending || !text.trim()}
              onClick={async () => {
                const ok = await run(() =>
                  outcome.mutateAsync({ id: referral.id, outcome: text, declined }),
                )
                if (ok) { setOpen(false); setText('') }
              }}
            >
              Record it
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function OutboundCard({
  referral, canSend, onLetter, run,
}: {
  referral: Referral
  canSend: boolean
  onLetter: (letter: ReferralLetter) => void
  run: (a: () => Promise<unknown>) => Promise<boolean>
}) {
  const send = useSendReferral()
  const cancel = useCancelReferral()
  const letter = useReferralLetter()
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')

  return (
    <div className="rounded-lg border border-border bg-surface-sunken/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-[13px] font-semibold text-ink">
            {referral.patient_name}
          </span>
          <p className="text-[11.5px] text-ink-faint">
            {referral.reference} → {referral.destination}
            {referral.sent_at && ` · sent ${fullDate(referral.sent_at)}`}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Badge tone={urgencyTone(referral.urgency)}>{referral.urgency_display}</Badge>
          <Badge tone={referral.status === 'draft' ? 'idle' : 'progress'}>
            {referral.status_display}
          </Badge>
        </div>
      </div>

      <p className="mt-2 text-[12.5px] leading-relaxed text-ink-muted">
        {referral.clinical_question}
      </p>
      {referral.print_count > 0 && (
        <p className="mt-1 text-[11px] text-ink-faint">
          Printed {referral.print_count}{' '}
          {referral.print_count === 1 ? 'time' : 'times'}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={async () => {
            const result = await letter.mutateAsync(referral.id)
            onLetter(result)
          }}
          className="text-[12px] font-medium text-accent hover:underline"
        >
          {referral.print_count > 0 ? 'Reprint the letter' : 'Print the letter'}
        </button>
        {canSend && referral.status === 'draft' && (
          <button
            type="button"
            onClick={() => run(() => send.mutateAsync({ id: referral.id }))}
            className="text-[12px] font-medium text-accent hover:underline"
          >
            Send it
          </button>
        )}
        {canSend && referral.is_open && !cancelling && (
          <button
            type="button"
            onClick={() => setCancelling(true)}
            className="text-[12px] font-medium text-ink-muted hover:text-critical"
          >
            Cancel
          </button>
        )}
      </div>

      {cancelling && (
        <div className="mt-3 grid gap-2 border-t border-border pt-3">
          <Input
            value={reason}
            maxLength={255}
            placeholder="Why it is being cancelled"
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              disabled={cancel.isPending || !reason.trim()}
              onClick={async () => {
                const ok = await run(() =>
                  cancel.mutateAsync({ id: referral.id, reason }),
                )
                if (ok) setCancelling(false)
              }}
            >
              Cancel the referral
            </Button>
            <Button variant="ghost" onClick={() => setCancelling(false)}>Keep it</Button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * The letter, as it prints.
 *
 * Rendered from the fields the server returned rather than from anything held
 * locally, which is what makes a reprint identical to the original: there is
 * no second copy to drift.
 */
function LetterPanel({
  letter, onClose,
}: {
  letter: ReferralLetter
  onClose: () => void
}) {
  const L = letter.letter
  return (
    <Panel className="mt-6">
      <PanelHeader
        title={letter.is_reprint ? 'Referral letter (reprint)' : 'Referral letter'}
        hint={`Print ${letter.print_count}. Every print is logged.`}
        action={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => window.print()}>Print</Button>
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        }
      />
      <div className="grid gap-4 p-6 text-[13px] leading-relaxed">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-border pb-3">
          <div>
            <p className="font-semibold text-ink">{L.from.facility}</p>
            {L.from.department && (
              <p className="text-ink-muted">{L.from.department}</p>
            )}
            <p className="text-ink-muted">{L.from.clinician}</p>
          </div>
          <div className="text-right">
            <p className="font-semibold text-ink">{L.reference}</p>
            <p className="text-ink-muted">{fullDate(L.written_on)}</p>
            <p className="font-medium text-accent">{L.urgency}</p>
          </div>
        </div>

        <div>
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            To
          </p>
          <p className="text-ink">{L.to.name}</p>
          {L.to.address && (
            <p className="whitespace-pre-line text-ink-muted">{L.to.address}</p>
          )}
        </div>

        <div className="rounded-lg border border-border bg-surface-sunken/40 p-4">
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Regarding
          </p>
          <p className="font-semibold text-ink">{L.patient.name}</p>
          <p className="text-ink-muted">
            {L.patient.hospital_number}
            {L.patient.age_years !== null && ` · ${L.patient.age_years} years`}
            {' · '}{L.patient.sex}
            {L.patient.date_of_birth && ` · born ${fullDate(L.patient.date_of_birth)}`}
          </p>
          {L.patient.phone && (
            <p className="text-ink-muted">{L.patient.phone}</p>
          )}
        </div>

        <div>
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            Reason for referral
          </p>
          <p className="whitespace-pre-line text-ink">{L.reason}</p>
        </div>

        <div>
          <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
            What I am asking
          </p>
          <p className="whitespace-pre-line text-ink">{L.clinical_question}</p>
        </div>

        {L.what_was_sent && (
          <div>
            <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
              Enclosed
            </p>
            <p className="whitespace-pre-line text-ink">{L.what_was_sent}</p>
          </div>
        )}

        {L.outcome && (
          <div className="border-t border-border pt-3">
            <p className="text-[11px] font-medium tracking-[0.08em] text-ink-muted uppercase">
              Outcome
            </p>
            <p className="whitespace-pre-line text-ink">{L.outcome}</p>
          </div>
        )}
      </div>
    </Panel>
  )
}

function NewReferral({ run }: { run: (a: () => Promise<unknown>) => Promise<boolean> }) {
  const departments = useDepartments()
  const create = useCreateReferral()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    kind: 'internal' as 'internal' | 'external',
    visit: '', to_department: '', to_organisation: '', to_external_clinician: '',
    to_address: '', reason: '', clinical_question: '', what_was_sent: '',
    urgency: 'routine',
  })

  const ready =
    form.visit !== '' &&
    form.reason.trim() !== '' &&
    form.clinical_question.trim() !== '' &&
    (form.kind === 'internal' ? form.to_department !== '' : form.to_organisation.trim() !== '')

  return (
    <Panel>
      <PanelHeader title="Refer a patient" hint="Say what you are asking, not just why." />
      <div className="p-5">
        {!open ? (
          <Button variant="secondary" onClick={() => setOpen(true)}>New referral</Button>
        ) : (
          <div className="grid gap-4">
            <Field
              label="Attendance"
              required
              hint="The visit this comes out of. Find it in the queue or on the patient's record."
            >
              <Input
                type="number"
                value={form.visit}
                onChange={(e) => setForm({ ...form, visit: e.target.value })}
                placeholder="Visit number"
              />
            </Field>
            <Field label="Where to" required>
              <Select
                value={form.kind}
                onChange={(e) =>
                  setForm({ ...form, kind: e.target.value as 'internal' })
                }
              >
                <option value="internal">A department in this hospital group</option>
                <option value="external">Another organisation</option>
              </Select>
            </Field>
            {form.kind === 'internal' ? (
              <Field label="Department" required>
                <Select
                  value={form.to_department}
                  onChange={(e) =>
                    setForm({ ...form, to_department: e.target.value })
                  }
                >
                  <option value="">Choose a department…</option>
                  {(departments.data ?? []).map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <>
                <Field label="Organisation" required>
                  <Input
                    value={form.to_organisation}
                    maxLength={200}
                    onChange={(e) =>
                      setForm({ ...form, to_organisation: e.target.value })
                    }
                  />
                </Field>
                <Field label="Named clinician">
                  <Input
                    value={form.to_external_clinician}
                    maxLength={200}
                    onChange={(e) =>
                      setForm({ ...form, to_external_clinician: e.target.value })
                    }
                  />
                </Field>
                <Field label="Address">
                  <Textarea
                    value={form.to_address}
                    onChange={(e) => setForm({ ...form, to_address: e.target.value })}
                  />
                </Field>
              </>
            )}
            <Field label="Urgency" required>
              <Select
                value={form.urgency}
                onChange={(e) => setForm({ ...form, urgency: e.target.value })}
              >
                <option value="routine">Routine</option>
                <option value="urgent">Urgent</option>
                <option value="two_week">Urgent, suspected cancer</option>
              </Select>
            </Field>
            <Field label="Why you are referring" required>
              <Textarea
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                placeholder="Persistent epigastric pain, not settling on a proton pump inhibitor."
              />
            </Field>
            <Field
              label="What you are asking"
              required
              hint="A referral without a question is a transfer of responsibility, and the person receiving it has no way to know what you want."
            >
              <Textarea
                value={form.clinical_question}
                onChange={(e) =>
                  setForm({ ...form, clinical_question: e.target.value })
                }
                placeholder="Does this warrant endoscopy, and can you see him this week?"
              />
            </Field>
            <Field label="What you are sending with it">
              <Textarea
                value={form.what_was_sent}
                onChange={(e) => setForm({ ...form, what_was_sent: e.target.value })}
                placeholder="FBC, LFTs, abdominal ultrasound report."
              />
            </Field>
            <div className="flex gap-2">
              <Button
                disabled={!ready || create.isPending}
                onClick={async () => {
                  const ok = await run(() =>
                    create.mutateAsync({
                      kind: form.kind,
                      visit: Number(form.visit),
                      to_department:
                        form.kind === 'internal' ? Number(form.to_department) : null,
                      to_organisation: form.to_organisation,
                      to_external_clinician: form.to_external_clinician,
                      to_address: form.to_address,
                      reason: form.reason,
                      clinical_question: form.clinical_question,
                      what_was_sent: form.what_was_sent,
                      urgency: form.urgency,
                    }),
                  )
                  if (ok) setOpen(false)
                }}
              >
                {create.isPending ? 'Saving…' : 'Save as draft'}
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
