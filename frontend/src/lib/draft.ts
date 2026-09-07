'use client'

/**
 * Keeps a half-written record on this device.
 *
 * A consultation note is often the only account of what happened, and losing
 * one to a dropped connection means it gets rewritten from memory — which is a
 * worse record, not just an annoyance. So typed content is stashed locally on
 * every change and only cleared once the server has accepted it.
 *
 * Every access is guarded: private browsing and locked-down browsers throw on
 * localStorage, and a note-taking screen must not break because of it.
 */
export type StashedDraft<T> = { value: T; at: string }

export function readDraft<T>(key: string): StashedDraft<T> | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as StashedDraft<T>
  } catch {
    return null
  }
}

export function writeDraft<T>(key: string, value: T) {
  try {
    localStorage.setItem(key, JSON.stringify({ value, at: new Date().toISOString() }))
  } catch {
    // Nothing to do: the server copy is still the primary, and the indicator
    // reports "not saved" either way.
  }
}

export function clearDraft(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // As above.
  }
}

export function draftKey(encounterId: number | string) {
  return `hms.encounter-draft.${encounterId}`
}
