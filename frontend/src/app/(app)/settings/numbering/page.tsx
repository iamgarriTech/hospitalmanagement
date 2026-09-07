'use client'

import { useState } from 'react'
import { ErrorNotice, PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Button, EmptyState, Input, Panel, PanelHeader } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type NumberSequenceRecord, useNumbering, useUpdateNumbering } from '@/lib/config'

/**
 * Identifier formats.
 *
 * The next value is shown but cannot be edited: rewinding a sequence would
 * reissue a hospital number that is already written on a chart. A format change
 * only affects identifiers issued from now on — the ones already out there stay
 * as they were printed.
 */
const LABELS: Record<string, string> = {
  hospital_number: 'Hospital number',
  visit_number: 'Visit number',
  lab_order_number: 'Laboratory order',
  specimen_id: 'Specimen label',
  prescription_number: 'Prescription',
  invoice_number: 'Invoice',
  receipt_number: 'Receipt',
  refund_reference: 'Refund reference',
}

export default function NumberingPage() {
  const { can } = useAuth()
  const sequences = useNumbering()
  const update = useUpdateNumbering()
  const [error, setError] = useState<string | null>(null)

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Numbering formats"
        subtitle="Applies to identifiers issued from now on. Already-issued numbers are unchanged."
      />

      {error && <div className="mt-4"><ErrorNotice>{error}</ErrorNotice></div>}

      <Panel className="mt-6">
        <PanelHeader title="Sequences" hint="Preview shows the next identifier to be issued" />
        {sequences.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : (sequences.data ?? []).length === 0 ? (
          <div className="p-5">
            <EmptyState>No sequences configured.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={820}>
            <thead>
              <tr>
                <Th>Identifier</Th>
                <Th>Prefix</Th>
                <Th className="text-center">Year</Th>
                <Th className="text-right">Digits</Th>
                <Th>Next</Th>
                {can('patients.change_numbersequence') && <Th className="text-right">Change</Th>}
              </tr>
            </thead>
            <tbody>
              {sequences.data!.map((sequence) => (
                <Row
                  key={sequence.id}
                  sequence={sequence}
                  editable={can('patients.change_numbersequence')}
                  update={update}
                  onError={setError}
                />
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}

function Row({
  sequence,
  editable,
  update,
  onError,
}: {
  sequence: NumberSequenceRecord
  editable: boolean
  update: ReturnType<typeof useUpdateNumbering>
  onError: (message: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [prefix, setPrefix] = useState(sequence.prefix)
  const [width, setWidth] = useState(String(sequence.width))
  const [includeYear, setIncludeYear] = useState(sequence.include_year)
  const [separator, setSeparator] = useState(sequence.separator)

  const preview = [
    prefix || null,
    includeYear ? String(new Date().getFullYear()) : null,
    String(sequence.next_value).padStart(Number(width) || 1, '0'),
  ]
    .filter(Boolean)
    .join(separator)

  async function save() {
    onError(null)
    try {
      await update.mutateAsync({
        id: sequence.id,
        prefix,
        width: Number(width),
        include_year: includeYear,
        separator,
      })
      setOpen(false)
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : 'Could not change the format.')
    }
  }

  if (open) {
    return (
      <tr className="bg-accent-muted/40">
        <Td className="font-medium">{LABELS[sequence.key] ?? sequence.key}</Td>
        <Td>
          <Input value={prefix} onChange={(event) => setPrefix(event.target.value)} className="w-20" aria-label="Prefix" />
        </Td>
        <Td className="text-center">
          <input
            type="checkbox"
            checked={includeYear}
            onChange={(event) => setIncludeYear(event.target.checked)}
            className="size-4 rounded border-border"
            aria-label="Include the year"
          />
        </Td>
        <Td className="text-right">
          <Input
            type="number"
            min={1}
            max={12}
            value={width}
            onChange={(event) => setWidth(event.target.value)}
            className="w-16 text-right"
            aria-label="Digits"
          />
        </Td>
        <Td className="font-mono text-[12px] font-semibold text-accent">{preview}</Td>
        <Td className="text-right">
          <div className="flex justify-end gap-1.5">
            <Button onClick={save} disabled={update.isPending}>Save</Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </Td>
      </tr>
    )
  }

  return (
    <tr>
      <Td className="font-medium">{LABELS[sequence.key] ?? sequence.key}</Td>
      <Td className="font-mono text-[11.5px]">{sequence.prefix || '—'}</Td>
      <Td className="text-center text-ink-muted">{sequence.include_year ? 'Yes' : 'No'}</Td>
      <Td className="text-right text-ink-muted">{sequence.width}</Td>
      <Td className="font-mono text-[12px] font-semibold">{sequence.preview}</Td>
      {editable && (
        <Td className="text-right">
          <Button variant="ghost" onClick={() => setOpen(true)}>Change</Button>
        </Td>
      )}
    </tr>
  )
}
