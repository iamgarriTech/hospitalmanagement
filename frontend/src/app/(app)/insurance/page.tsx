'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { AlertIcon, BillingIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Field, Panel, PanelHeader, Select, StatTile, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useFacilities } from '@/lib/config'
import {
  type ChargeCoverageRow,
  type PreauthorisationRow,
  useAgeing,
  useDecidePreauthorisation,
  useHeldCoverage,
  useOutstandingPreauthorisations,
} from '@/lib/insurance'
import { dateAndTime, money, waitedFor } from '@/lib/workflow'

/**
 * The insurance desk.
 *
 * Three lists, and they are the three ways a hospital loses money to a scheme:
 * charges the scheme would pay for that nobody can claim yet, authorisations
 * nobody chased, and claims the provider has not settled. A held line that
 * dropped off every list is money the hospital never asks for.
 */
export default function InsuranceDeskPage() {
  const { can } = useAuth()
  const facilities = useFacilities()
  const [facilityId, setFacilityId] = useState<number | null>(null)

  useEffect(() => {
    if (facilityId === null && facilities.data?.length) {
      setFacilityId(facilities.data[0].id)
    }
  }, [facilityId, facilities.data])

  const held = useHeldCoverage()
  const authorisations = useOutstandingPreauthorisations()
  const ageing = useAgeing(facilityId)

  const heldRows = held.data ?? []
  const heldTotal = heldRows.reduce((sum, row) => sum + Number(row.scheme_amount), 0)
  const owed = (ageing.data ?? []).reduce((sum, row) => sum + Number(row.total), 0)
  const overdue = (ageing.data ?? []).reduce(
    (sum, row) =>
      sum + Number(row['31-60']) + Number(row['61-90']) + Number(row['over 90']),
    0,
  )

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Insurance
      </div>
      <PageHeading
        title="Insurance desk"
        subtitle="What the schemes owe, what is stuck, and what nobody has chased."
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/insurance/claims"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
            >
              Claims
            </Link>
            <Link
              href="/insurance/providers"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
            >
              Providers &amp; plans
            </Link>
          </div>
        }
      />

      <div className="mb-5 max-w-xs">
        <Field label="Facility">
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
      </div>

      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Owed by schemes"
          value={money(owed)}
          hint={`${(ageing.data ?? []).reduce((n, r) => n + r.claims, 0)} claims outstanding`}
          tone="accent"
          icon={<BillingIcon className="size-4" />}
        />
        <StatTile
          label="Past the agreed terms"
          value={money(overdue)}
          hint={overdue > 0 ? 'Worth a telephone call' : 'Everything within terms'}
          tone={overdue > 0 ? 'abnormal' : 'normal'}
        />
        <StatTile
          label="Held, unclaimable"
          value={money(heldTotal)}
          hint={`${heldRows.length} charge${heldRows.length === 1 ? '' : 's'} the scheme would pay for`}
          tone={heldRows.length ? 'abnormal' : 'normal'}
          icon={heldRows.length ? <AlertIcon className="size-4" /> : undefined}
        />
        <StatTile
          label="Authorisations waiting"
          value={authorisations.data?.length ?? 0}
          hint="Requests with no answer from the provider"
          tone={(authorisations.data?.length ?? 0) > 0 ? 'progress' : 'normal'}
        />
      </div>

      <div className="space-y-5">
        <Panel>
          <PanelHeader
            title="Owed by each scheme"
            hint="Banded past each provider's own undertaking to settle, so what is late is visible rather than only what is outstanding."
          />
          {ageing.isLoading && (
            <div className="p-5">
              <LoadingNotice>Working out the ageing…</LoadingNotice>
            </div>
          )}
          {(ageing.data ?? []).length === 0 && !ageing.isLoading ? (
            <div className="p-5">
              <EmptyState>No scheme owes this facility anything.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={820}>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>Within terms</Th>
                  <Th>31–60 days</Th>
                  <Th>61–90 days</Th>
                  <Th>Over 90 days</Th>
                  <Th>Total</Th>
                  <Th>Oldest</Th>
                </tr>
              </thead>
              <tbody>
                {ageing.data?.map((row) => (
                  <tr key={row.code} className="border-t border-border">
                    <Td>
                      <span className="font-semibold text-ink">{row.provider}</span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.claims} claim{row.claims === 1 ? '' : 's'}
                      </span>
                    </Td>
                    <Td className="text-ink-muted">{money(row.current)}</Td>
                    <Td className={Number(row['31-60']) > 0 ? 'text-abnormal' : 'text-ink-faint'}>
                      {money(row['31-60'])}
                    </Td>
                    <Td className={Number(row['61-90']) > 0 ? 'text-abnormal' : 'text-ink-faint'}>
                      {money(row['61-90'])}
                    </Td>
                    <Td className={Number(row['over 90']) > 0 ? 'font-semibold text-critical' : 'text-ink-faint'}>
                      {money(row['over 90'])}
                    </Td>
                    <Td className="font-semibold text-ink">{money(row.total)}</Td>
                    <Td>
                      <Badge tone={row.oldest_days > 60 ? 'critical' : row.oldest_days > 30 ? 'abnormal' : 'idle'}>
                        {row.oldest_days} days
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="Held charges"
            hint="The scheme would pay for these, and nobody can claim them yet. Care was never delayed for them — only the claim."
            action={
              heldRows.length > 0 ? (
                <Badge tone="abnormal">{money(heldTotal)}</Badge>
              ) : undefined
            }
          />
          {heldRows.length === 0 ? (
            <div className="p-5">
              <EmptyState>Nothing is held. Every covered charge is claimable.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={880}>
              <thead>
                <tr>
                  <Th>Patient</Th>
                  <Th>Charge</Th>
                  <Th>Scheme</Th>
                  <Th>Scheme would pay</Th>
                  <Th>Why it is held</Th>
                  <Th>Service date</Th>
                </tr>
              </thead>
              <tbody>
                {heldRows.map((row: ChargeCoverageRow) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <span className="font-medium text-ink">{row.patient_name}</span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.invoice_number}
                      </span>
                    </Td>
                    <Td className="max-w-56 text-[12px] text-ink-muted">
                      {row.description}
                    </Td>
                    <Td className="text-ink">
                      {row.provider_code}
                      <span className="mt-0.5 block text-[11px] text-ink-muted">
                        {row.policy_number}
                      </span>
                    </Td>
                    <Td className="font-medium text-ink">{money(row.scheme_amount)}</Td>
                    <Td>
                      <Badge tone="abnormal">{row.hold_display}</Badge>
                    </Td>
                    <Td className="text-[12px] text-ink-muted">{row.service_date}</Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="Authorisations waiting for an answer"
            hint="A request nobody followed up is a claim that gets rejected months later."
          />
          {(authorisations.data ?? []).length === 0 ? (
            <div className="p-5">
              <EmptyState>Nothing outstanding with any provider.</EmptyState>
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {authorisations.data?.map((row) => (
                <li key={row.id} className="p-5">
                  <Authorisation row={row} canDecide={can('insurance.request_preauthorisation')} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </PageShell>
  )
}

function Authorisation({
  row,
  canDecide,
}: {
  row: PreauthorisationRow
  canDecide: boolean
}) {
  const decide = useDecidePreauthorisation()
  const [open, setOpen] = useState(false)
  const [outcome, setOutcome] = useState<'approved' | 'declined'>('approved')
  const [reference, setReference] = useState('')
  const [validUntil, setValidUntil] = useState('')
  const [reason, setReason] = useState('')

  const fieldErrors = decide.error instanceof ApiError ? decide.error.fields : {}
  const waiting = Math.floor(
    (Date.now() - new Date(row.requested_at).getTime()) / 60000,
  )

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[13.5px] font-semibold text-ink">{row.patient_name}</p>
          <p className="mt-0.5 text-[11.5px] text-ink-muted">
            {row.provider_name} · {row.policy_number} · asked by{' '}
            {row.requested_by_name}, {dateAndTime(row.requested_at)}
          </p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink">
            {row.requested_for}
          </p>
          {row.service_names.length > 0 && (
            <p className="mt-1 text-[11.5px] text-ink-muted">
              For: {row.service_names.join(', ')}
            </p>
          )}
          {row.estimated_amount && (
            <p className="mt-1 text-[11.5px] text-ink-muted">
              Estimated {money(row.estimated_amount)}
            </p>
          )}
        </div>
        <Badge tone={waiting > 1440 ? 'critical' : 'progress'}>
          Waiting {waitedFor(waiting)}
        </Badge>
      </div>

      {canDecide && (
        <div className="mt-3">
          {!open ? (
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="text-[12px] font-semibold text-accent hover:underline"
            >
              Record the provider&apos;s answer →
            </button>
          ) : (
            <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
              {decide.error instanceof ApiError &&
                Object.keys(fieldErrors).length === 0 && (
                  <ErrorNotice>{decide.error.message}</ErrorNotice>
                )}
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Answer" required>
                  <Select
                    value={outcome}
                    onChange={(event) =>
                      setOutcome(event.target.value as 'approved' | 'declined')
                    }
                  >
                    <option value="approved">Approved</option>
                    <option value="declined">Declined</option>
                  </Select>
                </Field>
                {outcome === 'approved' ? (
                  <>
                    <Field
                      label="Authorisation reference"
                      hint="A claim cannot be made without it."
                      error={fieldErrors.reference}
                      required
                    >
                      <input
                        value={reference}
                        onChange={(event) => setReference(event.target.value)}
                        placeholder="HYG-AUTH-4410"
                        className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-ink"
                      />
                    </Field>
                    <Field label="Valid until">
                      <input
                        type="date"
                        value={validUntil}
                        onChange={(event) => setValidUntil(event.target.value)}
                        className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-ink"
                      />
                    </Field>
                  </>
                ) : (
                  <div className="sm:col-span-2">
                    <Field
                      label="Why was it declined?"
                      hint="Somebody has to explain this to the patient."
                      error={fieldErrors.decline_reason}
                      required
                    >
                      <Textarea
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </Field>
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  disabled={
                    decide.isPending ||
                    (outcome === 'approved' && !reference.trim()) ||
                    (outcome === 'declined' && !reason.trim())
                  }
                  onClick={() =>
                    decide.mutate(
                      {
                        id: row.id,
                        outcome,
                        reference: reference.trim(),
                        valid_until: validUntil || null,
                        decline_reason: reason.trim(),
                      },
                      { onSuccess: () => setOpen(false) },
                    )
                  }
                >
                  Record it
                </Button>
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
