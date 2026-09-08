'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useFacilities } from '@/lib/config'
import {
  type ClaimLineRow,
  type ClaimRow,
  useAcknowledgeClaim,
  useAssembleClaim,
  useClaimable,
  useClaims,
  useInsuranceProviders,
  useRejectClaim,
  useResolveShortfall,
  useResubmitClaim,
  useSubmitClaim,
} from '@/lib/insurance'
import { dateAndTime, money } from '@/lib/workflow'

const CLAIM_TONES: Record<ClaimRow['status'], 'idle' | 'progress' | 'abnormal' | 'normal' | 'critical'> = {
  draft: 'idle',
  submitted: 'progress',
  acknowledged: 'progress',
  part_paid: 'abnormal',
  paid: 'normal',
  rejected: 'critical',
}

function firstOfMonth() {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10)
}

/**
 * Claims: what is being asked of each scheme, and what came back.
 *
 * Assembling shows a preview first, because a claim is a statement the hospital
 * makes to a provider and a billing officer should see it before it goes. The
 * transitions come from the server's `allowed_transitions`, so the screen
 * cannot offer a move the claim cannot make.
 */
export default function ClaimsPage() {
  const { can } = useAuth()
  const [status, setStatus] = useState('')
  const claims = useClaims(status ? { status } : {})
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const rows = claims.data ?? []
  const selected = rows.find((row) => row.id === selectedId) ?? null

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Insurance
      </div>
      <PageHeading
        title="Claims"
        subtitle="What each scheme has been asked for, and what it has answered."
        action={
          <Link
            href="/insurance"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Insurance desk
          </Link>
        }
      />

      {can('insurance.add_claimbatch') && <AssemblePanel />}

      <div className="mt-5 mb-5 max-w-xs">
        <Field label="Show">
          <Select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Every claim</option>
            <option value="draft">Drafts</option>
            <option value="submitted,acknowledged">With the provider</option>
            <option value="part_paid">Part paid</option>
            <option value="rejected">Rejected</option>
            <option value="paid">Settled</option>
          </Select>
        </Field>
      </div>

      {claims.isError && <ErrorNotice>Could not load the claims.</ErrorNotice>}
      {claims.isLoading && <LoadingNotice>Loading…</LoadingNotice>}

      <div className="space-y-5">
        <Panel>
          <PanelHeader title={`${rows.length} claim${rows.length === 1 ? '' : 's'}`} />
          {rows.length === 0 && !claims.isLoading ? (
            <div className="p-5">
              <EmptyState>
                Nothing here yet. Assemble one above from charges already raised.
              </EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={900}>
              <thead>
                <tr>
                  <Th>Claim</Th>
                  <Th>Provider</Th>
                  <Th>Period</Th>
                  <Th>Claimed</Th>
                  <Th>Paid</Th>
                  <Th>Outstanding</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <button
                        type="button"
                        onClick={() => setSelectedId(row.id)}
                        className="font-semibold text-ink hover:text-accent"
                      >
                        {row.claim_number}
                      </button>
                      {row.resubmits_number && (
                        <span className="mt-0.5 block text-[11px] text-ink-muted">
                          replaces {row.resubmits_number}
                        </span>
                      )}
                    </Td>
                    <Td className="text-ink">{row.provider_code}</Td>
                    <Td className="text-[12px] text-ink-muted">
                      {row.period_start} → {row.period_end}
                    </Td>
                    <Td className="font-medium text-ink">{money(row.claimed_total)}</Td>
                    <Td className="text-ink-muted">{money(row.paid_total)}</Td>
                    <Td
                      className={
                        Number(row.outstanding) > 0 ? 'font-medium text-abnormal' : 'text-normal'
                      }
                    >
                      {money(row.outstanding)}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Badge tone={CLAIM_TONES[row.status]}>{row.status_display}</Badge>
                        {row.is_overdue && <Badge tone="critical">Late</Badge>}
                      </div>
                      {row.days_outstanding !== null && row.status !== 'paid' && (
                        <span className="mt-0.5 block text-[11px] text-ink-muted">
                          {row.days_outstanding} days out
                        </span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        {selected && <ClaimDetail claim={selected} onClose={() => setSelectedId(null)} />}
      </div>
    </PageShell>
  )
}

function AssemblePanel() {
  const providers = useInsuranceProviders({ accepting: 'true' })
  const facilities = useFacilities()
  const assemble = useAssembleClaim()
  const [providerId, setProviderId] = useState<number | null>(null)
  const [facilityId, setFacilityId] = useState<number | null>(null)
  const [start, setStart] = useState(firstOfMonth())
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10))

  useEffect(() => {
    if (facilityId === null && facilities.data?.length) {
      setFacilityId(facilities.data[0].id)
    }
  }, [facilityId, facilities.data])

  const preview = useClaimable({
    provider: providerId,
    facility: facilityId,
    period_start: start,
    period_end: end,
  })

  return (
    <Panel>
      <PanelHeader
        title="Assemble a claim"
        hint="Built from charges already raised — nothing is retyped, and a charge already on a live claim is left off."
      />
      <div className="space-y-4 p-5">
        {assemble.error instanceof ApiError && (
          <ErrorNotice>
            {Object.values(assemble.error.fields).flat().join(' ') ||
              assemble.error.message}
          </ErrorNotice>
        )}
        {assemble.isSuccess && assemble.data && (
          <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            {assemble.data.claim_number} assembled with {assemble.data.lines.length}{' '}
            line{assemble.data.lines.length === 1 ? '' : 's'} for{' '}
            {money(assemble.data.claimed_total)}.
            {Boolean(assemble.data.skipped) && (
              <> {assemble.data.skipped} charge(s) were already on another live claim.</>
            )}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Provider" required>
            <Select
              value={providerId ?? ''}
              onChange={(event) =>
                setProviderId(event.target.value ? Number(event.target.value) : null)
              }
            >
              <option value="">Choose…</option>
              {providers.data?.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Facility" required>
            <Select
              value={facilityId ?? ''}
              onChange={(event) =>
                setFacilityId(event.target.value ? Number(event.target.value) : null)
              }
            >
              {facilities.data?.map((facility) => (
                <option key={facility.id} value={facility.id}>
                  {facility.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="From" required>
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="To" required>
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
        </div>

        {preview.data && (
          <div className="rounded-xl bg-surface-muted/60 p-4">
            <p className="text-[12.5px] font-semibold text-ink">
              {preview.data.lines.length} charge
              {preview.data.lines.length === 1 ? '' : 's'} ready — {money(preview.data.total)}
            </p>
            {preview.data.lines.length === 0 ? (
              <p className="mt-1.5 text-[11.5px] text-ink-muted">
                Nothing claimable in this period. Held charges are on the insurance
                desk.
              </p>
            ) : (
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto pr-1">
                {preview.data.lines.slice(0, 40).map((line) => (
                  <li key={line.id} className="text-[11.5px] text-ink-muted">
                    {line.service_date} · {line.patient_name} · {line.description} —{' '}
                    <span className="font-medium text-ink">{money(line.scheme_amount)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <Button
          disabled={
            providerId === null ||
            facilityId === null ||
            (preview.data?.lines.length ?? 0) === 0 ||
            assemble.isPending
          }
          onClick={() =>
            assemble.mutate({
              provider: providerId as number,
              facility: facilityId as number,
              period_start: start,
              period_end: end,
            })
          }
        >
          {assemble.isPending ? 'Assembling…' : 'Assemble draft claim'}
        </Button>
      </div>
    </Panel>
  )
}

function ClaimDetail({ claim, onClose }: { claim: ClaimRow; onClose: () => void }) {
  const { can } = useAuth()
  const submit = useSubmitClaim()
  const acknowledge = useAcknowledgeClaim()
  const reject = useRejectClaim()
  const resubmit = useResubmitClaim()
  const [reference, setReference] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const [lineReasons, setLineReasons] = useState<Record<string, string>>({})
  const [resubmitting, setResubmitting] = useState(false)
  const [correction, setCorrection] = useState('')

  const allowed = claim.allowed_transitions
  const anyError = [submit, acknowledge, reject, resubmit].find(
    (mutation) => mutation.error instanceof ApiError,
  )

  return (
    <Panel>
      <PanelHeader
        title={claim.claim_number}
        hint={
          <>
            {claim.provider_name} · {claim.period_start} → {claim.period_end}
            {claim.submitted_at && ` · sent ${dateAndTime(claim.submitted_at)}`}
            {claim.provider_reference && ` · their ref ${claim.provider_reference}`}
          </>
        }
        action={
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      />
      <div className="space-y-5 p-5">
        {anyError && (
          <ErrorNotice>
            {(() => {
              const error = anyError.error as ApiError
              return Object.values(error.fields).flat().join(' ') || error.message
            })()}
          </ErrorNotice>
        )}

        {claim.rejection_reason && (
          <div role="alert" className="rounded-lg border border-critical/40 bg-critical-muted px-4 py-3">
            <p className="text-[12.5px] font-bold text-critical">Rejected</p>
            <p className="mt-1 text-[12px] text-critical">{claim.rejection_reason}</p>
          </div>
        )}
        {claim.resubmission_reason && (
          <p className="rounded-md bg-surface-muted px-4 py-2.5 text-[12px] text-ink-muted">
            Resubmitted because: {claim.resubmission_reason}
          </p>
        )}

        <div className="flex flex-wrap items-end gap-3">
          {allowed.includes('submitted') && can('insurance.submit_claim') && (
            <>
              <Field
                label="Provider reference"
                hint="Their batch or upload reference, if they gave one."
              >
                <Input
                  value={reference}
                  onChange={(event) => setReference(event.target.value)}
                  placeholder="HYG-BATCH-77"
                />
              </Field>
              <Button
                disabled={submit.isPending}
                onClick={() =>
                  submit.mutate({ id: claim.id, provider_reference: reference })
                }
              >
                {submit.isPending ? 'Sending…' : 'Mark submitted'}
              </Button>
            </>
          )}
          {allowed.includes('acknowledged') && can('insurance.record_claim_outcome') && (
            <Button
              variant="secondary"
              disabled={acknowledge.isPending}
              onClick={() => acknowledge.mutate({ id: claim.id })}
            >
              Provider acknowledged
            </Button>
          )}
          {allowed.includes('rejected') && can('insurance.record_claim_outcome') && (
            <Button variant="danger" onClick={() => setRejecting((value) => !value)}>
              Record a rejection
            </Button>
          )}
          {claim.status === 'rejected' &&
            !claim.resubmits_number &&
            can('insurance.add_claimbatch') && (
              <Button onClick={() => setResubmitting((value) => !value)}>
                Correct and resubmit
              </Button>
            )}
        </div>

        {rejecting && (
          <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
            <Field
              label="What did the provider say?"
              hint="Applies to the whole claim unless you name individual lines below."
              required
            >
              <Textarea value={reason} onChange={(event) => setReason(event.target.value)} />
            </Field>
            <p className="text-[11.5px] leading-relaxed text-ink-faint">
              Naming a line rejects only that one. Lines you leave alone stay
              accepted, so a partial rejection does not throw away the half the
              provider agreed to pay.
            </p>
            <Button
              variant="danger"
              disabled={!reason.trim() || reject.isPending}
              onClick={() =>
                reject.mutate(
                  { id: claim.id, reason: reason.trim(), line_reasons: lineReasons },
                  { onSuccess: () => setRejecting(false) },
                )
              }
            >
              Record the rejection
            </Button>
          </div>
        )}

        {resubmitting && (
          <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
            <Field
              label="What was corrected?"
              hint="Recorded on the new claim. One resubmission per rejected claim — the charges move rather than duplicating."
              required
            >
              <Input
                value={correction}
                onChange={(event) => setCorrection(event.target.value)}
                placeholder="Policy numbers corrected."
              />
            </Field>
            <Button
              disabled={!correction.trim() || resubmit.isPending}
              onClick={() =>
                resubmit.mutate(
                  { id: claim.id, reason: correction.trim() },
                  { onSuccess: () => setResubmitting(false) },
                )
              }
            >
              Resubmit
            </Button>
          </div>
        )}

        <TableFrame minWidth={980}>
          <thead>
            <tr>
              <Th>Patient</Th>
              <Th>Service</Th>
              <Th>Date</Th>
              <Th>Claimed</Th>
              <Th>Paid</Th>
              <Th>Unsettled</Th>
              <Th>Status</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {claim.lines.map((line) => (
              <ClaimLine
                key={line.id}
                line={line}
                rejecting={rejecting}
                onLineReason={(value) =>
                  setLineReasons((current) => ({ ...current, [String(line.id)]: value }))
                }
              />
            ))}
          </tbody>
        </TableFrame>

        <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 border-t border-border pt-4 text-[13px] sm:max-w-sm sm:ml-auto">
          <dt className="text-ink-muted">Claimed</dt>
          <dd className="text-right text-ink">{money(claim.claimed_total)}</dd>
          <dt className="text-ink-muted">Paid</dt>
          <dd className="text-right text-ink">{money(claim.paid_total)}</dd>
          {Number(claim.written_off_total) > 0 && (
            <>
              <dt className="text-ink-muted">Written off</dt>
              <dd className="text-right text-ink-muted">{money(claim.written_off_total)}</dd>
            </>
          )}
          <dt className="border-t border-border pt-1.5 font-semibold text-ink">Outstanding</dt>
          <dd
            className={`border-t border-border pt-1.5 text-right text-[15px] font-bold ${
              Number(claim.outstanding) > 0 ? 'text-abnormal' : 'text-normal'
            }`}
          >
            {money(claim.outstanding)}
          </dd>
        </dl>
      </div>
    </Panel>
  )
}

function ClaimLine({
  line,
  rejecting,
  onLineReason,
}: {
  line: ClaimLineRow
  rejecting: boolean
  onLineReason: (reason: string) => void
}) {
  const { can } = useAuth()
  const resolve = useResolveShortfall()
  const [open, setOpen] = useState(false)
  const [writeOff, setWriteOff] = useState('')
  const [toPatient, setToPatient] = useState('')
  const [reason, setReason] = useState('')

  const unsettled = Number(line.unsettled)

  return (
    <>
      <tr className="border-t border-border">
        <Td>
          <span className="font-medium text-ink">{line.patient_name}</span>
          <span className="mt-0.5 block text-[11px] text-ink-muted">
            {line.policy_number}
          </span>
        </Td>
        <Td className="max-w-56">
          <span className="text-[12.5px] text-ink">{line.service_description}</span>
          {line.diagnosis_codes && (
            <span className="mt-0.5 block text-[11px] text-ink-muted">
              {line.diagnosis_codes}
            </span>
          )}
          {line.authorisation_reference && (
            <span className="mt-0.5 block text-[11px] text-ink-faint">
              auth {line.authorisation_reference}
            </span>
          )}
        </Td>
        <Td className="text-[12px] text-ink-muted">{line.service_date}</Td>
        <Td className="font-medium text-ink">{money(line.claimed_amount)}</Td>
        <Td className="text-ink-muted">{money(line.paid_amount)}</Td>
        <Td className={unsettled > 0 ? 'font-medium text-abnormal' : 'text-normal'}>
          {money(line.unsettled)}
        </Td>
        <Td>
          <Badge
            tone={
              line.status === 'rejected'
                ? 'critical'
                : line.status === 'accepted'
                  ? 'normal'
                  : 'idle'
            }
          >
            {line.status_display}
          </Badge>
          {line.rejection_reason && (
            <span className="mt-0.5 block text-[11px] text-critical">
              {line.rejection_reason}
            </span>
          )}
          {line.shortfall_reason && (
            <span className="mt-0.5 block text-[11px] text-ink-muted">
              {line.shortfall_reason}
            </span>
          )}
        </Td>
        <Td>
          {rejecting ? (
            <Input
              aria-label={`Rejection reason for ${line.service_description}`}
              placeholder="Reject this line…"
              onChange={(event) => onLineReason(event.target.value)}
              className="py-1.5 text-[11.5px]"
            />
          ) : unsettled > 0 && can('insurance.write_off_claim_shortfall') ? (
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              className="text-[11.5px] font-medium text-accent hover:underline"
            >
              Resolve
            </button>
          ) : null}
        </Td>
      </tr>
      {open && (
        <tr className="border-t border-border bg-surface-muted/40">
          <td colSpan={8} className="p-4">
            {resolve.error instanceof ApiError && (
              <ErrorNotice>
                {Object.values(resolve.error.fields).flat().join(' ') ||
                  resolve.error.message}
              </ErrorNotice>
            )}
            <p className="mb-3 text-[12px] text-ink-muted">
              {money(line.unsettled)} unsettled. It goes somewhere explicit — written
              off, or moved to the patient — and either way it says why.
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Write off">
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={writeOff}
                  onChange={(event) => setWriteOff(event.target.value)}
                />
              </Field>
              <Field label="Move to the patient" hint="Appears on their invoice.">
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  value={toPatient}
                  onChange={(event) => setToPatient(event.target.value)}
                />
              </Field>
              <Field label="Why" required>
                <Input value={reason} onChange={(event) => setReason(event.target.value)} />
              </Field>
            </div>
            <Button
              className="mt-3"
              disabled={
                !reason.trim() ||
                (!Number(writeOff) && !Number(toPatient)) ||
                resolve.isPending
              }
              onClick={() =>
                resolve.mutate(
                  {
                    id: line.id,
                    write_off: writeOff || '0',
                    move_to_patient: toPatient || '0',
                    reason: reason.trim(),
                  },
                  { onSuccess: () => setOpen(false) },
                )
              }
            >
              Resolve the shortfall
            </Button>
          </td>
        </tr>
      )}
    </>
  )
}
