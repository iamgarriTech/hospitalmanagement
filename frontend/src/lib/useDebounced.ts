'use client'

import { useEffect, useState } from 'react'

/** Hold a value still while someone is typing, so search does not fire per keystroke. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [held, setHeld] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setHeld(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return held
}
