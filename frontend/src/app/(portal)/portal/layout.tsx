import type { Metadata } from 'next'
import type { ReactNode } from 'react'

export const metadata: Metadata = {
  title: 'Your records | VitaCore',
  description: 'See your appointments, results, medication and bills.',
  // The portal is the only externally reachable surface. It has no business
  // in a search index.
  robots: { index: false, follow: false },
}

/**
 * The portal frame.
 *
 * Deliberately not wrapped in the staff `AppShell`, and it renders none of
 * the staff navigation. A patient signed in here has no route to a hospital
 * screen, and the layout is where that starts being true.
 */
export default function PortalLayout({ children }: { children: ReactNode }) {
  return <div className="min-h-dvh bg-surface-sunken">{children}</div>
}
