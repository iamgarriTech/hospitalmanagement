'use client'

import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { SafetyCapabilitySummary } from '@/components/clinic/PrescribePanel'
import { Badge, EmptyState, Input, Panel, PanelHeader } from '@/components/ui'
import { useMedications } from '@/lib/clinical'
import { useDebounced } from '@/lib/useDebounced'

/**
 * The hospital formulary.
 *
 * This is the list a prescriber can write from — which is deliberately what the
 * pharmacy stocks, so a prescription cannot be written for something that
 * cannot be filled.
 *
 * The safety-capability summary is here rather than buried in settings: which
 * checks run against these drugs is a property of the formulary, and the one
 * that is *not* running needs to be findable.
 */
export default function FormularyPage() {
  const [term, setTerm] = useState('')
  const held = useDebounced(term.trim())
  const medications = useMedications(held)
  const rows = medications.data ?? []

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Pharmacy
      </div>
      <PageHeading
        title="Formulary"
        subtitle="What can be prescribed here, with the dose ranges the safety checks use."
      />

      <div className="mt-6 grid items-start gap-5 xl:grid-cols-[1fr_340px]">
        <div className="grid gap-5">
          <div className="max-w-md">
            <label htmlFor="formulary-search" className="sr-only">
              Search the formulary
            </label>
            <Input
              id="formulary-search"
              type="search"
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="Amoxicillin, paracetamol…"
            />
          </div>

          <Panel>
            <PanelHeader title="Medications" hint={`${rows.length} listed`} />
            {medications.isLoading ? (
              <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
                Loading…
              </p>
            ) : rows.length === 0 ? (
              <div className="p-5">
                <EmptyState>Nothing matches.</EmptyState>
              </div>
            ) : (
              <TableFrame minWidth={860}>
                <thead>
                  <tr>
                    <Th>Medication</Th>
                    <Th>Form</Th>
                    <Th>Dose range</Th>
                    <Th className="text-right">In stock</Th>
                    <Th>Cautions</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((medication) => (
                    <tr key={medication.id}>
                      <Td>
                        <span className="font-semibold text-ink">{medication.generic_name}</span>{' '}
                        <span className="text-ink-muted">{medication.strength}</span>
                        {medication.brand_name && (
                          <div className="text-[11px] text-ink-faint">{medication.brand_name}</div>
                        )}
                        <div className="text-[11px] text-ink-faint">{medication.category_name}</div>
                      </Td>
                      <Td className="text-ink-muted">
                        {medication.dosage_form}
                        <div className="text-[11px] text-ink-faint">{medication.default_route}</div>
                      </Td>
                      <Td className="text-[12px] text-ink-muted">
                        {medication.dose_ranges.length === 0 ? (
                          /* Said out loud: no range means the dose check cannot
                             run, and silence would read as "checked and fine". */
                          <span className="font-medium text-abnormal">
                            No range configured — dose is not checked
                          </span>
                        ) : (
                          medication.dose_ranges.map((range) => (
                            <div key={range.id}>
                              {Number(range.min_single_dose)}–{Number(range.max_single_dose)}{' '}
                              {range.dose_unit} {range.route}
                              {range.max_daily_dose &&
                                ` · max ${Number(range.max_daily_dose)}/day`}
                            </div>
                          ))
                        )}
                      </Td>
                      <Td
                        className={`text-right font-semibold ${
                          medication.stock_on_hand === 0 ? 'text-critical' : ''
                        }`}
                      >
                        {medication.stock_on_hand}
                        <div className="text-[10.5px] font-normal text-ink-faint">
                          {medication.dispensing_unit}
                        </div>
                      </Td>
                      <Td>
                        <div className="flex flex-wrap gap-1">
                          {medication.paediatric_caution && <Badge tone="abnormal">Paediatric</Badge>}
                          {medication.avoid_in_renal_impairment && <Badge tone="abnormal">Renal</Badge>}
                        </div>
                        {medication.caution_note && (
                          <div className="mt-1 text-[11px] text-abnormal">
                            {medication.caution_note}
                          </div>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            )}
          </Panel>
        </div>

        <Panel>
          <PanelHeader
            title="Safety checks"
            hint="What runs against every prescription, and what does not"
          />
          <div className="p-5">
            <SafetyCapabilitySummary />
            <p className="mt-4 flex items-start gap-2 rounded-lg border border-abnormal/30 bg-abnormal-muted px-3 py-2.5 text-[11.5px] leading-relaxed text-abnormal">
              <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
              Drug–drug interaction checking needs a licensed interaction database, which is
              not bundled with this system. Until one is configured, interactions must be
              checked independently.
            </p>
          </div>
        </Panel>
      </div>
    </PageShell>
  )
}
