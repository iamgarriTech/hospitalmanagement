import { describe, expect, it } from 'vitest'
import {
  dispenseLabel, invoiceLabel, labLabel, money, queueAction, queueLabel, queueTone,
  shortMoney, waitedFor,
} from './workflow'

/**
 * Labels and tones are shared so the queue board, the dashboard and the patient
 * record cannot call the same state different things. These check that, and
 * that an unknown state degrades to something readable rather than showing an
 * enum to a nurse.
 */
describe('workflow vocabulary', () => {
  it('uses the words staff say, not the enum', () => {
    expect(queueLabel('in_consultation')).toBe('With clinician')
    expect(queueLabel('sent_for_investigation')).toBe('At laboratory')
    expect(queueLabel('sent_for_billing')).toBe('At cash desk')
    expect(labLabel('resulted')).toBe('Awaiting verification')
    expect(dispenseLabel('partially_dispensed')).toBe('Part dispensed')
    expect(invoiceLabel('finalised')).toBe('Unpaid')
  })

  it('degrades an unknown state to something readable', () => {
    expect(queueLabel('some_new_state')).toBe('some new state')
    expect(queueTone('some_new_state')).toBe('idle')
  })

  it('names the action for moving into a state', () => {
    expect(queueAction('called')).toBe('Call patient')
    expect(queueAction('sent_to_pharmacy')).toBe('Send to pharmacy')
    expect(queueAction('completed')).toBe('Complete visit')
  })

  it('reserves normal for finished and abnormal for waiting on someone', () => {
    expect(queueTone('completed')).toBe('normal')
    expect(queueTone('sent_for_billing')).toBe('abnormal')
    expect(queueTone('waiting')).toBe('idle')
  })
})

describe('money', () => {
  it('always shows two decimal places, as a receipt does', () => {
    expect(money('5000')).toBe('₦5,000.00')
    expect(money('0')).toBe('₦0.00')
    expect(money(1234.5)).toBe('₦1,234.50')
  })

  it('drops the decimals only where a total is being skimmed', () => {
    expect(shortMoney(10300)).toBe('₦10,300')
  })

  it('shows a dash for a missing amount, never ₦0', () => {
    // Number('') is 0, so an absent value would otherwise render as "nothing
    // owed" when it means "unknown" — a difference that matters at a cash desk.
    expect(money('not a number')).toBe('—')
    expect(money('')).toBe('—')
    expect(money(null)).toBe('—')
    expect(money(undefined)).toBe('—')
    expect(shortMoney('')).toBe('—')
    // A genuine zero is still shown as zero.
    expect(money(0)).toBe('₦0.00')
    expect(money('0.00')).toBe('₦0.00')
  })
})

describe('waiting times', () => {
  it('reads as minutes within the hour', () => {
    expect(waitedFor(0)).toBe('0 min')
    expect(waitedFor(45)).toBe('45 min')
    expect(waitedFor(59)).toBe('59 min')
  })

  it('switches to hours beyond that, because "680 min" is not a wait anyone parses', () => {
    expect(waitedFor(60)).toBe('1h')
    expect(waitedFor(95)).toBe('1h 35m')
    expect(waitedFor(680)).toBe('11h 20m')
  })
})
