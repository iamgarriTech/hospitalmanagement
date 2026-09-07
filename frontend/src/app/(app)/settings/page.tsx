'use client'

import Link from 'next/link'
import { PageHeading, PageShell } from '@/components/PageShell'
import { Panel } from '@/components/ui'
import { useAuth } from '@/lib/auth'

/**
 * Configuration index.
 *
 * Everything a hospital administrator has to be able to change without a
 * developer. Areas the signed-in user cannot change are not listed — a link to
 * a screen that will refuse you is worse than no link.
 */
const AREAS = [
  {
    href: '/settings/facilities',
    title: 'Facilities, departments and clinics',
    description: 'Sites, their departments, and the clinics patients are booked into.',
    permission: 'facilities.view_facility',
  },
  {
    href: '/settings/roles',
    title: 'Roles and permissions',
    description: 'Create roles and decide what each one may do. Nothing is hard-coded.',
    permission: 'accounts.view_role',
  },
  {
    href: '/billing/services',
    title: 'Services and prices',
    description: 'What the hospital charges for, priced per facility.',
    permission: 'billing.view_service',
  },
  {
    href: '/laboratory/catalogue',
    title: 'Laboratory test catalogue',
    description: 'Tests, their measurements, units and reference ranges.',
    permission: 'laboratory.view_labtest',
  },
  {
    href: '/pharmacy/formulary',
    title: 'Medication formulary',
    description: 'What may be prescribed, with dose ranges and cautions.',
    permission: 'pharmacy.view_medication',
  },
  {
    href: '/settings/payment-methods',
    title: 'Payment methods',
    description: 'How money can be taken, and which methods need a reference.',
    permission: 'billing.view_paymentmethod',
  },
  {
    href: '/settings/numbering',
    title: 'Numbering formats',
    description: 'How hospital numbers, receipts and invoices are formatted.',
    permission: 'patients.view_numbersequence',
  },
  {
    href: '/audit',
    title: 'Audit log',
    description: 'Every recorded action, and verification of the log itself.',
    permission: 'audit.view_auditevent',
  },
]

export default function SettingsPage() {
  const { can } = useAuth()
  const visible = AREAS.filter((area) => can(area.permission))

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Configuration
      </div>
      <PageHeading
        title="Configuration"
        subtitle="Operational settings a hospital changes for itself, without touching code."
      />

      {visible.length === 0 ? (
        <Panel className="mt-6 p-5">
          <p className="text-[13px] text-ink-muted">
            You do not hold any configuration permissions.
          </p>
        </Panel>
      ) : (
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((area) => (
            <Link key={area.href} href={area.href} className="group">
              <Panel className="h-full p-5 transition-colors group-hover:border-accent">
                <p className="text-[14px] font-semibold text-ink group-hover:text-accent">
                  {area.title}
                </p>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-muted">
                  {area.description}
                </p>
              </Panel>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  )
}
