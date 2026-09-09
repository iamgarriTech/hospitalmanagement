'use client'

import type { MethodVariance } from '@/lib/billing'
import { money } from '@/lib/workflow'
import { Field, Input } from '@/components/ui'

/**
 * The count sheet: one row per payment method the session took money through.
 *
 * A single figure for the drawer is not enough. ₦5,000 short on cash and
 * ₦5,000 over on transfers nets to zero, reconciles clean, and hides two real
 * mistakes — so each method is counted and explained on its own row.
 *
 * The rows are driven by what the session actually took, not by the full list
 * of payment methods, because asking a cashier to count a method nobody used
 * that day teaches them to type zeroes without looking.
 */
export function CountSheet({
  rows, counts, onChange, disabled = false,
}: {
  rows: MethodVariance[]
  counts: Record<number, { counted: string; note: string }>
  onChange: (method: number, value: { counted: string; note: string }) => void
  disabled?: boolean
}) {
  if (rows.length === 0) {
    return (
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        No payments were taken in this session, so there is nothing to count.
      </p>
    )
  }

  return (
    <div className="grid gap-4">
      {rows.map((row) => {
        const entry = counts[row.method] ?? { counted: '', note: '' }
        const expected = Number(row.expected)
        const variance = entry.counted === '' ? null : Number(entry.counted) - expected
        const off = variance !== null && variance !== 0

        return (
          <div
            key={row.method}
            className="rounded-lg border border-border bg-surface-sunken/40 p-4"
          >
            <div className="mb-3 flex items-baseline justify-between gap-4">
              <span className="text-[13px] font-semibold text-ink">{row.method_name}</span>
              <span className="text-[12px] text-ink-muted">
                taken <span className="font-semibold text-ink">{money(row.expected)}</span>
              </span>
            </div>

            <Field label="Counted" required>
              <Input
                type="number"
                step="0.01"
                min={0}
                value={entry.counted}
                disabled={disabled}
                onChange={(event) =>
                  onChange(row.method, { ...entry, counted: event.target.value })
                }
                className="text-right"
                aria-describedby={off ? `variance-${row.method}` : undefined}
              />
            </Field>

            {off && (
              <>
                <p
                  id={`variance-${row.method}`}
                  className="mt-2 text-[12px] font-semibold text-critical"
                >
                  {money(Math.abs(variance))} {variance > 0 ? 'over' : 'short'}
                </p>
                <div className="mt-3">
                  <Field label="What happened" required>
                    <Input
                      value={entry.note}
                      disabled={disabled}
                      maxLength={255}
                      onChange={(event) =>
                        onChange(row.method, { ...entry, note: event.target.value })
                      }
                      placeholder={
                        variance > 0
                          ? 'a transfer posted to the wrong session'
                          : 'change given twice at 14:20, patient had left'
                      }
                    />
                  </Field>
                </div>
              </>
            )}

            {variance === 0 && (
              <p className="mt-2 text-[12px] font-medium text-normal">Matches exactly.</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Is every row counted, and every discrepancy explained? Mirrors the server. */
export function countSheetComplete(
  rows: MethodVariance[],
  counts: Record<number, { counted: string; note: string }>,
) {
  return rows.every((row) => {
    const entry = counts[row.method]
    if (!entry || entry.counted === '') return false
    const variance = Number(entry.counted) - Number(row.expected)
    return variance === 0 || entry.note.trim() !== ''
  })
}

/** The count sheet as the API wants it. */
export function countPayload(
  rows: MethodVariance[],
  counts: Record<number, { counted: string; note: string }>,
) {
  return rows
    .filter((row) => counts[row.method]?.counted !== undefined)
    .map((row) => ({
      method: row.method,
      counted: counts[row.method].counted,
      note: counts[row.method].note ?? '',
    }))
}
