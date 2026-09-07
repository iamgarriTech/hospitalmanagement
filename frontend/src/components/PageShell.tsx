import type { ReactNode } from 'react'

/**
 * The frame every authenticated screen sits in. Defined once so the queue,
 * consultation, results and billing screens cannot drift apart on width and
 * rhythm the way they do when each sets its own.
 *
 * Wider than a typical admin column, because the clinical screens here are
 * genuinely tabular — a full blood count with four parameters, a reference
 * range and a flag needs the room.
 */
export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full px-4 py-6 md:px-7 lg:py-8 xl:px-9">
      <div className="mx-auto max-w-[1440px]">{children}</div>
    </div>
  )
}

export function PageHeading({
  title,
  subtitle,
  action,
  className = '',
}: {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={`flex flex-wrap items-start justify-between gap-4 ${className}`}>
      <div>
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.035em] text-ink sm:text-[30px]">
          {title}
        </h1>
        {subtitle && <p className="mt-2 text-sm leading-relaxed text-ink-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

/** Inline failure banner, so every screen reports problems identically. */
export function ErrorNotice({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="mb-4 rounded-md border border-critical/30 bg-critical-muted px-4 py-3 text-[12.5px] font-medium text-critical"
    >
      {children}
    </p>
  )
}

export function LoadingNotice({ children = 'Loading…' }: { children?: ReactNode }) {
  return <p className="py-6 text-[13px] text-ink-muted">{children}</p>
}

/* --- tables ------------------------------------------------------------ */

export function TableFrame({
  children,
  minWidth = 760,
}: {
  children: ReactNode
  minWidth?: number
}) {
  return (
    <div className="table-scroll overflow-x-auto">
      <table
        className="w-full border-collapse text-[13px] [&_tbody_tr:last-child_td]:border-b-0 [&_tbody_tr]:transition-colors [&_tbody_tr:hover]:bg-surface-muted/70"
        style={{ minWidth }}
      >
        {children}
      </table>
    </div>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`border-b border-border bg-surface-muted/70 px-5 py-3 text-left text-[11px] font-semibold tracking-[0.06em] text-ink-muted uppercase ${className}`}
    >
      {children}
    </th>
  )
}

export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <td className={`border-b border-border/80 px-5 py-4 align-middle text-ink ${className}`}>
      {children}
    </td>
  )
}
