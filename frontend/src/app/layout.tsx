import type { Metadata } from 'next'
import { IBM_Plex_Mono, IBM_Plex_Sans } from 'next/font/google'
import { Providers } from './providers'
import './globals.css'

/* IBM Plex: designed for interfaces, with unambiguous 1/l/I and 0/O and
   proper tabular figures — which matters when the number on screen is a dose. */
const plexSans = IBM_Plex_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  display: 'swap',
  variable: '--font-plex-sans',
})

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
  variable: '--font-plex-mono',
})

export const metadata: Metadata = {
  title: 'Hospital Management System',
  description: 'Clinical, laboratory, pharmacy and billing workflows.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
