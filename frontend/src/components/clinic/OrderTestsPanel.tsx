'use client'

import { useState } from 'react'
import { ErrorNotice } from '@/components/PageShell'
import { Badge, Button, Field, Panel, PanelHeader, Select, Textarea } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useLabTests, useOrderLabTests } from '@/lib/clinical'

/**
 * Requesting investigations.
 *
 * The clinical details field is not decoration: the laboratory reads it to
 * decide how to handle a specimen and how to interpret a borderline result, and
 * an unexplained request is the one that gets deprioritised.
 *
 * Specimen requirements are shown at the point of ordering, because "fasting 8
 * hours" is useless information if it only appears after the blood is drawn.
 */
export function OrderTestsPanel({
  visitId,
  onOrdered,
}: {
  visitId: number
  onOrdered?: () => void
}) {
  const tests = useLabTests()
  const order = useOrderLabTests()
  const [chosen, setChosen] = useState<number[]>([])
  const [priority, setPriority] = useState('routine')
  const [details, setDetails] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [placed, setPlaced] = useState<string | null>(null)

  const catalogue = tests.data ?? []
  const grouped = catalogue.reduce<Record<string, typeof catalogue>>((groups, test) => {
    const key = test.category_name || 'Other'
    groups[key] = [...(groups[key] ?? []), test]
    return groups
  }, {})

  function toggle(id: number) {
    setChosen((current) =>
      current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id],
    )
    setPlaced(null)
  }

  async function submit() {
    setError(null)
    try {
      const created = await order.mutateAsync({
        visit: visitId,
        tests: chosen,
        priority,
        clinical_details: details.trim(),
      })
      setChosen([])
      setDetails('')
      setPlaced(`${created.order_number} sent to the laboratory.`)
      onOrdered?.()
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not reach the hospital server. Nothing was requested.',
      )
    }
  }

  const selectedTests = catalogue.filter((test) => chosen.includes(test.id))
  const requirements = selectedTests
    .map((test) => test.specimen_requirements)
    .filter(Boolean)

  return (
    <Panel>
      <PanelHeader
        title="Request investigations"
        hint={chosen.length ? `${chosen.length} selected` : 'Select from the catalogue'}
      />
      <div className="grid gap-4 p-5">
        {tests.isLoading ? (
          <p role="status" className="text-[13px] text-ink-muted">
            Loading the catalogue…
          </p>
        ) : catalogue.length === 0 ? (
          <p className="text-[13px] text-ink-muted">
            No tests are configured. The laboratory has to add them before they can be
            requested.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {Object.entries(grouped).map(([category, entries]) => (
              <fieldset key={category}>
                <legend className="mb-1.5 text-[10.5px] font-bold tracking-[0.09em] text-ink-faint uppercase">
                  {category}
                </legend>
                <div className="grid gap-1">
                  {entries.map((test) => (
                    <label
                      key={test.id}
                      className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-surface-muted"
                    >
                      <input
                        type="checkbox"
                        checked={chosen.includes(test.id)}
                        onChange={() => toggle(test.id)}
                        aria-label={`${test.name}${test.is_panel ? ' (panel)' : ''}, ${test.specimen_type} specimen`}
                        className="mt-0.5 size-4 rounded border-border"
                      />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5">
                          <span className="text-[12.5px] font-medium text-ink">{test.name}</span>
                          {test.is_panel && <Badge tone="accent">Panel</Badge>}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-ink-faint">
                          {test.specimen_type}
                          {test.parameters.length > 1 &&
                            ` · ${test.parameters.length} measurements`}
                          {test.turnaround_hours ? ` · ~${test.turnaround_hours}h` : ''}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        )}

        {requirements.length > 0 && (
          <p className="rounded-lg border border-abnormal/30 bg-abnormal-muted px-3 py-2 text-[12px] text-abnormal">
            <strong className="font-bold">Specimen requirements:</strong>{' '}
            {requirements.join(' · ')}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-[160px_1fr]">
          <Field label="Priority">
            <Select value={priority} onChange={(event) => setPriority(event.target.value)}>
              <option value="routine">Routine</option>
              <option value="urgent">Urgent</option>
            </Select>
          </Field>
          <Field
            label="Clinical details"
            hint="Why the test is requested. The laboratory reads this."
          >
            <Textarea
              value={details}
              onChange={(event) => setDetails(event.target.value)}
              placeholder="Fever for three days, query malaria"
              className="min-h-[38px]"
            />
          </Field>
        </div>

        {error && <ErrorNotice>{error}</ErrorNotice>}
        {placed && (
          <p
            role="status"
            className="rounded-md border border-normal/30 bg-normal-muted px-3 py-2 text-[12.5px] font-medium text-normal"
          >
            {placed}
          </p>
        )}

        <div>
          <Button
            onClick={submit}
            disabled={order.isPending || chosen.length === 0}
            className="px-4 py-2.5"
          >
            {order.isPending ? 'Requesting…' : `Request ${chosen.length || ''} test${chosen.length === 1 ? '' : 's'}`}
          </Button>
        </div>
      </div>
    </Panel>
  )
}
