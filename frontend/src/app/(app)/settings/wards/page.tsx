'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
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
} from '@/components/ui'
import { ApiError, request } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useFacilities } from '@/lib/config'
import {
  useBeds,
  useEscalationThresholds,
  useSetBedState,
  useWards,
} from '@/lib/inpatient'
import { useServices } from '@/lib/billing'
import { bedLabel, bedTone, money } from '@/lib/workflow'

const WARD_TYPES = [
  { value: 'general', label: 'General' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'paediatric', label: 'Paediatric' },
  { value: 'maternity', label: 'Maternity' },
  { value: 'intensive', label: 'Intensive care' },
  { value: 'isolation', label: 'Isolation' },
]

const MEASUREMENTS = [
  { value: 'temperature_c', label: 'Temperature (°C)' },
  { value: 'systolic_bp', label: 'Systolic BP (mmHg)' },
  { value: 'diastolic_bp', label: 'Diastolic BP (mmHg)' },
  { value: 'pulse_bpm', label: 'Pulse (bpm)' },
  { value: 'respiratory_rate', label: 'Respiratory rate' },
  { value: 'oxygen_saturation', label: 'Oxygen saturation (%)' },
  { value: 'blood_glucose_mmol', label: 'Blood glucose (mmol/L)' },
]

/**
 * Wards, rooms, beds and escalation thresholds.
 *
 * Configuration, so it is built from the shared list-and-form machinery. A
 * hospital can create a ward, give it rooms, give the rooms beds, and set what
 * this ward escalates on — without anyone touching the database.
 *
 * Thresholds are per ward on purpose: the same figure means something different
 * in intensive care and on a general ward, and one hospital-wide number would
 * either cry wolf or stay silent.
 */
