import type { Tone } from '@/components/ui'

/**
 * Labels and tones for the states the workflow actually has. Kept out of any
 * page so the queue board, the dashboard, the patient profile and the pharmacy
 * queue cannot drift into calling the same state different things.
 *
 * The wording is what staff say out loud — "with clinician", "at the lab" —
 * rather than the enum. The tone never carries meaning on its own: every badge
 * shows the label too.
 */
const QUEUE: Record<string, { label: string; tone: Tone }> = {
  scheduled: { label: 'Scheduled', tone: 'idle' },
  waiting: { label: 'Waiting', tone: 'idle' },
  called: { label: 'Called', tone: 'accent' },
  in_consultation: { label: 'With clinician', tone: 'progress' },
  sent_for_investigation: { label: 'At laboratory', tone: 'progress' },
  sent_to_pharmacy: { label: 'At pharmacy', tone: 'progress' },
  sent_for_billing: { label: 'At cash desk', tone: 'abnormal' },
  completed: { label: 'Completed', tone: 'normal' },
  cancelled: { label: 'Cancelled', tone: 'idle' },
}

export function queueLabel(status: string) {
  return QUEUE[status]?.label ?? status.replace(/_/g, ' ')
}
export function queueTone(status: string): Tone {
  return QUEUE[status]?.tone ?? 'idle'
}

/** The verb for moving *into* a state, for buttons. */
const QUEUE_ACTIONS: Record<string, string> = {
  waiting: 'Return to waiting',
  called: 'Call patient',
  in_consultation: 'Start consultation',
  sent_for_investigation: 'Send to laboratory',
  sent_to_pharmacy: 'Send to pharmacy',
  sent_for_billing: 'Send to cash desk',
  completed: 'Complete visit',
  cancelled: 'Cancel visit',
}

export function queueAction(status: string) {
  return QUEUE_ACTIONS[status] ?? `Move to ${queueLabel(status).toLowerCase()}`
}

const LAB: Record<string, { label: string; tone: Tone }> = {
  ordered: { label: 'Ordered', tone: 'idle' },
  collected: { label: 'Collected', tone: 'progress' },
  processing: { label: 'Processing', tone: 'progress' },
  resulted: { label: 'Awaiting verification', tone: 'abnormal' },
  verified: { label: 'Verified', tone: 'normal' },
  cancelled: { label: 'Cancelled', tone: 'idle' },
}

export function labLabel(status: string) {
  return LAB[status]?.label ?? status
}
export function labTone(status: string): Tone {
  return LAB[status]?.tone ?? 'idle'
}

const DISPENSE: Record<string, { label: string; tone: Tone }> = {
  active: { label: 'To dispense', tone: 'abnormal' },
  prescribed: { label: 'To dispense', tone: 'abnormal' },
  partially_dispensed: { label: 'Part dispensed', tone: 'progress' },
  dispensed: { label: 'Dispensed', tone: 'normal' },
  cancelled: { label: 'Cancelled', tone: 'idle' },
}

export function dispenseLabel(status: string) {
  return DISPENSE[status]?.label ?? status
}
export function dispenseTone(status: string): Tone {
  return DISPENSE[status]?.tone ?? 'idle'
}

const INVOICE: Record<string, { label: string; tone: Tone }> = {
  draft: { label: 'Draft', tone: 'idle' },
  finalised: { label: 'Unpaid', tone: 'abnormal' },
  paid: { label: 'Paid', tone: 'normal' },
  void: { label: 'Void', tone: 'idle' },
}

export function invoiceLabel(status: string) {
  return INVOICE[status]?.label ?? status
}
export function invoiceTone(status: string): Tone {
  return INVOICE[status]?.tone ?? 'idle'
}

/**
 * Naira, the way a receipt prints it.
 *
 * An absent amount renders as a dash, never as ₦0. `Number('')` is 0, so a
 * missing value would otherwise display as "nothing owed" when it means
 * "unknown" — a difference that matters at a cash desk.
 */
function toAmount(amount: string | number | null | undefined) {
  if (amount === null || amount === undefined) return null
  if (typeof amount === 'string' && amount.trim() === '') return null
  const value = Number(amount)
  return Number.isFinite(value) ? value : null
}

export function money(amount: string | number | null | undefined) {
  const value = toAmount(amount)
  if (value === null) return '—'
  return `₦${value.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function shortMoney(amount: string | number | null | undefined) {
  const value = toAmount(amount)
  if (value === null) return '—'
  return `₦${value.toLocaleString('en-NG', { maximumFractionDigits: 0 })}`
}

/** Waiting times read as minutes up to an hour, then hours and minutes. */
export function waitedFor(minutes: number) {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours}h ${rest}m` : `${hours}h`
}

export function timeOfDay(iso: string) {
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

export function dateAndTime(iso: string) {
  return new Date(iso).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
