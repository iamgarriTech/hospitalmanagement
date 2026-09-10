import type { SVGProps } from 'react'

/* Single-stroke line icons at a consistent 1.6 weight. Every one is decorative:
   the label beside it is what conveys meaning. */

function Icon({ children, ...props }: SVGProps<SVGSVGElement> & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  )
}

export const DashboardIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z" />
  </Icon>
)
export const PatientsIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3.5 20c0-3.3 2.5-5.6 5.5-5.6s5.5 2.3 5.5 5.6M17 11h4M19 9v4" />
  </Icon>
)
export const QueueIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.2" />
    <path d="M12 7.5V12l3 2" />
  </Icon>
)
export const StethoscopeIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 3v5a4 4 0 0 0 8 0V3M10 12v3a5 5 0 0 0 5 5 4 4 0 0 0 4-4v-2" />
    <circle cx="19" cy="12" r="1.6" />
  </Icon>
)
export const LabIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M9 3h6M10 3v6.5L5.6 17A2.6 2.6 0 0 0 7.9 21h8.2a2.6 2.6 0 0 0 2.3-4L14 9.5V3M7 15h10" />
  </Icon>
)
export const PharmacyIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3.2" y="8" width="17.6" height="12.4" rx="2.4" />
    <path d="M12 11.4v5.6M9.2 14.2h5.6M8 8V5.6A2.4 2.4 0 0 1 10.4 3.2h3.2A2.4 2.4 0 0 1 16 5.6V8" />
  </Icon>
)
export const BillingIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3.4" y="4.4" width="17.2" height="15.2" rx="2" />
    <path d="M7.4 9h9.2M7.4 13h6M7.4 16.4h4" />
  </Icon>
)
export const SettingsIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6" />
  </Icon>
)
export const AuditIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M6 3.6h8.6L19 8v12.4H6zM14 3.6V8h5M9 12.4h6M9 16h4" />
  </Icon>
)
export const SearchIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="6.4" />
    <path d="M15.8 15.8 21 21" />
  </Icon>
)
export const BellIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M18 15.6V10.4a6 6 0 1 0-12 0v5.2L4.4 18h15.2zM9.6 18v.8a2.4 2.4 0 0 0 4.8 0V18" />
  </Icon>
)
export const MenuIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)
export const ChevronRightIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M9.5 5.5 16 12l-6.5 6.5" />
  </Icon>
)
export const ChevronUpDownIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M8 10l4-4 4 4M8 14l4 4 4-4" />
  </Icon>
)
export const AlertIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M12 4.6 21 20H3zM12 10v4.2M12 16.8v.4" />
  </Icon>
)
export const LogoutIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M15 8V5.6A1.6 1.6 0 0 0 13.4 4H6.6A1.6 1.6 0 0 0 5 5.6v12.8A1.6 1.6 0 0 0 6.6 20h6.8a1.6 1.6 0 0 0 1.6-1.6V16M10 12h10M17 9l3 3-3 3" />
  </Icon>
)

export const EyeIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M2.6 12S6 5.8 12 5.8 21.4 12 21.4 12 18 18.2 12 18.2 2.6 12 2.6 12Z" />
    <circle cx="12" cy="12" r="2.8" />
  </Icon>
)
export const EyeSlashIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 4l16 16M9.6 5.9A9.6 9.6 0 0 1 12 5.8c6 0 9.4 6.2 9.4 6.2a17 17 0 0 1-2.6 3.4M6.7 7.9A17 17 0 0 0 2.6 12S6 18.2 12 18.2a9 9 0 0 0 3.1-.5M9.9 9.9a2.8 2.8 0 0 0 3.9 3.9" />
  </Icon>
)
export const CollapseIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3.4" y="4.4" width="17.2" height="15.2" rx="2" />
    <path d="M9.4 4.4v15.2" />
  </Icon>
)

export const HospitalIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="4" y="3" width="16" height="18" rx="3" />
    <path d="M12 6v6M9 9h6M9 21v-5h6v5" />
  </Icon>
)
export const CalendarIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="3" y="5" width="18" height="16" rx="3" />
    <path d="M7 3v4M17 3v4M3 11h18M8 15h2M14 15h2M8 18h2" />
  </Icon>
)
export const ArrowRightIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 12h16M14 6l6 6-6 6" />
  </Icon>
)
export const RefreshIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.5-1L20 9M4 15l2.4 3A7 7 0 0 0 18 17" />
  </Icon>
)
export const ShieldIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5" />
  </Icon>
)

/** A ward bed, for the inpatient section. */
export const BedIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 8v11M3 12h18a0 0 0 0 1 0 0v7M3 19h18M7.5 12V9.5h4a2 2 0 0 1 2 2V12" />
    <circle cx="6" cy="9" r="1.6" />
  </Icon>
)

/** A radiology film, for imaging. */
export const ImagingIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <rect x="4" y="3" width="16" height="18" rx="2" />
    <path d="M12 3v18M8 8.5c1.6 1.2 1.6 6.8 0 8M16 8.5c-1.6 1.2-1.6 6.8 0 8" />
  </Icon>
)

/** A box on a shelf. Stores. */
export const StoresIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z" />
    <path d="M3 7.5 12 12l9-4.5M12 12v9" />
  </Icon>
)

/** A scalpel. Theatre. */
export const TheatreIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 20 14.5 9.5M13 4.5 20 11l-5.5 1.5L11 9z" />
    <path d="M4 20h3l1-3" />
  </Icon>
)

/** A cross in a shield. The emergency department. */
export const EmergencyIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M7 4h10l4 4v8l-4 4H7l-4-4V8z" />
    <path d="M12 9v6M9 12h6" />
  </Icon>
)

/** A bar chart. Reports. */
export const ReportsIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M4 20V4M4 20h16" />
    <path d="M8 20v-6M12.5 20V8M17 20v-9" />
  </Icon>
)

/** An arrow leaving a document. A referral. */
export const ReferralIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <path d="M13 3.6H6v16.8h12V8.6z" />
    <path d="M13 3.6V8.6h5" />
    <path d="M9 14h6M13 11.5 15.5 14 13 16.5" />
  </Icon>
)

/** A stylised mother and child. Maternity. */
export const MaternityIcon = (p: SVGProps<SVGSVGElement>) => (
  <Icon {...p}>
    <circle cx="10" cy="5.5" r="2.5" />
    <path d="M6 21v-6a4 4 0 0 1 4-4c2.5 0 4 1.5 4 4v2" />
    <circle cx="17" cy="13" r="2" />
    <path d="M14.5 21v-3a2.5 2.5 0 0 1 5 0v3" />
  </Icon>
)