export default function WardSettingsPage() {
  const { can } = useAuth()
  const wards = useWards()
  const [wardId, setWardId] = useState<number | null>(null)

  useEffect(() => {
    if (wardId === null && wards.data?.length) setWardId(wards.data[0].id)
  }, [wardId, wards.data])

  const ward = wards.data?.find((entry) => entry.id === wardId) ?? null

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Wards &amp; beds"
        subtitle="What this hospital has, and what each ward escalates on."
      />

      {wards.isError && <ErrorNotice>Could not load the wards.</ErrorNotice>}
      {wards.isLoading && <LoadingNotice>Loading…</LoadingNotice>}

      <div className="space-y-5">
        <Panel>
          <PanelHeader
            title={`${wards.data?.length ?? 0} ward${wards.data?.length === 1 ? '' : 's'}`}
            hint="Bed counts are derived from live occupancy on every read, never from a stored counter."
          />
          {(wards.data?.length ?? 0) === 0 && !wards.isLoading ? (
            <div className="p-5">
              <EmptyState>No wards yet. Add the first one below.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={820}>
              <thead>
                <tr>
                  <Th>Ward</Th>
                  <Th>Type</Th>
                  <Th>Facility</Th>
                  <Th>Beds</Th>
                  <Th>Bed night</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {wards.data?.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <button
                        type="button"
                        onClick={() => setWardId(row.id)}
                        className="font-semibold text-ink hover:text-accent"
                      >
                        {row.name}
                      </button>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.code}
                      </span>
                    </Td>
                    <Td className="text-ink-muted">{row.ward_type_display}</Td>
                    <Td className="text-ink-muted">{row.facility_name}</Td>
                    <Td>
                      <span className="text-ink">
                        {row.occupancy.occupied} / {row.occupancy.beds}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-ink-muted">
                        {row.occupancy.available} free
                        {row.occupancy.cleaning > 0 &&
                          `, ${row.occupancy.cleaning} cleaning`}
                        {row.occupancy.maintenance > 0 &&
                          `, ${row.occupancy.maintenance} out of service`}
                      </span>
                    </Td>
                    <Td className="text-ink">
                      {row.nightly_rate === null ? (
                        <span className="text-abnormal">Not priced</span>
                      ) : (
                        money(row.nightly_rate)
                      )}
                    </Td>
                    <Td>
                      {wardId === row.id && <Badge tone="accent">Selected</Badge>}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        {can('inpatient.add_ward') && <AddWard />}

        {ward && (
          <>
            <BedsPanel wardId={ward.id} wardName={ward.name} />
            <ThresholdsPanel wardId={ward.id} wardName={ward.name} />
          </>
        )}
      </div>
    </PageShell>
  )
}

function AddWard() {
  const client = useQueryClient()
  const facilities = useFacilities()
  const services = useServices()
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request('/wards/', { method: 'POST', body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['wards'] }),
  })
  const [form, setForm] = useState({
    facility: '',
    name: '',
    code: '',
    ward_type: 'general',
    nightly_service: '',
  })
  const fieldErrors = create.error instanceof ApiError ? create.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title="Add a ward"
        hint="Bed nights bill through the ordinary service machinery, so the rate is a service and a change to it is audited like any other price."
      />
      <form
        className="space-y-4 p-5"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate(
            {
              ...form,
              facility: Number(form.facility),
              nightly_service: form.nightly_service ? Number(form.nightly_service) : null,
            },
            {
              onSuccess: () =>
                setForm({
                  facility: '',
                  name: '',
                  code: '',
                  ward_type: 'general',
                  nightly_service: '',
                }),
            },
          )
        }}
      >
        {create.error instanceof ApiError && Object.keys(fieldErrors).length === 0 && (
          <ErrorNotice>{create.error.message}</ErrorNotice>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Facility" error={fieldErrors.facility} required>
            <Select
              value={form.facility}
              onChange={(event) => setForm({ ...form, facility: event.target.value })}
            >
              <option value="">Choose…</option>
              {facilities.data?.map((facility) => (
                <option key={facility.id} value={facility.id}>
                  {facility.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name" error={fieldErrors.name} required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Male Medical Ward"
            />
          </Field>
          <Field label="Code" error={fieldErrors.code} required>
            <Input
              value={form.code}
              onChange={(event) => setForm({ ...form, code: event.target.value })}
              placeholder="MMW"
            />
          </Field>
          <Field label="Type" error={fieldErrors.ward_type}>
            <Select
              value={form.ward_type}
              onChange={(event) => setForm({ ...form, ward_type: event.target.value })}
            >
              {WARD_TYPES.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Bed-night service"
            hint="The service charged for each night slept."
            error={fieldErrors.nightly_service}
          >
            <Select
              value={form.nightly_service}
              onChange={(event) =>
                setForm({ ...form, nightly_service: event.target.value })
              }
            >
              <option value="">Not priced yet</option>
              {services.data?.map((service) => (
                <option key={service.id} value={service.id}>
                  {service.name} ({service.code})
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Button
          type="submit"
          disabled={
            !form.facility || !form.name.trim() || !form.code.trim() || create.isPending
          }
        >
          {create.isPending ? 'Adding…' : 'Add ward'}
        </Button>
      </form>
    </Panel>
  )
}

function BedsPanel({ wardId, wardName }: { wardId: number; wardName: string }) {
  const { can } = useAuth()
  const client = useQueryClient()
  const beds = useBeds({ ward: String(wardId) })
  const setState = useSetBedState()
  const [roomName, setRoomName] = useState('')
  const [roomCode, setRoomCode] = useState('')
  const [bedCodes, setBedCodes] = useState('A,B,C,D')

  const createRoom = useMutation({
    mutationFn: async () => {
      const room = await request<{ id: number }>('/rooms/', {
        method: 'POST',
        body: { ward: wardId, name: roomName, code: roomCode },
      })
      // Beds are created one by one because a bed is a real thing with its own
      // state and history, not a number on a room.
      for (const code of bedCodes.split(',').map((entry) => entry.trim()).filter(Boolean)) {
        await request('/beds/', { method: 'POST', body: { room: room.id, code } })
      }
      return room
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['beds'] })
      client.invalidateQueries({ queryKey: ['wards'] })
      setRoomName('')
      setRoomCode('')
    },
  })

  const rows = beds.data ?? []
  const byRoom = rows.reduce<Record<string, typeof rows>>((groups, bed) => {
    groups[bed.room_code] = [...(groups[bed.room_code] ?? []), bed]
    return groups
  }, {})

  return (
    <Panel>
      <PanelHeader
        title={`Beds in ${wardName}`}
        hint="A bed has no “occupied” setting: occupancy comes from whether a patient is in it, so the two can never disagree."
      />
      <div className="space-y-5 p-5">
        {beds.isLoading && <LoadingNotice>Loading beds…</LoadingNotice>}
        {rows.length === 0 && !beds.isLoading && (
          <EmptyState>No rooms or beds yet.</EmptyState>
        )}

        {Object.entries(byRoom).map(([room, roomBeds]) => (
          <section key={room}>
            <h3 className="mb-2 text-[12px] font-semibold text-ink">Room {room}</h3>
            <ul className="flex flex-wrap gap-2">
              {roomBeds.map((bed) => (
                <li
                  key={bed.id}
                  className="rounded-lg border border-border px-3 py-2 text-[12px]"
                >
                  <span className="font-semibold text-ink">{bed.code}</span>
                  <span className="ml-2">
                    <Badge tone={bedTone(bed.state)}>{bedLabel(bed.state)}</Badge>
                  </span>
                  {bed.occupant && (
                    <span className="mt-1 block text-[11px] text-ink-muted">
                      {bed.occupant.patient_name}
                    </span>
                  )}
                  {bed.state_note && (
                    <span className="mt-1 block text-[11px] text-ink-faint">
                      {bed.state_note}
                    </span>
                  )}
                  {can('inpatient.manage_beds') && !bed.occupant && (
                    <span className="mt-1.5 flex flex-wrap gap-1">
                      {(['available', 'cleaning', 'maintenance'] as const)
                        .filter((state) => state !== bed.state)
                        .map((state) => (
                          <button
                            key={state}
                            type="button"
                            disabled={setState.isPending}
                            onClick={() =>
                              setState.mutate({ id: bed.id, service_state: state, note: '' })
                            }
                            className="rounded border border-border px-1.5 py-0.5 text-[10.5px] font-medium text-ink-muted hover:border-border-strong hover:text-ink"
                          >
                            {bedLabel(state)}
                          </button>
                        ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}

        {can('inpatient.add_room') && (
          <form
            className="space-y-3 border-t border-border pt-5"
            onSubmit={(event) => {
              event.preventDefault()
              createRoom.mutate()
            }}
          >
            <h3 className="text-[13px] font-semibold text-ink">Add a room and its beds</h3>
            {createRoom.error instanceof ApiError && (
              <ErrorNotice>{createRoom.error.message}</ErrorNotice>
            )}
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Room name" required>
                <Input
                  value={roomName}
                  onChange={(event) => setRoomName(event.target.value)}
                  placeholder="Room 4"
                />
              </Field>
              <Field label="Room code" required>
                <Input
                  value={roomCode}
                  onChange={(event) => setRoomCode(event.target.value)}
                  placeholder="R4"
                />
              </Field>
              <Field label="Bed codes" hint="Comma-separated.">
                <Input
                  value={bedCodes}
                  onChange={(event) => setBedCodes(event.target.value)}
                />
              </Field>
            </div>
            <Button
              type="submit"
              disabled={!roomName.trim() || !roomCode.trim() || createRoom.isPending}
            >
              {createRoom.isPending ? 'Adding…' : 'Add room'}
            </Button>
          </form>
        )}
      </div>
    </Panel>
  )
}

function ThresholdsPanel({ wardId, wardName }: { wardId: number; wardName: string }) {
  const { can } = useAuth()
  const client = useQueryClient()
  const thresholds = useEscalationThresholds(wardId)
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request('/escalation-thresholds/', { method: 'POST', body }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ['escalation-thresholds', wardId] }),
  })
  const [form, setForm] = useState({
    measurement: 'systolic_bp',
    low: '',
    high: '',
    instruction: '',
  })
  const fieldErrors = create.error instanceof ApiError ? create.error.fields : {}
  const rows = thresholds.data ?? []

  return (
    <Panel>
      <PanelHeader
        title={`What ${wardName} escalates on`}
        hint="Per ward, because the same reading means something different in intensive care. An escalation keeps a copy of the bound it breached, so editing these never rewrites history."
      />
      <div className="space-y-5 p-5">
        {rows.length === 0 ? (
          <EmptyState>
            Nothing configured. Observations on this ward will not raise
            escalations — which is a valid choice, not a failure.
          </EmptyState>
        ) : (
          <TableFrame minWidth={620}>
            <thead>
              <tr>
                <Th>Measurement</Th>
                <Th>Low</Th>
                <Th>High</Th>
                <Th>Instruction shown with the alert</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-border">
                  <Td className="font-medium text-ink">{row.measurement_display}</Td>
                  <Td className="text-ink">{row.low ?? '—'}</Td>
                  <Td className="text-ink">{row.high ?? '—'}</Td>
                  <Td className="text-[12px] text-ink-muted">{row.instruction || '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}

        {can('inpatient.add_escalationthreshold') && (
          <form
            className="space-y-3 border-t border-border pt-5"
            onSubmit={(event) => {
              event.preventDefault()
              create.mutate(
                {
                  ward: wardId,
                  measurement: form.measurement,
                  low: form.low || null,
                  high: form.high || null,
                  instruction: form.instruction,
                },
                {
                  onSuccess: () =>
                    setForm({
                      measurement: 'systolic_bp',
                      low: '',
                      high: '',
                      instruction: '',
                    }),
                },
              )
            }}
          >
            <h3 className="text-[13px] font-semibold text-ink">Add a threshold</h3>
            {create.error instanceof ApiError && (
              <ErrorNotice>
                {Object.values(fieldErrors).flat().join(' ') || create.error.message}
              </ErrorNotice>
            )}
            <div className="grid gap-4 sm:grid-cols-4">
              <Field label="Measurement" required>
                <Select
                  value={form.measurement}
                  onChange={(event) =>
                    setForm({ ...form, measurement: event.target.value })
                  }
                >
                  {MEASUREMENTS.map((entry) => (
                    <option key={entry.value} value={entry.value}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Low bound" hint="Blank for no lower bound.">
                <Input
                  type="number"
                  step="0.1"
                  value={form.low}
                  onChange={(event) => setForm({ ...form, low: event.target.value })}
                />
              </Field>
              <Field label="High bound" hint="Blank for no upper bound.">
                <Input
                  type="number"
                  step="0.1"
                  value={form.high}
                  onChange={(event) => setForm({ ...form, high: event.target.value })}
                />
              </Field>
              <Field label="Instruction">
                <Input
                  value={form.instruction}
                  onChange={(event) =>
                    setForm({ ...form, instruction: event.target.value })
                  }
                  placeholder="Tell the registrar"
                />
              </Field>
            </div>
            <Button
              type="submit"
              disabled={(!form.low && !form.high) || create.isPending}
            >
              {create.isPending ? 'Adding…' : 'Add threshold'}
            </Button>
            <p className="text-[11px] text-ink-faint">
              A threshold needs a low bound, a high bound, or both — one with
              neither would never fire.
            </p>
          </form>
        )}
      </div>
    </Panel>
  )
}
