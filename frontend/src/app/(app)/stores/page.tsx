'use client'

import Link from 'next/link'
import { AlertIcon } from '@/components/icons'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, EmptyState, Panel, PanelHeader, StatTile } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { useStockAlerts, useStores } from '@/lib/inventory'
import { fullDate } from '@/lib/workflow'

/**
 * What a storekeeper looks at first thing in the morning.
 *
 * Two lists, and they answer different questions. Low stock is "what do I
 * order today". Expiring is "what do I move or write off before it becomes
 * waste". Neither is a count of rows — a store below its level with nothing
 * expiring needs a purchase order, and a store full of stock expiring next
 * week needs somebody walking the shelves.
 *
 * Expired stock is shown separately from expiring, because they need opposite
 * actions: expiring stock should be used first, expired stock must not be used
 * at all.
 */
export default function StoresPage() {
  const { can } = useAuth()
  const stores = useStores()
  const alerts = useStockAlerts()

  const low = alerts.data?.low ?? []
  const expiring = (alerts.data?.expiring ?? []).filter((row) => !row.is_expired)
  const expired = (alerts.data?.expiring ?? []).filter((row) => row.is_expired)

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Stores
      </div>
      <PageHeading
        title="Stores"
        subtitle="Stock sits in a store, not in a hospital. A theatre can run out while the main store is full."
      />

      {alerts.isError && (
        <div className="mt-4"><ErrorNotice>Stock alerts could not be loaded.</ErrorNotice></div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatTile label="Below reorder level" value={low.length} tone={low.length ? 'abnormal' : 'normal'} />
        <StatTile label="Expiring soon" value={expiring.length} tone={expiring.length ? 'abnormal' : 'normal'} />
        <StatTile label="Already expired" value={expired.length} tone={expired.length ? 'critical' : 'normal'} />
      </div>

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
        <Panel>
          <PanelHeader
            title="Below reorder level"
            hint="Expired stock does not count towards the level."
          />
          {alerts.isPending ? (
            <div className="p-5"><LoadingNotice /></div>
          ) : low.length === 0 ? (
            <div className="p-5"><EmptyState>Every store is above its level.</EmptyState></div>
          ) : (
            <TableFrame minWidth={560}>
              <thead>
                <tr>
                  <Th>Item</Th>
                  <Th>Store</Th>
                  <Th className="text-right">In date</Th>
                  <Th className="text-right">Level</Th>
                </tr>
              </thead>
              <tbody>
                {low.map((row) => (
                  <tr key={`${row.store}-${row.item}`}>
                    <Td>
                      <span className="font-medium text-ink">{row.item_name}</span>
                      <div className="text-[11px] text-ink-faint">{row.unit_of_issue}</div>
                    </Td>
                    <Td className="text-ink-muted">
                      <Link href={`/stores/${row.store}`} className="hover:text-accent">
                        {row.store_name}
                      </Link>
                    </Td>
                    <Td className="text-right">
                      <span className="font-semibold text-critical">{row.usable_on_hand}</span>
                      {row.on_hand !== row.usable_on_hand && (
                        <div className="text-[11px] text-ink-faint">
                          {row.on_hand} on shelf
                        </div>
                      )}
                    </Td>
                    <Td className="text-right text-ink-muted">{row.reorder_level}</Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        <div className="grid gap-5">
          {expired.length > 0 && (
            <Panel>
              <PanelHeader
                title="Expired and still on the shelf"
                hint="Cannot be issued. Write it off or return it."
                action={<Badge tone="critical">{expired.length}</Badge>}
              />
              <TableFrame minWidth={520}>
                <thead>
                  <tr>
                    <Th>Item</Th>
                    <Th>Store</Th>
                    <Th className="text-right">Quantity</Th>
                    <Th>Expired</Th>
                  </tr>
                </thead>
                <tbody>
                  {expired.map((row) => (
                    <tr key={row.lot}>
                      <Td>
                        <span className="font-medium text-ink">{row.item_name}</span>
                        <div className="text-[11px] text-ink-faint">lot {row.lot_number}</div>
                      </Td>
                      <Td className="text-ink-muted">{row.store_name}</Td>
                      <Td className="text-right font-semibold">{row.quantity_on_hand}</Td>
                      <Td>
                        <span className="font-medium text-critical">
                          {fullDate(row.expiry_date)}
                        </span>
                        <div className="text-[11px] text-ink-faint">
                          {Math.abs(row.days_left)} days ago
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            </Panel>
          )}

          <Panel>
            <PanelHeader title="Expiring soon" hint="Each store sets its own horizon." />
            {expiring.length === 0 ? (
              <div className="p-5">
                <EmptyState>Nothing expiring inside any store&apos;s horizon.</EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={520}>
                <thead>
                  <tr>
                    <Th>Item</Th>
                    <Th>Store</Th>
                    <Th className="text-right">Quantity</Th>
                    <Th>Expires</Th>
                  </tr>
                </thead>
                <tbody>
                  {expiring.map((row) => (
                    <tr key={row.lot}>
                      <Td>
                        <span className="font-medium text-ink">{row.item_name}</span>
                        <div className="text-[11px] text-ink-faint">lot {row.lot_number}</div>
                      </Td>
                      <Td className="text-ink-muted">{row.store_name}</Td>
                      <Td className="text-right font-semibold">{row.quantity_on_hand}</Td>
                      <Td>
                        {fullDate(row.expiry_date)}
                        <div
                          className={`text-[11px] font-medium ${
                            row.days_left <= 30 ? 'text-critical' : 'text-ink-faint'
                          }`}
                        >
                          {row.days_left} days
                        </div>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
          </Panel>
        </div>
      </div>

      <Panel className="mt-5">
        <PanelHeader title="Stores" hint="Stock is held per store." />
        {stores.isPending ? (
          <div className="p-5"><LoadingNotice /></div>
        ) : (stores.data ?? []).length === 0 ? (
          <div className="p-5">
            <EmptyState>
              No stores yet.{' '}
              {can('inventory.add_store')
                ? 'Create one under Configuration → Stores.'
                : 'Ask an administrator to create one.'}
            </EmptyState>
          </div>
        ) : (
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {(stores.data ?? []).map((store) => {
              const lowHere = low.filter((row) => row.store === store.id).length
              const expiringHere = (alerts.data?.expiring ?? []).filter(
                (row) => row.store === store.id,
              ).length
              return (
                <Link
                  key={store.id}
                  href={`/stores/${store.id}`}
                  className="rounded-lg border border-border bg-surface p-4 transition hover:border-accent/50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-[13px] font-semibold text-ink">{store.name}</span>
                    <Badge tone="idle">{store.kind_display}</Badge>
                  </div>
                  <p className="mt-1 text-[11.5px] text-ink-faint">
                    {store.facility_name}
                    {store.ward_name ? ` · ${store.ward_name}` : ''}
                  </p>
                  <div className="mt-3 flex items-center gap-3 text-[12px]">
                    {lowHere > 0 ? (
                      <span className="flex items-center gap-1 font-medium text-critical">
                        <AlertIcon className="size-3" />
                        {lowHere} below level
                      </span>
                    ) : (
                      <span className="text-normal">Stocked</span>
                    )}
                    {expiringHere > 0 && (
                      <span className="text-ink-muted">{expiringHere} expiring</span>
                    )}
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </Panel>
    </PageShell>
  )
}
