import { describe, expect, it } from 'vitest'
import { ApiError, query } from './api'

/**
 * The API layer's job on a failure is to give the screen something useful to
 * show. A clinician seeing "Something went wrong" when the server said
 * "Account locked after 10 failed attempts" has been failed twice.
 */
describe('ApiError', () => {
  it('carries the server detail, the field errors and the whole body', () => {
    const error = new ApiError(
      409,
      'Possible duplicate records found.',
      {},
      { duplicates: [{ patient: { id: 1 } }] },
    )
    expect(error.status).toBe(409)
    expect(error.message).toBe('Possible duplicate records found.')
    // Structured payloads travel with the error, because the duplicate and
    // safety-warning flows need them.
    expect((error.body as { duplicates: unknown[] }).duplicates).toHaveLength(1)
  })

  it('keeps field errors so they can render next to their input', () => {
    const error = new ApiError(400, 'A reason is required.', {
      duplicate_reason: ['A reason is required to override a suspected duplicate.'],
    })
    expect(error.fields.duplicate_reason?.[0]).toContain('reason is required')
  })
})

describe('query string building', () => {
  it('omits empty values rather than sending search=', () => {
    expect(query({ search: '', patient: 5 })).toBe('?patient=5')
    expect(query({ a: undefined, b: null })).toBe('')
  })

  it('returns nothing when there is nothing to send', () => {
    expect(query({})).toBe('')
  })
})
