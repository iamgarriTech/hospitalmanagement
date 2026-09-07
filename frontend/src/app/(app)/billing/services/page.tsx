'use client'

import { useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Input, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type Service, useServices, useSetServicePrice } from '@/lib/billing'
import { dateAndTime, money } from '@/lib/workflow'

/**
 * Services and their prices, per facility.
 *
 * A price change supersedes rather than edits: the previous amount stays on the
 * record and the change is audited, because a bill raised last week was raised
 * at last week's price and has to remain explicable.
 *
 * Prices are per facility on purpose — a branch clinic does not charge a
 * teaching hospital's rates.
 */
export default function ServicesPage() {
  const { can, facility } = useAuth()
  const services = useServices()
  const setPrice = useSetServicePrice()
  const [error, setError] = useState<string | null>(null)

  const rows = services.data ?? []
  const grouped = rows.reduce<Record<string, Service[]>>((groups, service) => {
    const key = service.category_name || 'Other'
    groups[key] = [...(groups[key] ?? []), service]
    return groups
  }, {})

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Services and prices"
        subtitle={
          facility
            ? `Prices shown for ${facility.name}. Each facility has its own.`
            : 'No facility selected.'
        }
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      {services.isLoading ? (
        <p role="status" className="py-10 text-[13px] text-ink-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <Panel className="mt-6 p-5">
          <EmptyState>No services configured.</EmptyState>
        </Panel>
      ) : (
        <div className="mt-6 grid gap-5">
          {Object.entries(grouped).map(([category, entries]) => (
            <Panel key={category}>
              <PanelHeader title={category} hint={`${entries.length} services`} />
              <TableFrame minWidth={720}>
                <thead>
                  <tr>
                    <Th>Service</Th>
                    <Th>Code</Th>
                    <Th className="text-right">Price here</Th>
                    <Th>Last changed</Th>
                    {can('billing.change_serviceprice') && <Th className="text-right">Change</Th>}
                  </tr>
                </thead>
                <tbody>
                  {entries.map((service) => {
                    const price = service.prices.find(
                      (entry) => entry.facility === facility?.id && entry.is_active,
                    )
                    return (
                      <tr key={service.id}>
                        <Td>
                          <span className="font-medium text-ink">{service.name}</span>
                          {!service.is_active && <Badge tone="idle">Inactive</Badge>}
                        </Td>
                        <Td className="font-mono text-[11.5px]">{service.code}</Td>
                        <Td className="text-right font-semibold">
                          {price ? (
                            money(price.amount)
                          ) : (
                            /* Said explicitly: no price means the charge cannot be
                               raised, which is a configuration gap, not a free service. */
                            <span className="text-[11.5px] font-medium text-abnormal">
                              Not priced here
                            </span>
                          )}
                        </Td>
                        <Td className="text-[11.5px] text-ink-muted">
                          {price ? dateAndTime(price.updated_at) : '—'}
                        </Td>
                        {can('billing.change_serviceprice') && (
                          <Td className="text-right">
                            <PriceEditor
                              serviceId={service.id}
                              current={price?.amount ?? ''}
                              facilityId={facility?.id ?? null}
                              setPrice={setPrice}
                              onError={setError}
                            />
                          </Td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </TableFrame>
            </Panel>
          ))}
        </div>
      )}
    </PageShell>
  )
}

function PriceEditor({
  serviceId,
  current,
  facilityId,
  setPrice,
  onError,
}: {
  serviceId: number
  current: string
  facilityId: number | null
  setPrice: ReturnType<typeof useSetServicePrice>
  onError: (message: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [amount, setAmount] = useState(current)

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => { setAmount(current); setOpen(true) }}>
        {current ? 'Change' : 'Set price'}
      </Button>
    )
  }

  return (
    <div className="flex items-center justify-end gap-1.5">
      <Input
        type="number"
        step="0.01"
        min="0"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        className="w-28 text-right"
        autoFocus
        aria-label="New price"
      />
      <Button
        disabled={!facilityId || amount === '' || setPrice.isPending}
        onClick={async () => {
          onError(null)
          try {
            await setPrice.mutateAsync({ id: serviceId, facility: facilityId!, amount })
            setOpen(false)
          } catch (caught) {
            onError(caught instanceof ApiError ? caught.message : 'Could not change the price.')
          }
        }}
      >
        Save
      </Button>
      <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
    </div>
  )
}
