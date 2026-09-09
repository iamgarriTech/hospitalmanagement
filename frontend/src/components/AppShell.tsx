'use client'

import Link from 'next/link'
import { BrandLogo } from './BrandLogo'
import { usePathname } from 'next/navigation'
import {
  type ComponentType,
  type ReactNode,
  type SVGProps,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useAuth } from '@/lib/auth'
import { useDeploymentMeta } from '@/lib/meta'
import { type Notification, useNotifications } from '@/lib/notifications'
import {
  AlertIcon,
  AuditIcon,
  BedIcon,
  BellIcon,
  BillingIcon,
  ChevronRightIcon,
  ChevronUpDownIcon,
  CollapseIcon,
  DashboardIcon,
  ImagingIcon,
  StoresIcon,

  LabIcon,
  LogoutIcon,
  MenuIcon,
  PatientsIcon,
  PharmacyIcon,
  QueueIcon,
  SettingsIcon,
  StethoscopeIcon,
  HospitalIcon,
  ShieldIcon,
} from './icons'

const RAIL_KEY = 'hms.rail-collapsed'

type NavChild = { to: string; label: string; show: boolean }
type NavItem = {
  to: string
  end: boolean
  label: string
  icon: ComponentType<SVGProps<SVGSVGElement>>
  show: boolean
  children?: NavChild[]
}

function isActive(pathname: string, to: string, end: boolean) {
  if (end) return pathname === to
  return pathname === to || pathname.startsWith(`${to}/`)
}

const linkBase = 'group flex h-11 items-center gap-3 rounded-lg px-3 text-[13px] transition-colors'

