'use client'

import Link from 'next/link'
import { useState } from 'react'
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
import { useImagingModalities, useImagingProcedures } from '@/lib/imaging'
import { useFacilities } from '@/lib/config'
import { money } from '@/lib/workflow'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { request } from '@/lib/api'

/**
 * The imaging catalogue.
 *
 * Configuration, so it uses the shared list-and-form machinery rather than a
 * hand-designed screen — a hospital adds an examination the same way it adds a
 * laboratory test or a service.
 *
 * Preparation instructions live on the procedure rather than in a leaflet: "nil
 * by mouth for six hours" reaching the ward late is a cancelled slot and a
 * patient who fasted for nothing.
 */
export default function ImagingCataloguePage() {
  const { can } = useAuth()
  const facilities = useFacilities()
  const [facilityId, setFacilityId] = useState<number | null>(null)
  const [modalityId, setModalityId] = useState<number | null>(null)
  const modalities = useImagingModalities()

  const params: Record<string, string> = {}
  if (facilityId) params.facility = String(facilityId)
  if (modalityId) params.modality = String(modalityId)
  const procedures = useImagingProcedures(params)

  const rows = procedures.data ?? []

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Radiology
      </div>
      <PageHeading
        title="Examination catalogue"
        subtitle="What this hospital offers, what it costs, and what a patient has to do first."
        action={
          <Link
            href="/imaging"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Worklist
          </Link>
        }
      />

      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:max-w-2xl">
        <Field label="Modality">
          <Select
            value={modalityId ?? ''}
            onChange={(event) =>
              setModalityId(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">All modalities</option>
            {modalities.data?.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Prices for" hint="Prices are per facility.">
          <Select
            value={facilityId ?? ''}
            onChange={(event) =>
              setFacilityId(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">Choose a facility…</option>
            {facilities.data?.map((facility) => (
              <option key={facility.id} value={facility.id}>
                {facility.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {procedures.isError && <ErrorNotice>Could not load the catalogue.</ErrorNotice>}
      {procedures.isLoading && <LoadingNotice>Loading…</LoadingNotice>}

      <div className="space-y-5">
        <Panel>
          <PanelHeader
            title={`${rows.length} examination${rows.length === 1 ? '' : 's'}`}
            hint={
              facilityId
                ? 'Prices shown for the chosen facility.'
                : 'Choose a facility to see prices — a branch clinic does not charge a teaching hospital’s rates.'
            }
          />
          {rows.length === 0 && !procedures.isLoading ? (
            <div className="p-5">
              <EmptyState>Nothing in the catalogue yet.</EmptyState>
            </div>
          ) : (
            <TableFrame minWidth={920}>
              <thead>
                <tr>
                  <Th>Examination</Th>
                  <Th>Modality</Th>
                  <Th>Body part</Th>
                  <Th>Price</Th>
                  <Th>Preparation</Th>
                  <Th>Notes</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border">
                    <Td>
                      <span className="font-semibold text-ink">{row.name}</span>
                      <span className="mt-0.5 block text-[11.5px] text-ink-muted">
                        {row.code_short}
                        {row.code && ` · ${row.code_system} ${row.code}`}
                      </span>
                    </Td>
                    <Td className="text-ink">{row.modality_name}</Td>
                    <Td className="text-ink-muted">{row.body_part}</Td>
                    <Td className="font-medium text-ink">
                      {row.service === null ? (
                        <span className="text-ink-faint">Not priced</span>
                      ) : facilityId ? (
                        money(row.price)
                      ) : (
                        <span className="text-ink-faint">—</span>
                      )}
                    </Td>
                    <Td className="max-w-64 text-[12px] text-ink-muted">
                      {row.preparation_instructions || '—'}
                    </Td>
                    <Td className="max-w-56">
                      <div className="flex flex-wrap gap-1.5">
                        {row.requires_contrast && <Badge tone="abnormal">Contrast</Badge>}
                        {!row.is_active && <Badge tone="idle">Withdrawn</Badge>}
                      </div>
                      {row.contraindications && (
                        <span className="mt-1 block text-[11.5px] text-abnormal">
                          {row.contraindications}
                        </span>
                      )}
                      <span className="mt-1 block text-[11px] text-ink-faint">
                        {row.typical_minutes} min slot
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableFrame>
          )}
        </Panel>

        {can('imaging.add_imagingprocedure') && (
          <AddProcedure
            modalities={modalities.data ?? []}
            onAdded={() => procedures.refetch()}
          />
        )}
      </div>
    </PageShell>
  )
}

function AddProcedure({
  modalities,
  onAdded,
}: {
  modalities: { id: number; name: string }[]
  onAdded: () => void
}) {
  const client = useQueryClient()
  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      request('/imaging-procedures/', { method: 'POST', body }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['imaging-procedures'] })
      onAdded()
    },
  })
  const [form, setForm] = useState({
    modality: '',
    name: '',
    code_short: '',
    body_part: '',
    preparation_instructions: '',
    contraindications: '',
    typical_minutes: '15',
    requires_contrast: false,
  })

  const fieldErrors = create.error instanceof ApiError ? create.error.fields : {}

  return (
    <Panel>
      <PanelHeader
        title="Add an examination"
        hint="Available to order as soon as it is saved. Price it under Billing → Services."
      />
      <form
        className="space-y-4 p-5"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate(
            {
              ...form,
              modality: Number(form.modality),
              typical_minutes: Number(form.typical_minutes),
            },
            {
              onSuccess: () =>
                setForm({
                  modality: '',
                  name: '',
                  code_short: '',
                  body_part: '',
                  preparation_instructions: '',
                  contraindications: '',
                  typical_minutes: '15',
                  requires_contrast: false,
                }),
            },
          )
        }}
      >
        {create.error instanceof ApiError && Object.keys(fieldErrors).length === 0 && (
          <ErrorNotice>{create.error.message}</ErrorNotice>
        )}
        {create.isSuccess && (
          <p className="rounded-md border border-normal/30 bg-normal-muted px-4 py-3 text-[12.5px] font-medium text-normal">
            Added to the catalogue.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Modality" error={fieldErrors.modality} required>
            <Select
              value={form.modality}
              onChange={(event) => setForm({ ...form, modality: event.target.value })}
            >
              <option value="">Choose…</option>
              {modalities.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name" error={fieldErrors.name} required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Chest X-ray, PA"
            />
          </Field>
          <Field
            label="Short code"
            hint="What the department calls it."
            error={fieldErrors.code_short}
            required
          >
            <Input
              value={form.code_short}
              onChange={(event) => setForm({ ...form, code_short: event.target.value })}
              placeholder="CXR"
            />
          </Field>
          <Field label="Body part" error={fieldErrors.body_part} required>
            <Input
              value={form.body_part}
              onChange={(event) => setForm({ ...form, body_part: event.target.value })}
              placeholder="Chest"
            />
          </Field>
          <Field label="Slot length (minutes)" error={fieldErrors.typical_minutes}>
            <Input
              type="number"
              min={5}
              max={180}
              value={form.typical_minutes}
              onChange={(event) =>
                setForm({ ...form, typical_minutes: event.target.value })
              }
            />
          </Field>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-[12.5px] font-medium text-ink">
              <input
                type="checkbox"
                checked={form.requires_contrast}
                onChange={(event) =>
                  setForm({ ...form, requires_contrast: event.target.checked })
                }
                className="size-4 rounded border-border"
              />
              Uses contrast
            </label>
          </div>
        </div>
        <Field
          label="Preparation instructions"
          hint="Shown to the ward and the patient when the examination is requested."
        >
          <Textarea
            value={form.preparation_instructions}
            onChange={(event) =>
              setForm({ ...form, preparation_instructions: event.target.value })
            }
            placeholder="Nil by mouth for 6 hours. Cannulate before arrival."
          />
        </Field>
        <Field
          label="Contraindications"
          hint="Shown at ordering. Pregnancy, pacemaker, renal impairment."
        >
          <Input
            value={form.contraindications}
            onChange={(event) =>
              setForm({ ...form, contraindications: event.target.value })
            }
          />
        </Field>
        <Button
          type="submit"
          disabled={
            !form.modality ||
            !form.name.trim() ||
            !form.code_short.trim() ||
            !form.body_part.trim() ||
            create.isPending
          }
        >
          {create.isPending ? 'Adding…' : 'Add examination'}
        </Button>
      </form>
    </Panel>
  )
}
