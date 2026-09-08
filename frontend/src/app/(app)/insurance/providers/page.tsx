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
import { useServices } from '@/lib/billing'
import {
  type PlanRow,
  useDeleteCoverageRule,
  useInsurancePlans,
  useInsuranceProviders,
  useSaveCoverageRule,
  useSavePlan,
  useSaveProvider,
} from '@/lib/insurance'
import { money } from '@/lib/workflow'

const BASES = [
  { value: 'full', label: 'Scheme pays in full' },
  { value: 'percentage', label: 'Scheme pays a percentage' },
  { value: 'fixed_copay', label: 'Patient pays a fixed co-pay' },
  { value: 'excluded', label: 'Not covered' },
]

/**
 * Providers, plans and what each plan covers.
 *
 * Configuration, so it uses the shared list-and-form machinery. The one thing
 * worth saying on the screen itself is that editing a rule changes what
 * *future* charges cost and cannot change one already raised — a billing
 * officer who does not know that will be afraid to correct a mistake.
 */
export default function ProvidersPage() {
  const { can } = useAuth()
  const providers = useInsuranceProviders({ include_inactive: 'true' })
  const [providerId, setProviderId] = useState<number | null>(null)
  const plans = useInsurancePlans(
    providerId ? { provider: String(providerId), include_inactive: 'true' } : {},
  )
  const [planId, setPlanId] = useState<number | null>(null)

  useEffect(() => {
    if (providerId === null && providers.data?.length) {
      setProviderId(providers.data[0].id)
    }
  }, [providerId, providers.data])

  const plan = plans.data?.find((entry) => entry.id === planId) ?? null

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Insurance
      </div>
      <PageHeading
        title="Providers &amp; plans"
        subtitle="Who covers patients here, and what each plan actually pays for."
        action={
          <Link
            href="/insurance"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Insurance desk
          </Link>
        }
      />

      {providers.isError && <ErrorNotice>Could not load the providers.</ErrorNotice>}
      {providers.isLoading && <LoadingNotice>Loading…</LoadingNotice>}

      <div className="space-y-5">
        <Panel>
          <PanelHeader
            title={`${providers.data?.length ?? 0} provider${providers.data?.length === 1 ? '' : 's'}`}
            hint="A provider that has stopped paying can be switched off without deleting the history that still has to be chased."
          />
          {(providers.data?.length ?? 0) === 0 && !providers.isLoading ? (
            <div className="p-5">
              <EmptyState>None yet. Add the first below.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={880}>
              <thead>
                <tr>
                  <Th>Provider</Th>
                  <Th>Type</Th>
                  <Th>Claims go</Th>
                  <Th>Settles in</Th>
                  <Th>Plans</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {providers.data?.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <button
                        type="button"
                        onClick={() => {
                          setProviderId(row.id)
                          setPlanId(null)
                        }}
                        className="font-semibold text-ink hover:text-accent"
                      >
                        {row.name}
                      </button>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.code}
                        {row.contact_phone && ` · ${row.contact_phone}`}
                      </span>
                    </Td>
                    <Td className="text-ink-muted">{row.provider_type_display}</Td>
                    <Td className="max-w-56 text-[12px] text-ink-muted">
                      {row.claim_channel_display}
                      {row.claim_submission_note && (
                        <span className="mt-0.5 block text-[11px] text-ink-faint">
                          {row.claim_submission_note}
                        </span>
                      )}
                    </Td>
                    <Td className="text-ink">{row.settlement_days} days</Td>
                    <Td className="text-ink-muted">{row.plan_count}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1.5">
                        {!row.is_active && <Badge tone="idle">Inactive</Badge>}
                        {row.is_active && !row.is_accepting_claims && (
                          <Badge tone="abnormal">Not accepting claims</Badge>
                        )}
                        {row.is_active && row.is_accepting_claims && (
                          <Badge tone="normal">Accepting</Badge>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        {can('insurance.manage_coverage') && <AddProvider />}

        {providerId && (
          <Panel>
            <PanelHeader
              title="Plans"
              hint="Each plan states what it does with a service nobody wrote a rule for — both behaviours are real, so the plan decides rather than the code."
            />
            {(plans.data?.length ?? 0) === 0 ? (
              <div className="p-5">
                <EmptyState>This provider has no plans yet.</EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={900}>
                <thead>
                  <tr>
                    <Th>Plan</Th>
                    <Th>Unruled services</Th>
                    <Th>Default</Th>
                    <Th>Annual limit</Th>
                    <Th>Preauth above</Th>
                    <Th>Rules</Th>
                  </tr>
                </thead>
                <tbody>
                  {plans.data?.map((row) => (
                    <tr key={row.id} className="border-t border-border">
                      <Td>
                        <button
                          type="button"
                          onClick={() => setPlanId(row.id)}
                          className="font-semibold text-ink hover:text-accent"
                        >
                          {row.name}
                        </button>
                        <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                          {row.code}
                        </span>
                      </Td>
                      <Td className="max-w-48 text-[12px] text-ink-muted">
                        {row.unruled_display}
                      </Td>
                      <Td className="text-ink">{row.default_scheme_percent}%</Td>
                      <Td className="text-ink">
                        {row.annual_limit ? money(row.annual_limit) : '—'}
                      </Td>
                      <Td className="text-ink">
                        {row.requires_preauthorisation_above
                          ? money(row.requires_preauthorisation_above)
                          : '—'}
                      </Td>
                      <Td>
                        <Badge tone={row.rules.length ? 'accent' : 'idle'}>
                          {row.rules.length}
                        </Badge>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
          </Panel>
        )}

        {providerId && can('insurance.manage_coverage') && (
          <AddPlan providerId={providerId} />
        )}

        {plan && <RulesPanel plan={plan} />}
      </div>
    </PageShell>
  )
}

function AddProvider() {
  const save = useSaveProvider()
  const [form, setForm] = useState({
    name: '',
    code: '',
    provider_type: 'hmo',
    claim_channel: 'portal',
    claim_submission_note: '',
    contact_phone: '',
    contact_email: '',
    settlement_days: '30',
  })
  const fieldErrors = save.error instanceof ApiError ? save.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title="Add a provider"
        hint="How claims physically reach them matters: most Nigerian HMOs take a portal upload or an emailed spreadsheet."
      />
      <form
        className="space-y-4 p-5"
        onSubmit={(event) => {
          event.preventDefault()
          save.mutate(
            { ...form, settlement_days: Number(form.settlement_days) },
            {
              onSuccess: () =>
                setForm({
                  name: '',
                  code: '',
                  provider_type: 'hmo',
                  claim_channel: 'portal',
                  claim_submission_note: '',
                  contact_phone: '',
                  contact_email: '',
                  settlement_days: '30',
                }),
            },
          )
        }}
      >
        {save.error instanceof ApiError && Object.keys(fieldErrors).length === 0 && (
          <ErrorNotice>{save.error.message}</ErrorNotice>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Name" error={fieldErrors.name} required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Hygeia HMO"
            />
          </Field>
          <Field label="Code" error={fieldErrors.code} required>
            <Input
              value={form.code}
              onChange={(event) => setForm({ ...form, code: event.target.value })}
              placeholder="HYG"
            />
          </Field>
          <Field label="Type">
            <Select
              value={form.provider_type}
              onChange={(event) => setForm({ ...form, provider_type: event.target.value })}
            >
              <option value="hmo">HMO</option>
              <option value="insurer">Private insurer</option>
              <option value="government">Government scheme</option>
              <option value="corporate">Corporate account</option>
            </Select>
          </Field>
          <Field label="Claims go by">
            <Select
              value={form.claim_channel}
              onChange={(event) => setForm({ ...form, claim_channel: event.target.value })}
            >
              <option value="portal">Provider portal</option>
              <option value="email">Email</option>
              <option value="paper">Paper / hand delivered</option>
              <option value="api">API</option>
            </Select>
          </Field>
          <Field label="Telephone">
            <Input
              value={form.contact_phone}
              onChange={(event) => setForm({ ...form, contact_phone: event.target.value })}
            />
          </Field>
          <Field label="Email">
            <Input
              type="email"
              value={form.contact_email}
              onChange={(event) => setForm({ ...form, contact_email: event.target.value })}
            />
          </Field>
          <Field
            label="Settles in (days)"
            hint="What they undertake, so the ageing report can show what is late."
          >
            <Input
              type="number"
              min={1}
              max={365}
              value={form.settlement_days}
              onChange={(event) => setForm({ ...form, settlement_days: event.target.value })}
            />
          </Field>
        </div>
        <Field label="Where claims actually go" hint="A portal URL, an address, a person.">
          <Input
            value={form.claim_submission_note}
            onChange={(event) =>
              setForm({ ...form, claim_submission_note: event.target.value })
            }
          />
        </Field>
        <Button type="submit" disabled={!form.name.trim() || !form.code.trim() || save.isPending}>
          {save.isPending ? 'Adding…' : 'Add provider'}
        </Button>
      </form>
    </Panel>
  )
}

function AddPlan({ providerId }: { providerId: number }) {
  const save = useSavePlan()
  const [form, setForm] = useState({
    name: '',
    code: '',
    unruled_services: 'excluded',
    default_scheme_percent: '100.00',
    annual_limit: '',
    requires_preauthorisation_above: '',
  })
  const fieldErrors = save.error instanceof ApiError ? save.error.fields : {}

  return (
    <Panel>
      <PanelHeader title="Add a plan" />
      <form
        className="space-y-4 p-5"
        onSubmit={(event) => {
          event.preventDefault()
          save.mutate(
            {
              provider: providerId,
              ...form,
              annual_limit: form.annual_limit || null,
              requires_preauthorisation_above:
                form.requires_preauthorisation_above || null,
            },
            {
              onSuccess: () =>
                setForm({
                  name: '',
                  code: '',
                  unruled_services: 'excluded',
                  default_scheme_percent: '100.00',
                  annual_limit: '',
                  requires_preauthorisation_above: '',
                }),
            },
          )
        }}
      >
        {save.error instanceof ApiError && Object.keys(fieldErrors).length === 0 && (
          <ErrorNotice>{save.error.message}</ErrorNotice>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Name" error={fieldErrors.name} required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Gold"
            />
          </Field>
          <Field label="Code" error={fieldErrors.code} required>
            <Input
              value={form.code}
              onChange={(event) => setForm({ ...form, code: event.target.value })}
              placeholder="GOLD"
            />
          </Field>
          <Field
            label="A service with no rule"
            hint="Guessing covered bills the scheme for what it will reject; guessing excluded surprises the patient. The plan says which."
          >
            <Select
              value={form.unruled_services}
              onChange={(event) =>
                setForm({ ...form, unruled_services: event.target.value })
              }
            >
              <option value="excluded">Patient pays</option>
              <option value="covered">Covered at the default rate</option>
            </Select>
          </Field>
          <Field label="Default scheme percentage">
            <Input
              type="number"
              step="0.01"
              min="0"
              max="100"
              value={form.default_scheme_percent}
              onChange={(event) =>
                setForm({ ...form, default_scheme_percent: event.target.value })
              }
            />
          </Field>
          <Field label="Annual limit" hint="Blank for none.">
            <Input
              type="number"
              step="0.01"
              min="0"
              value={form.annual_limit}
              onChange={(event) => setForm({ ...form, annual_limit: event.target.value })}
            />
          </Field>
          <Field
            label="Preauthorisation above"
            hint="Any single charge above this needs an authorisation reference to claim."
          >
            <Input
              type="number"
              step="0.01"
              min="0"
              value={form.requires_preauthorisation_above}
              onChange={(event) =>
                setForm({ ...form, requires_preauthorisation_above: event.target.value })
              }
            />
          </Field>
        </div>
        <Button type="submit" disabled={!form.name.trim() || !form.code.trim() || save.isPending}>
          {save.isPending ? 'Adding…' : 'Add plan'}
        </Button>
      </form>
    </Panel>
  )
}

function RulesPanel({ plan }: { plan: PlanRow }) {
  const { can } = useAuth()
  const services = useServices()
  /* Derived from the services rather than fetched separately: it lists only
     categories that actually contain something, which is what you want when
     writing a rule — a rule about an empty category covers nothing. */
  const categories = Array.from(
    new Map(
      (services.data ?? []).map((service) => [
        service.category,
        { id: service.category, name: service.category_name },
      ]),
    ).values(),
  ).sort((a, b) => a.name.localeCompare(b.name))
  const save = useSaveCoverageRule()
  const remove = useDeleteCoverageRule()
  const [target, setTarget] = useState<'category' | 'service'>('category')
  const [targetId, setTargetId] = useState('')
  const [basis, setBasis] = useState('full')
  const [percent, setPercent] = useState('')
  const [copay, setCopay] = useState('')
  const [exclusion, setExclusion] = useState('')
  const [needsAuth, setNeedsAuth] = useState(false)

  const fieldErrors = save.error instanceof ApiError ? save.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title={`What ${plan.name} covers`}
        hint="A rule naming a service beats one naming its category, so an exception for one test survives a rule about the whole department."
      />
      <div className="space-y-5 p-5">
        <p className="rounded-md bg-surface-muted px-4 py-2.5 text-[12px] leading-relaxed text-ink-muted">
          Editing these changes what <strong>future</strong> charges cost. A charge
          already raised keeps the split it was given — correcting a mistake here
          cannot rewrite what a patient was told last month.
        </p>

        {plan.rules.length === 0 ? (
          <EmptyState>
            No rules. Every service falls to this plan&apos;s default:{' '}
            {plan.unruled_display.toLowerCase()}.
          </EmptyState>
        ) : (
          <TableFrame minWidth={780}>
            <thead>
              <tr>
                <Th>Applies to</Th>
                <Th>Treatment</Th>
                <Th>Patient pays</Th>
                <Th>Preauth</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {plan.rules.map((rule) => (
                <tr key={rule.id} className="border-t border-border">
                  <Td>
                    <span className="font-medium text-ink">
                      {rule.service_name ?? rule.category_name}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-ink-muted">
                      {rule.service_name ? 'this service' : 'whole category'}
                    </span>
                  </Td>
                  <Td className="text-ink-muted">
                    {rule.basis_display}
                    {rule.exclusion_reason && (
                      <span className="mt-0.5 block text-[11px] text-abnormal">
                        {rule.exclusion_reason}
                      </span>
                    )}
                  </Td>
                  <Td className="text-ink">
                    {rule.basis === 'percentage' && rule.scheme_percent
                      ? `${100 - Number(rule.scheme_percent)}%`
                      : rule.basis === 'fixed_copay' && rule.patient_copay
                        ? money(rule.patient_copay)
                        : rule.basis === 'excluded'
                          ? 'all of it'
                          : 'nothing'}
                  </Td>
                  <Td>
                    {rule.requires_preauthorisation ? (
                      <Badge tone="abnormal">Required</Badge>
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </Td>
                  <Td>
                    {can('insurance.manage_coverage') && (
                      <button
                        type="button"
                        onClick={() => remove.mutate(rule.id)}
                        className="text-[11.5px] font-medium text-ink-muted hover:text-critical"
                      >
                        Remove
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}

        {can('insurance.manage_coverage') && (
          <form
            className="space-y-3 border-t border-border pt-5"
            onSubmit={(event) => {
              event.preventDefault()
              save.mutate(
                {
                  plan: plan.id,
                  service: target === 'service' ? Number(targetId) : null,
                  category: target === 'category' ? Number(targetId) : null,
                  basis,
                  scheme_percent: basis === 'percentage' ? percent : null,
                  patient_copay: basis === 'fixed_copay' ? copay : null,
                  exclusion_reason: basis === 'excluded' ? exclusion : '',
                  requires_preauthorisation: needsAuth,
                },
                { onSuccess: () => setTargetId('') },
              )
            }}
          >
            <h3 className="text-[13px] font-semibold text-ink">Add a rule</h3>
            {save.error instanceof ApiError && (
              <ErrorNotice>
                {Object.values(fieldErrors).flat().join(' ') || save.error.message}
              </ErrorNotice>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Applies to" required>
                <Select
                  value={target}
                  onChange={(event) => {
                    setTarget(event.target.value as 'category' | 'service')
                    setTargetId('')
                  }}
                >
                  <option value="category">A whole category</option>
                  <option value="service">One service</option>
                </Select>
              </Field>
              <Field label={target === 'category' ? 'Category' : 'Service'} required>
                <Select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                  <option value="">Choose…</option>
                  {(target === 'category'
                    ? categories
                    : (services.data ?? []).map((service) => ({
                        id: service.id,
                        name: service.name,
                      }))
                  ).map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Treatment" required>
                <Select value={basis} onChange={(event) => setBasis(event.target.value)}>
                  {BASES.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {basis === 'percentage' && (
                <Field label="Scheme pays (%)" error={fieldErrors.scheme_percent} required>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    max="100"
                    value={percent}
                    onChange={(event) => setPercent(event.target.value)}
                  />
                </Field>
              )}
              {basis === 'fixed_copay' && (
                <Field label="Patient co-pay" error={fieldErrors.patient_copay} required>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    value={copay}
                    onChange={(event) => setCopay(event.target.value)}
                  />
                </Field>
              )}
            </div>
            {basis === 'excluded' && (
              <Field
                label="Why is it excluded?"
                hint="Printed on the invoice line. An unexplained amount is a dispute."
                error={fieldErrors.exclusion_reason}
                required
              >
                <Textarea
                  value={exclusion}
                  onChange={(event) => setExclusion(event.target.value)}
                  placeholder="Cosmetic procedures are not a scheme benefit."
                />
              </Field>
            )}
            <label className="flex items-center gap-2 text-[12.5px] font-medium text-ink">
              <input
                type="checkbox"
                checked={needsAuth}
                onChange={(event) => setNeedsAuth(event.target.checked)}
                className="size-4 rounded border-border"
              />
              Needs preauthorisation before it can be claimed
            </label>
            <Button
              type="submit"
              disabled={
                !targetId ||
                (basis === 'percentage' && !percent) ||
                (basis === 'fixed_copay' && !copay) ||
                (basis === 'excluded' && !exclusion.trim()) ||
                save.isPending
              }
            >
              {save.isPending ? 'Adding…' : 'Add rule'}
            </Button>
          </form>
        )}
      </div>
    </Panel>
  )
}
