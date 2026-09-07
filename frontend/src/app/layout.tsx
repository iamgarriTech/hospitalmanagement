import type { Metadata } from 'next'
import { IBM_Plex_Mono, Inter } from 'next/font/google'
import { Providers } from './providers'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
})

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
  variable: '--font-plex-mono',
})

export const metadata: Metadata = {
  applicationName: 'VitaCore',
  title: { default: 'VitaCore — Hospital Management', template: '%s | VitaCore' },
  description:
    'VitaCore connects your hospital’s clinical, laboratory, pharmacy and billing workflows. Healthier people. Brighter tomorrows.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
