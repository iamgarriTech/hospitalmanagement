import { describe, expect, it } from 'vitest'
import { countPayload, countSheetComplete } from '@/components/till/CountSheet'
import type { MethodVariance } from '@/lib/billing'

function row(overrides: Partial<MethodVariance> & { method: number }): MethodVariance {
  return {
    method_name: `Method ${overrides.method}`,
    expected: '0.00',
    counted: null,
    variance: null,
    note: '',
    counted_at_all: false,
    ...overrides,
  }
}

const CASH = row({ method: 1, method_name: 'Cash', expected: '3000.00' })
const TRANSFER = row({ method: 2, method_name: 'Bank transfer', expected: '2000.00' })

describe('countSheetComplete', () => {
  it('is incomplete while any method is uncounted', () => {
    // The likeliest real mistake: counting the cash box and forgetting the
    // transfers went through the same session.
    expect(countSheetComplete([CASH, TRANSFER], { 1: { counted: '3000.00', note: '' } })).toBe(
      false,
    )
  })

  it('is complete when every method matches', () => {
    expect(
      countSheetComplete([CASH, TRANSFER], {
        1: { counted: '3000.00', note: '' },
        2: { counted: '2000.00', note: '' },
      }),
    ).toBe(true)
  })

  it('requires an explanation on the row that is out, not on the sheet', () => {
    const short = {
      1: { counted: '2900.00', note: '' },
      2: { counted: '2000.00', note: '' },
    }
    expect(countSheetComplete([CASH, TRANSFER], short)).toBe(false)

    short[1].note = 'change given twice at 14:20'
    expect(countSheetComplete([CASH, TRANSFER], short)).toBe(true)
  })

  it('does not let offsetting errors pass as balanced', () => {
    // ₦500 short on cash against ₦500 over on transfers nets to zero. Both
    // rows still need explaining, which is the whole reason for the sheet.
    expect(
      countSheetComplete([CASH, TRANSFER], {
        1: { counted: '2500.00', note: '' },
        2: { counted: '2500.00', note: '' },
      }),
    ).toBe(false)
  })

  it('treats a zero count as counted, because zero is an answer', () => {
    expect(
      countSheetComplete([row({ method: 3, expected: '0.00' })], {
        3: { counted: '0', note: '' },
      }),
    ).toBe(true)
  })
})

describe('countPayload', () => {
  it('sends one entry per counted method, notes included', () => {
    expect(
      countPayload([CASH, TRANSFER], {
        1: { counted: '2900.00', note: 'short by ₦100' },
        2: { counted: '2000.00', note: '' },
      }),
    ).toEqual([
      { method: 1, counted: '2900.00', note: 'short by ₦100' },
      { method: 2, counted: '2000.00', note: '' },
    ])
  })

  it('omits a method the cashier never touched rather than sending a zero', () => {
    // Sending 0.00 for an untouched row would report the whole expected amount
    // as a shortage, which reads as theft rather than an unfinished count.
    expect(countPayload([CASH, TRANSFER], { 1: { counted: '3000.00', note: '' } })).toEqual([
      { method: 1, counted: '3000.00', note: '' },
    ])
  })
})
