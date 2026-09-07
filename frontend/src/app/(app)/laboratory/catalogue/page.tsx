'use client'

import { PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, EmptyState, Panel, PanelHeader } from '@/components/ui'
import { useLabTests } from '@/lib/clinical'

/**
 * The test catalogue.
 *
 * Read-only here on purpose: a test's parameters and reference ranges decide
 * how every result gets flagged, so editing them is a configuration act with
 * clinical consequences and belongs behind the configuration permissions, not
 * on a screen the bench uses all day.
 *
 * Shown so the bench and prescribers can see exactly what a test measures and
 * against what range — the thing a catalogue is actually for.
 */
export default function CataloguePage() {
  const tests = useLabTests()
  const catalogue = tests.data ?? []

  const grouped = catalogue.reduce<Record<string, typeof catalogue>>((groups, test) => {
    const key = test.category_name || 'Other'
    groups[key] = [...(groups[key] ?? []), test]
    return groups
  }, {})

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Laboratory
      </div>
      <PageHeading
        title="Test catalogue"
        subtitle={`${catalogue.length} test${catalogue.length === 1 ? '' : 's'} configured. A test may carry several measurements, each flagged on its own.`}
      />

      {tests.isLoading ? (
        <p role="status" className="py-10 text-[13px] text-ink-muted">Loading…</p>
      ) : catalogue.length === 0 ? (
        <Panel className="mt-6 p-5">
          <EmptyState>No tests configured yet.</EmptyState>
        </Panel>
      ) : (
        <div className="mt-6 grid gap-5">
          {Object.entries(grouped).map(([category, entries]) => (
            <Panel key={category}>
              <PanelHeader title={category} hint={`${entries.length} tests`} />
              <TableFrame minWidth={880}>
                <thead>
                  <tr>
                    <Th>Test</Th>
                    <Th>Code</Th>
                    <Th>Specimen</Th>
                    <Th>Measurements</Th>
                    <Th className="text-right">Turnaround</Th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((test) => (
                    <tr key={test.id}>
                      <Td>
                        <span className="font-semibold text-ink">{test.name}</span>
                        {test.is_panel && <Badge tone="accent">Panel</Badge>}
                        {test.specimen_requirements && (
                          <div className="mt-0.5 text-[11.5px] text-abnormal">
                            {test.specimen_requirements}
                          </div>
                        )}
                      </Td>
                      <Td className="font-mono text-[11.5px]">{test.short_code}</Td>
                      <Td className="text-ink-muted capitalize">{test.specimen_type}</Td>
                      <Td className="text-[12px] text-ink-muted">
                        {test.parameters.length === 0 ? (
                          <span className="text-ink-faint">—</span>
                        ) : (
                          test.parameters
                            .map((p) => `${p.name}${p.unit ? ` (${p.unit})` : ''}`)
                            .join(', ')
                        )}
                      </Td>
                      <Td className="text-right text-ink-muted">
                        {test.turnaround_hours ? `${test.turnaround_hours}h` : '—'}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableFrame>
            </Panel>
          ))}
        </div>
      )}
    </PageShell>
  )
}
