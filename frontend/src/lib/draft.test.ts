import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearDraft, draftKey, readDraft, writeDraft } from './draft'

/**
 * AC-23 — a consultation note must survive a dropped connection.
 *
 * This is the retention half of that criterion: what is typed is stashed on the
 * device and only cleared once the server has accepted it. The other half — the
 * explicit saved/unsaved indicator — is in the consultation screen.
 *
 * Every localStorage access is guarded, because private browsing and
 * locked-down browsers throw on it and a note-taking screen must not break for
 * that reason.
 */
describe('draft retention', () => {
  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('keeps what was typed, with the time it was kept', () => {
    const key = draftKey(42)
    writeDraft(key, { clinical_notes: 'Fever for three days' })

    const stashed = readDraft<{ clinical_notes: string }>(key)
    expect(stashed?.value.clinical_notes).toBe('Fever for three days')
    expect(new Date(stashed!.at).getTime()).toBeGreaterThan(0)
  })

  it('returns nothing when there is no stash, rather than throwing', () => {
    expect(readDraft(draftKey('never-written'))).toBeNull()
  })

  it('survives a corrupted stash instead of breaking the screen', () => {
    const key = draftKey(7)
    localStorage.setItem(key, 'not json{')
    expect(readDraft(key)).toBeNull()
  })

  it('clears only once the server has accepted the note', () => {
    const key = draftKey(9)
    writeDraft(key, { clinical_notes: 'draft' })
    expect(readDraft(key)).not.toBeNull()
    clearDraft(key)
    expect(readDraft(key)).toBeNull()
  })

  it('does not throw when the browser refuses storage', () => {
    // Private browsing and some managed browsers throw on access. Losing the
    // local copy is acceptable; crashing the consultation screen is not.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(() => writeDraft(draftKey(1), { a: 1 })).not.toThrow()
    expect(readDraft(draftKey(1))).toBeNull()
    expect(() => clearDraft(draftKey(1))).not.toThrow()
  })

  it('keys drafts per encounter, so two open charts cannot overwrite each other', () => {
    writeDraft(draftKey(1), { clinical_notes: 'patient one' })
    writeDraft(draftKey(2), { clinical_notes: 'patient two' })
    expect(readDraft<{ clinical_notes: string }>(draftKey(1))?.value.clinical_notes).toBe('patient one')
    expect(readDraft<{ clinical_notes: string }>(draftKey(2))?.value.clinical_notes).toBe('patient two')
  })
})
