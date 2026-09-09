'use client'

import { useState } from 'react'
import {
  ErrorNotice, LoadingNotice, PageHeading, PageShell, TableFrame, Td, Th,
} from '@/components/PageShell'
import {
  Badge, Button, EmptyState, Field, Input, Panel, PanelHeader, Select,
} from '@/components/ui'
import { ApiError, request } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useFacilities } from '@/lib/config'
import {
  type InventoryItem, type ItemCategory, type Store,
  useInventoryItems, useItemCategories, useStores,
} from '@/lib/inventory'
import { useWards } from '@/lib/inpatient'
import { money } from '@/lib/workflow'
import { useMutation, useQueryClient } from '@tanstack/react-query'

/**
 * Stores and the item catalogue.
 *
 * A configuration screen, so it uses the shared list-and-form shape. The two
 * numbers on a store are the ones that make AC-147 and AC-149 configurable
 * rather than hard-coded: what an adjustment has to be worth before a second
 * person signs it, and how far ahead that store wants to hear about expiry. A
 * linen store and a store of surgical implants do not deserve the same answer,
 * which is why the figures live here and not in the code.
 */
export default function StoreSettingsPage() {
  const { can } = useAuth()
  const [tab, setTab] = useState<'stores' | 'items' | 'categories'>('stores')

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Stores & items"
        subtitle="Where stock sits, and what the hospital stocks. Both change without code."
      />

      <div className="mt-6 flex gap-1 border-b border-border">
        {([
          ['stores', 'Stores'],
          ['items', 'Items'],
          ['categories', 'Categories'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`px-4 py-2.5 text-[13px] font-medium transition ${
              tab === key
                ? 'text-accent shadow-[inset_0_-2px_0_0_var(--color-accent)]'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === 'stores' && <StoresTab canEdit={can('inventory.change_store')} canAdd={can('inventory.add_store')} />}
        {tab === 'items' && <ItemsTab canAdd={can('inventory.add_inventoryitem')} canEdit={can('inventory.change_inventoryitem')} />}
        {tab === 'categories' && <CategoriesTab canAdd={can('inventory.add_itemcategory')} />}
      </div>
    </PageShell>
  )
}

function useSaveStore() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: Partial<Store> & { id?: number }) =>
      id
        ? request<Store>(`/stores/${id}/`, { method: 'PATCH', body: payload })
        : request<Store>('/stores/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['stores'] }),
  })
}

function StoresTab({ canAdd, canEdit }: { canAdd: boolean; canEdit: boolean }) {
  const stores = useStores()
  const facilities = useFacilities()
  const wards = useWards()
  const save = useSaveStore()

  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    facility: '', name: '', code: '', kind: 'main', ward: '',
    adjustment_authorisation_limit: '10000.00', expiry_horizon_days: '90',
  })

  function open(store: Store | null) {
    setError(null)
    if (store) {
      setEditing(store.id)
      setForm({
        facility: String(store.facility),
        name: store.name,
        code: store.code,
        kind: store.kind,
        ward: store.ward === null ? '' : String(store.ward),
        adjustment_authorisation_limit: store.adjustment_authorisation_limit,
        expiry_horizon_days: String(store.expiry_horizon_days),
      })
    } else {
      setEditing('new')
      setForm({
        facility: String(facilities.data?.[0]?.id ?? ''),
        name: '', code: '', kind: 'main', ward: '',
        adjustment_authorisation_limit: '10000.00', expiry_horizon_days: '90',
      })
    }
  }

  async function submit() {
    setError(null)
    try {
      await save.mutateAsync({
        id: editing === 'new' ? undefined : (editing ?? undefined),
        facility: Number(form.facility),
        name: form.name,
        code: form.code,
        kind: form.kind as Store['kind'],
        ward: form.ward === '' ? null : Number(form.ward),
        adjustment_authorisation_limit: form.adjustment_authorisation_limit,
        expiry_horizon_days: Number(form.expiry_horizon_days),
      })
      setEditing(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That store could not be saved.')
    }
  }

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1.3fr_1fr]">
      <Panel>
        <PanelHeader
          title="Stores"
          hint="Stock is held per store, not per facility."
          action={
            canAdd ? (
              <Button variant="secondary" onClick={() => open(null)}>Add store</Button>
            ) : null
          }
        />
        {stores.isPending ? (
          <div className="p-5"><LoadingNotice /></div>
        ) : (stores.data ?? []).length === 0 ? (
          <div className="p-5"><EmptyState>No stores yet.</EmptyState></div>
        ) : (
          <TableFrame minWidth={640}>
            <thead>
              <tr>
                <Th>Store</Th>
                <Th>Kind</Th>
                <Th className="text-right">Second signature above</Th>
                <Th className="text-right">Expiry warning</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(stores.data ?? []).map((store) => (
                <tr key={store.id}>
                  <Td>
                    <span className="font-medium text-ink">{store.name}</span>
                    <div className="text-[11px] text-ink-faint">
                      {store.code} · {store.facility_name}
                      {store.ward_name ? ` · ${store.ward_name}` : ''}
                    </div>
                  </Td>
                  <Td><Badge tone="idle">{store.kind_display}</Badge></Td>
                  <Td className="text-right">
                    {Number(store.adjustment_authorisation_limit) === 0 ? (
                      <span className="font-medium text-abnormal">every adjustment</span>
                    ) : (
                      money(store.adjustment_authorisation_limit)
                    )}
                  </Td>
                  <Td className="text-right text-ink-muted">
                    {store.expiry_horizon_days} days
                  </Td>
                  <Td>
                    {canEdit && (
                      <button
                        type="button"
                        onClick={() => open(store)}
                        className="text-[12px] font-medium text-accent hover:underline"
                      >
                        Edit
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      {editing !== null && (
        <Panel>
          <PanelHeader title={editing === 'new' ? 'New store' : 'Edit store'} />
          <div className="grid gap-4 p-5">
            {error && <ErrorNotice>{error}</ErrorNotice>}
            <Field label="Facility" required>
              <Select
                value={form.facility}
                disabled={editing !== 'new'}
                onChange={(event) => setForm({ ...form, facility: event.target.value })}
              >
                {(facilities.data ?? []).map((facility) => (
                  <option key={facility.id} value={facility.id}>{facility.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="Name" required>
              <Input
                value={form.name}
                maxLength={120}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </Field>
            <Field label="Code" required hint="Unique within the facility.">
              <Input
                value={form.code}
                maxLength={20}
                onChange={(event) => setForm({ ...form, code: event.target.value })}
              />
            </Field>
            <Field label="Kind" required>
              <Select
                value={form.kind}
                onChange={(event) => setForm({ ...form, kind: event.target.value })}
              >
                <option value="main">Main store</option>
                <option value="pharmacy">Pharmacy store</option>
                <option value="ward">Ward store</option>
                <option value="theatre">Theatre store</option>
                <option value="laboratory">Laboratory store</option>
                <option value="imaging">Imaging store</option>
              </Select>
            </Field>
            <Field label="Ward" hint="Only where the store serves one ward.">
              <Select
                value={form.ward}
                onChange={(event) => setForm({ ...form, ward: event.target.value })}
              >
                <option value="">Serves the whole facility</option>
                {(wards.data ?? []).map((ward) => (
                  <option key={ward.id} value={ward.id}>{ward.name}</option>
                ))}
              </Select>
            </Field>
            <Field
              label="Second signature needed above"
              required
              hint="Zero means every adjustment needs one. Sensible for implants, miserable for linen."
            >
              <Input
                type="number"
                step="0.01"
                min={0}
                value={form.adjustment_authorisation_limit}
                onChange={(event) =>
                  setForm({ ...form, adjustment_authorisation_limit: event.target.value })
                }
                className="text-right"
              />
            </Field>
            <Field
              label="Warn about expiry this many days ahead"
              required
              hint="Reagents need longer notice than gloves."
            >
              <Input
                type="number"
                min={1}
                value={form.expiry_horizon_days}
                onChange={(event) => setForm({ ...form, expiry_horizon_days: event.target.value })}
                className="text-right"
              />
            </Field>
            <div className="flex gap-2">
              <Button
                disabled={save.isPending || form.name === '' || form.code === ''}
                onClick={submit}
              >
                {save.isPending ? 'Saving…' : 'Save store'}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  )
}

function useSaveItem() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...payload }: Partial<InventoryItem> & { id?: number }) =>
      id
        ? request<InventoryItem>(`/inventory-items/${id}/`, { method: 'PATCH', body: payload })
        : request<InventoryItem>('/inventory-items/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['inventory-items'] }),
  })
}

function ItemsTab({ canAdd, canEdit }: { canAdd: boolean; canEdit: boolean }) {
  const items = useInventoryItems()
  const categories = useItemCategories()
  const save = useSaveItem()

  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    category: '', name: '', code: '', unit_of_issue: '',
    default_reorder_level: '0', is_controlled: false, tracks_expiry: true,
  })

  function open(item: InventoryItem | null) {
    setError(null)
    if (item) {
      setEditing(item.id)
      setForm({
        category: String(item.category),
        name: item.name,
        code: item.code,
        unit_of_issue: item.unit_of_issue,
        default_reorder_level: String(item.default_reorder_level),
        is_controlled: item.is_controlled,
        tracks_expiry: item.tracks_expiry,
      })
    } else {
      setEditing('new')
      setForm({
        category: String(categories.data?.[0]?.id ?? ''),
        name: '', code: '', unit_of_issue: '', default_reorder_level: '0',
        is_controlled: false, tracks_expiry: true,
      })
    }
  }

  async function submit() {
    setError(null)
    try {
      await save.mutateAsync({
        id: editing === 'new' ? undefined : (editing ?? undefined),
        category: Number(form.category),
        name: form.name,
        code: form.code,
        unit_of_issue: form.unit_of_issue,
        default_reorder_level: Number(form.default_reorder_level),
        is_controlled: form.is_controlled,
        tracks_expiry: form.tracks_expiry,
      })
      setEditing(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That item could not be saved.')
    }
  }

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1.3fr_1fr]">
      <Panel>
        <PanelHeader
          title="Items"
          hint="What the hospital stocks. Medications live in the formulary instead."
          action={
            canAdd ? (
              <Button variant="secondary" onClick={() => open(null)}>Add item</Button>
            ) : null
          }
        />
        {items.isPending ? (
          <div className="p-5"><LoadingNotice /></div>
        ) : (
          <TableFrame minWidth={640}>
            <thead>
              <tr>
                <Th>Item</Th>
                <Th>Category</Th>
                <Th>Unit</Th>
                <Th className="text-right">Default level</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(items.data ?? []).map((item) => (
                <tr key={item.id}>
                  <Td>
                    <span className="font-medium text-ink">{item.name}</span>
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      <span className="text-[11px] text-ink-faint">{item.code}</span>
                      {item.is_controlled && <Badge tone="abnormal">controlled</Badge>}
                      {!item.tracks_expiry && <Badge tone="idle">no expiry</Badge>}
                    </div>
                  </Td>
                  <Td className="text-ink-muted">{item.category_name}</Td>
                  <Td className="text-ink-muted">{item.unit_of_issue}</Td>
                  <Td className="text-right text-ink-muted">{item.default_reorder_level}</Td>
                  <Td>
                    {canEdit && (
                      <button
                        type="button"
                        onClick={() => open(item)}
                        className="text-[12px] font-medium text-accent hover:underline"
                      >
                        Edit
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      {editing !== null && (
        <Panel>
          <PanelHeader title={editing === 'new' ? 'New item' : 'Edit item'} />
          <div className="grid gap-4 p-5">
            {error && <ErrorNotice>{error}</ErrorNotice>}
            <Field label="Category" required>
              <Select
                value={form.category}
                onChange={(event) => setForm({ ...form, category: event.target.value })}
              >
                {(categories.data ?? []).map((category) => (
                  <option key={category.id} value={category.id}>{category.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="Name" required>
              <Input
                value={form.name}
                maxLength={200}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </Field>
            <Field label="Code" required hint="Unique across the hospital.">
              <Input
                value={form.code}
                maxLength={40}
                onChange={(event) => setForm({ ...form, code: event.target.value })}
              />
            </Field>
            <Field
              label="Unit of issue"
              required
              hint="What one of these is when it leaves the store: box, pair, litre."
            >
              <Input
                value={form.unit_of_issue}
                maxLength={40}
                onChange={(event) => setForm({ ...form, unit_of_issue: event.target.value })}
              />
            </Field>
            <Field
              label="Default reorder level"
              required
              hint="A starting point. Each store sets its own."
            >
              <Input
                type="number"
                min={0}
                value={form.default_reorder_level}
                onChange={(event) =>
                  setForm({ ...form, default_reorder_level: event.target.value })
                }
                className="text-right"
              />
            </Field>
            <div>
              <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
                <input
                  type="checkbox"
                  checked={form.is_controlled}
                  onChange={(event) => setForm({ ...form, is_controlled: event.target.checked })}
                  className="size-4 rounded border-border"
                />
                Controlled item
              </label>
              <p className="mt-1 pl-6.5 text-[12px] leading-relaxed text-ink-muted">
                Cannot be issued without a named recipient.
              </p>
            </div>
            <div>
              <label className="flex items-center gap-2.5 text-[12.5px] font-medium text-ink">
                <input
                  type="checkbox"
                  checked={form.tracks_expiry}
                  onChange={(event) => setForm({ ...form, tracks_expiry: event.target.checked })}
                  className="size-4 rounded border-border"
                />
                Tracked by expiry date
              </label>
              <p className="mt-1 pl-6.5 text-[12px] leading-relaxed text-ink-muted">
                Leave off for things that do not expire. Asking for an expiry on a bed pan
                teaches a storekeeper to invent one.
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                disabled={
                  save.isPending || form.name === '' || form.code === '' ||
                  form.unit_of_issue === ''
                }
                onClick={submit}
              >
                {save.isPending ? 'Saving…' : 'Save item'}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  )
}

function CategoriesTab({ canAdd }: { canAdd: boolean }) {
  const categories = useItemCategories()
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: (payload: { name: string; display_order: number }) =>
      request<ItemCategory>('/item-categories/', { method: 'POST', body: payload }),
    onSettled: () => client.invalidateQueries({ queryKey: ['item-categories'] }),
  })
  const [name, setName] = useState('')
  const [order, setOrder] = useState('0')
  const [error, setError] = useState<string | null>(null)

  return (
    <div className="grid items-start gap-5 xl:grid-cols-[1fr_1fr]">
      <Panel>
        <PanelHeader title="Categories" hint="How the stores list is grouped." />
        {categories.isPending ? (
          <div className="p-5"><LoadingNotice /></div>
        ) : (
          <TableFrame minWidth={360}>
            <thead>
              <tr><Th>Name</Th><Th className="text-right">Order</Th></tr>
            </thead>
            <tbody>
              {(categories.data ?? []).map((category) => (
                <tr key={category.id}>
                  <Td className="font-medium text-ink">{category.name}</Td>
                  <Td className="text-right text-ink-muted">{category.display_order}</Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>

      {canAdd && (
        <Panel>
          <PanelHeader title="New category" />
          <div className="grid gap-4 p-5">
            {error && <ErrorNotice>{error}</ErrorNotice>}
            <Field label="Name" required>
              <Input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="Display order">
              <Input
                type="number"
                min={0}
                value={order}
                onChange={(event) => setOrder(event.target.value)}
                className="text-right"
              />
            </Field>
            <div>
              <Button
                disabled={name === '' || create.isPending}
                onClick={async () => {
                  setError(null)
                  try {
                    await create.mutateAsync({ name, display_order: Number(order) })
                    setName('')
                    setOrder('0')
                  } catch (caught) {
                    setError(
                      caught instanceof ApiError
                        ? caught.message
                        : 'That category could not be saved.',
                    )
                  }
                }}
              >
                {create.isPending ? 'Saving…' : 'Add category'}
              </Button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  )
}