function linkClass(active: boolean) {
  return `${linkBase} ${
    active
      ? 'bg-accent-muted font-semibold text-accent'
      : 'font-medium text-ink-muted hover:bg-rail-hover hover:text-ink'
  }`
}
function groupClass(active: boolean) {
  return `${linkBase} w-full text-left ${
    active
      ? 'bg-accent-muted/60 font-semibold text-accent'
      : 'font-medium text-ink-muted hover:bg-rail-hover hover:text-ink'
  }`
}
function childClass(active: boolean) {
  return `block rounded-lg py-2.5 pr-3 pl-[42px] text-xs transition-colors ${
    active
      ? 'bg-accent-muted font-semibold text-accent'
      : 'text-ink-muted hover:bg-rail-hover hover:text-ink'
  }`
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, can, canAny, logout, facility, setFacility } = useAuth()
  const pathname = usePathname()
  const [isSidebarOpen, setSidebarOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<string[]>([])
  const [panel, setPanel] = useState<'none' | 'notifications' | 'profile' | 'facility'>('none')
  const [collapsePreference, setCollapsed] = useState(false)
  const [isDesktop, setDesktop] = useState(false)
  const isCollapsed = collapsePreference && isDesktop
  const headerRef = useRef<HTMLElement>(null)
  const menuRef = useRef<HTMLButtonElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const { data: notifications = [] } = useNotifications()
  const { data: meta } = useDeploymentMeta()

  // Route changes close everything: a menu left hanging over a new screen is
  // how someone clicks the wrong patient.
  useEffect(() => {
    setSidebarOpen(false)
    setPanel('none')
  }, [pathname])

  // Remembered, because whoever works from a laptop on a ward round wants the
  // rail out of the way and should not have to say so every shift.
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(RAIL_KEY) === '1')
    } catch {
      // Private browsing can throw on access; expanded is a fine default.
    }
  }, [])

  useEffect(() => {
    function close(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (panel !== 'none')
          headerRef.current?.querySelector<HTMLButtonElement>('[aria-expanded="true"]')?.focus()
        setPanel('none')
        if (isSidebarOpen) {
          setSidebarOpen(false)
          menuRef.current?.focus()
        }
      }
      if (event.key === 'Tab' && isSidebarOpen) {
        const items = Array.from(
          sidebarRef.current?.querySelectorAll<HTMLElement>('a, button') ?? [],
        ).filter((item) => item.getClientRects().length)
        const first = items[0]
        const last = items[items.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last?.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first?.focus()
        }
      }
    }
    function outside(event: PointerEvent) {
      if (!headerRef.current?.contains(event.target as Node)) setPanel('none')
    }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', outside)
    return () => {
      document.removeEventListener('keydown', close)
      document.removeEventListener('pointerdown', outside)
    }
  }, [panel, isSidebarOpen])

  useEffect(() => {
    if (!isSidebarOpen) return
    sidebarRef.current?.querySelector<HTMLElement>('a, button')?.focus()
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [isSidebarOpen])

  function toggleRail() {
    setCollapsed((collapsed) => {
      const next = !collapsed
      try {
        localStorage.setItem(RAIL_KEY, next ? '1' : '0')
      } catch {
        // Preference only.
      }
      if (next) setOpenGroups([])
      return next
    })
  }

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    function update() {
      setDesktop(media.matches)
      if (media.matches) setSidebarOpen(false)
    }
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  const unread = notifications.filter((entry) => !entry.read_at)
  const urgent = unread.filter((entry) => entry.urgency === 'urgent')
  const organization = meta?.organization ?? 'Hospital workspace'

  const links: NavItem[] = [
    { to: '/', end: true, label: 'Dashboard', icon: DashboardIcon, show: true },
    { to: '/queue', end: false, label: 'Queue', icon: QueueIcon, show: can('visits.view_visit') },
    {
      to: '/patients',
      end: false,
      label: 'Patients',
      icon: PatientsIcon,
      show: can('patients.view_patient'),
    },
    {
      to: '/clinic',
      end: false,
      label: 'Clinic',
      icon: StethoscopeIcon,
      show: canAny('clinical.add_encounter', 'clinical.view_encounter'),
      children: [
        { to: '/clinic', label: 'My consultations', show: can('clinical.view_encounter') },
        { to: '/clinic/vitals', label: 'Record vitals', show: can('clinical.add_vitalsigns') },
      ],
    },
    {
      to: '/laboratory',
      end: false,
      label: 'Laboratory',
      icon: LabIcon,
      show: can('laboratory.view_laborder'),
      children: [
        { to: '/laboratory', label: 'Worklist', show: can('laboratory.view_laborder') },
        {
          to: '/laboratory/critical',
          label: 'Critical results',
          show: can('laboratory.view_laborder'),
        },
        {
          to: '/laboratory/catalogue',
          label: 'Test catalogue',
          show: can('laboratory.view_labtest'),
        },
      ],
    },
    {
      to: '/imaging',
      end: false,
      label: 'Radiology',
      icon: ImagingIcon,
      show: can('imaging.view_imagingorder'),
      children: [
        { to: '/imaging', label: 'Worklist', show: can('imaging.view_imagingorder') },
        {
          to: '/imaging/critical',
          label: 'Critical findings',
          show: can('imaging.view_imagingorder'),
        },
        {
          to: '/imaging/catalogue',
          label: 'Examination catalogue',
          show: can('imaging.view_imagingprocedure'),
        },
      ],
    },
    {
      to: '/wards',
      end: false,
      label: 'Inpatient',
      icon: BedIcon,
      show: can('inpatient.view_ward'),
      children: [
        { to: '/wards', label: 'Bed board', show: can('inpatient.view_ward') },
        {
          to: '/wards/requests',
          label: 'Admission requests',
          show: can('inpatient.view_admissionrequest'),
        },
        {
          to: '/wards/discharges',
          label: 'Discharges',
          show: can('inpatient.view_admission'),
        },
      ],
    },
    {
      to: '/pharmacy',
      end: false,
      label: 'Pharmacy',
      icon: PharmacyIcon,
      show: canAny('pharmacy.view_prescription', 'pharmacy.view_medication'),
      children: [
        { to: '/pharmacy', label: 'Dispensing queue', show: can('pharmacy.view_prescription') },
        { to: '/pharmacy/stock', label: 'Stock', show: can('pharmacy.view_stockbatch') },
        { to: '/pharmacy/formulary', label: 'Formulary', show: can('pharmacy.view_medication') },
      ],
    },
    {
      to: '/billing',
      end: false,
      label: 'Billing',
      icon: BillingIcon,
      show: can('billing.view_invoice'),
      children: [
        { to: '/billing', label: 'Outstanding', show: can('billing.view_invoice') },
        { to: '/billing/till', label: 'My till', show: can('billing.view_cashiersession') },
        { to: '/billing/services', label: 'Services & prices', show: can('billing.view_service') },
      ],
    },
    {
      to: '/stores',
      end: false,
      label: 'Stores',
      icon: StoresIcon,
      show: can('inventory.view_stockrecord'),
      children: [
        { to: '/stores', label: 'Stock alerts', show: can('inventory.view_stockrecord') },
      ],
    },
    {
      to: '/insurance',
      end: false,
      label: 'Insurance',
      icon: ShieldIcon,
      show: canAny('insurance.view_claimbatch', 'insurance.view_patientpolicy'),
      children: [
        {
          to: '/insurance',
          label: 'Insurance desk',
          show: can('insurance.view_claimbatch'),
        },
        { to: '/insurance/claims', label: 'Claims', show: can('insurance.view_claimbatch') },
        {
          to: '/insurance/providers',
          label: 'Providers & plans',
          show: can('insurance.view_insuranceprovider'),
        },
      ],
    },
    {
      to: '/settings',
      end: false,
      label: 'Configuration',
      icon: SettingsIcon,
      show: canAny(
        'facilities.view_facility',
        'billing.view_paymentmethod',
        'inpatient.view_ward',
        'inventory.view_store',
      ),
      children: [
        { to: '/settings/facilities', label: 'Facilities', show: can('facilities.view_facility') },
        { to: '/settings/roles', label: 'Roles & permissions', show: can('accounts.view_role') },
        {
          to: '/settings/wards',
          label: 'Wards & beds',
          show: can('inpatient.view_ward'),
        },
        {
          to: '/settings/stores',
          label: 'Stores & items',
          show: can('inventory.view_store'),
        },
        {
          to: '/settings/payment-methods',
          label: 'Payment methods',
          show: can('billing.view_paymentmethod'),
        },
      ],
    },
    {
      to: '/audit',
      end: false,
      label: 'Audit log',
      icon: AuditIcon,
      show: can('patients.view_patient_access_log'),
    },
  ]

  const visibleLinks = links.filter((item) => item.show)
  const currentLabel =
    links.find((item) => isActive(pathname, item.to, item.end))?.label ?? 'Workspace'
  const nav = (
    <nav className="flex flex-1 flex-col gap-1 px-4 pb-6" aria-label="Main">
      {visibleLinks.map(({ to, end, label, icon: ItemIcon, children }) => {
        const visibleChildren = children?.filter((child) => child.show) ?? []
        const childActive = visibleChildren.some((child) => isActive(pathname, child.to, true))
        const active = isActive(pathname, to, end) || childActive
        const open = childActive || openGroups.includes(to)

        // Collapsed: icon only, with the label as its accessible name. A
        // truncated word is worse than none — it invites a wrong click.
        if (isCollapsed) {
          return (
            <Link
              key={to}
              href={visibleChildren[0]?.to ?? to}
              title={label}
              aria-current={active ? 'page' : undefined}
              aria-label={label}
              className={`flex h-11 items-center justify-center rounded-lg transition-colors ${
                active
                  ? 'bg-accent-muted text-accent'
                  : 'text-ink-muted hover:bg-rail-hover hover:text-ink'
              }`}
            >
              <ItemIcon className="size-[18px]" />
            </Link>
          )
        }

        if (visibleChildren.length > 0) {
          return (
            <div key={to}>
              {to === '/settings' && (
                <p className="mt-6 mb-3 px-3 text-[10px] font-semibold tracking-[0.12em] text-ink-faint uppercase">
                  Administration
                </p>
              )}
              <button
                type="button"
                aria-expanded={open}
                onClick={() =>
                  setOpenGroups((current) =>
                    current.includes(to)
                      ? current.filter((entry) => entry !== to)
                      : [...current, to],
                  )
                }
                className={groupClass(active)}
              >
                <ItemIcon className="size-[19px] shrink-0" />
                <span className="flex-1">{label}</span>
                <ChevronRightIcon
                  className={`size-3.5 transition-transform ${open ? 'rotate-90 text-accent' : 'text-ink-faint'}`}
                />
              </button>
              {open && (
                <div className="mt-0.5 flex flex-col gap-0.5">
                  {visibleChildren.map((child) => (
                    <Link
                      key={child.to}
                      href={child.to}
                      aria-current={isActive(pathname, child.to, true) ? 'page' : undefined}
                      className={childClass(isActive(pathname, child.to, true))}
                    >
                      {child.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          )
        }

        return (
          <Link
            key={to}
            href={to}
            aria-current={active ? 'page' : undefined}
            className={linkClass(active)}
          >
            <ItemIcon className="size-[19px] shrink-0" />
            <span className="flex-1">{label}</span>
          </Link>
        )
      })}
    </nav>
  )

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      <a
        href="#main-content"
        className="fixed top-3 left-3 z-50 -translate-y-24 rounded-lg bg-accent px-4 py-3 text-white focus:translate-y-0"
      >
        Skip to content
      </a>
      <div className="fixed inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-surface px-4 no-print lg:hidden">
        <Link href="/" aria-label="VitaCore dashboard">
          <BrandLogo />
        </Link>
        <button
          type="button"
          ref={menuRef}
          onClick={() => setSidebarOpen((open) => !open)}
          aria-label="Toggle menu"
          aria-expanded={isSidebarOpen}
          className="flex size-10 items-center justify-center rounded-lg border border-border text-ink-muted"
        >
          <MenuIcon className="size-[17px]" />
        </button>
      </div>

      {isSidebarOpen && (
        <button
          type="button"
          aria-label="Close menu"
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-20 bg-ink/30 lg:hidden"
        />
      )}

      <aside
        ref={sidebarRef}
        aria-label="Sidebar"
        className={`fixed inset-y-0 left-0 z-30 flex shrink-0 flex-col overflow-y-auto border-r border-border bg-surface transition-[width,transform] duration-200 no-print lg:visible lg:translate-x-0 ${
          isCollapsed ? 'w-[76px]' : 'w-[248px]'
        } ${isSidebarOpen ? 'visible translate-x-0' : 'invisible -translate-x-full'}`}
      >
        <div className="flex h-20 shrink-0 items-center gap-3 px-5">
          <Link
            href="/"
            aria-label="VitaCore dashboard"
            className="flex min-w-0 items-center gap-3"
          >
            <BrandLogo variant={isCollapsed ? 'icon' : 'full'} />
          </Link>
        </div>
        <div
          className={`mb-4 mt-3 flex items-center ${isCollapsed ? 'justify-center' : 'justify-between px-7'}`}
        >
          {!isCollapsed && (
            <p className="text-[10px] font-semibold tracking-[0.12em] text-ink-faint uppercase">
              Workspace
            </p>
          )}
          <button
            type="button"
            onClick={toggleRail}
            title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="hidden rounded-md p-1.5 text-ink-faint hover:bg-surface-muted hover:text-accent lg:block"
          >
            <CollapseIcon className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              setSidebarOpen(false)
              menuRef.current?.focus()
            }}
            aria-label="Close sidebar"
            className="rounded-md px-2 py-1 text-xs text-ink-muted lg:hidden"
          >
            Close
          </button>
        </div>

        {nav}
        <div className={`mt-auto border-t border-border p-4 ${isCollapsed ? 'text-center' : ''}`}>
          {!isCollapsed && (
            <div className="mb-4 flex items-start gap-2 rounded-xl bg-surface-muted p-3">
              <ShieldIcon className="mt-0.5 size-4 shrink-0 text-accent" />
              <div>
                <p className="text-xs font-medium">{organization}</p>
                <p className="mt-1 text-[11px] leading-relaxed text-ink-muted">
                  Connected care, from arrival to discharge.
                </p>
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => logout()}
            title="Sign out"
            className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium text-ink-muted hover:bg-surface-muted"
          >
            <LogoutIcon className="size-4" />
            {!isCollapsed && 'Sign out'}
          </button>
        </div>
      </aside>

      <div
        className={`app-content flex min-w-0 flex-1 flex-col ${isCollapsed ? 'lg:ml-[76px]' : 'lg:ml-[248px]'}`}
      >
        <header
          ref={headerRef}
          className="mt-16 border-b border-border bg-surface px-4 no-print lg:mt-0 lg:px-7 xl:px-9"
        >
          <div className="mx-auto flex h-20 w-full max-w-[1440px] items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-5">
              <div className="hidden items-center gap-2.5 border-r border-border pr-5 text-[13px] md:flex">
                <span className="text-ink-faint">Workspace</span>
                <ChevronRightIcon className="size-3 text-ink-faint" />
                <span className="font-medium">{currentLabel}</span>
              </div>
              <div className="relative min-w-0">
                <button
                  type="button"
                  onClick={() => setPanel(panel === 'facility' ? 'none' : 'facility')}
                  disabled={(user?.facilities.length ?? 0) < 2}
                  aria-expanded={panel === 'facility'}
                  className="flex min-h-9 max-w-full items-center gap-2 rounded-lg bg-surface-muted px-3 text-xs font-medium text-ink disabled:opacity-100"
                >
                  <HospitalIcon className="size-4 shrink-0 text-ink-muted" />
                  <span className="truncate">{facility?.name ?? 'No facility'}</span>
                  {(user?.facilities.length ?? 0) > 1 && (
                    <ChevronUpDownIcon className="size-3 text-ink-faint" />
                  )}
                </button>
                {panel === 'facility' && (
                  <div className="absolute top-12 left-0 z-40 w-64 rounded-xl border border-border bg-surface shadow-popover py-1">
                    {user?.facilities.map((entry) => (
                      <button
                        key={entry.id}
                        type="button"
                        onClick={() => {
                          setFacility(entry)
                          setPanel('none')
                        }}
                        className={`block w-full px-3 py-2 text-left text-[12.5px] hover:bg-surface-muted ${
                          entry.code === facility?.code ? 'font-semibold text-accent' : 'text-ink'
                        }`}
                      >
                        {entry.name}
                        <span className="ml-1.5 text-ink-faint">{entry.code}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="relative flex shrink-0 items-center gap-2 sm:gap-4">
              {meta?.demo_mode && (
                <span className="mr-1 hidden rounded border border-abnormal/30 bg-abnormal-muted px-2 py-0.5 text-[10.5px] font-bold tracking-wide text-abnormal uppercase sm:inline">
                  Demo data
                </span>
              )}

              <button
                type="button"
                onClick={() => setPanel(panel === 'notifications' ? 'none' : 'notifications')}
                aria-label={`Notifications${unread.length ? `, ${unread.length} unread` : ''}`}
                aria-expanded={panel === 'notifications'}
                className="relative flex size-10 items-center justify-center rounded-xl border border-border text-ink-muted hover:bg-surface-muted"
              >
                <BellIcon className="size-[17px]" />
                {unread.length > 0 && (
                  <span
                    className={`absolute top-0.5 right-0 flex min-w-[15px] items-center justify-center rounded-full px-1 text-[9px] font-bold text-white ${
                      urgent.length > 0 ? 'bg-critical' : 'bg-accent'
                    }`}
                  >
                    {unread.length > 9 ? '9+' : unread.length}
                  </span>
                )}
              </button>

              {panel === 'notifications' && <NotificationPanel notifications={notifications} />}

              <button
                type="button"
                onClick={() => setPanel(panel === 'profile' ? 'none' : 'profile')}
                aria-label="Open profile menu"
                aria-expanded={panel === 'profile'}
                className="flex min-h-10 items-center gap-2.5 rounded-lg text-[13px] text-ink hover:bg-surface-muted"
              >
                <span className="flex size-9 items-center justify-center rounded-full bg-accent-muted text-xs font-bold text-accent">
                  {user?.full_name.charAt(0).toUpperCase()}
                </span>
                <span className="hidden max-w-36 text-left sm:block">
                  <span className="block truncate font-semibold">{user?.full_name}</span>
                  <span className="block truncate text-[10px] text-ink-muted">
                    {user?.roles[0]?.role ?? 'Staff account'}
                  </span>
                </span>
                <ChevronUpDownIcon className="hidden size-3 text-ink-faint sm:block" />
              </button>

              {panel === 'profile' && (
                <div className="absolute top-12 right-0 z-40 w-64 rounded-xl border border-border bg-surface shadow-popover">
                  <div className="border-b border-border px-3 py-2.5">
                    <p className="text-[12.5px] font-semibold text-ink">{user?.full_name}</p>
                    <p className="text-[11.5px] text-ink-faint">{user?.email}</p>
                    <p className="mt-1.5 text-[11px] text-ink-muted">
                      {user?.roles.map((entry) => entry.role).join(' · ') || 'No role assigned'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => logout()}
                    className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[12.5px] text-ink hover:bg-surface-muted"
                  >
                    <LogoutIcon className="size-4 text-ink-muted" />
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="flex-1">
          {children}
        </main>
      </div>
    </div>
  )
}

function NotificationPanel({ notifications }: { notifications: Notification[] }) {
  return (
    <div className="absolute top-12 right-0 z-40 w-[min(92vw,420px)] rounded-xl border border-border bg-surface shadow-popover">
      <div className="border-b border-border px-3 py-2.5">
        <p className="text-[12.5px] font-bold text-ink">Notifications</p>
      </div>
      <div className="max-h-[380px] overflow-y-auto">
        {notifications.length === 0 && (
          <p className="px-3 py-6 text-center text-[12px] text-ink-faint">Nothing waiting.</p>
        )}
        {notifications.map((entry) => (
          <div
            key={entry.id}
            className={`border-b border-border px-3 py-2.5 last:border-b-0 ${
              entry.read_at ? '' : 'bg-accent-muted/40'
            }`}
          >
            <div className="flex items-start gap-2">
              {entry.urgency === 'urgent' && (
                <AlertIcon className="mt-0.5 size-3.5 shrink-0 text-critical" />
              )}
              <div className="min-w-0">
                <p
                  className={`text-[12.5px] font-semibold ${
                    entry.urgency === 'urgent' ? 'text-critical' : 'text-ink'
                  }`}
                >
                  {entry.subject}
                </p>
                {entry.body && (
                  <p className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">{entry.body}</p>
                )}
                {entry.patient_name && (
                  <p className="mt-1 text-[11px] text-ink-faint">{entry.patient_name}</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
