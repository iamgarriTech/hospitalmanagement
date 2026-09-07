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
    <div className="min-h-full bg-surface-muted px-4 py-5 md:px-6 xl:px-8">
      <div className="mx-auto max-w-[1180px]">{children}</div>
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
    <div className={`flex flex-wrap items-start justify-between gap-3 ${className}`}>
      <div>
        <h1 className="text-[21px] leading-none font-bold text-ink xl:text-[24px]">{title}</h1>
        {subtitle && <p className="mt-2 text-[12.5px] leading-tight text-ink-muted">{subtitle}</p>}
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

export function TableFrame({ children, minWidth = 760 }: { children: ReactNode; minWidth?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[12.5px]" style={{ minWidth }}>
        {children}
      </table>
    </div>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={`border-b border-border bg-surface-muted px-3 py-2 text-left text-[11px] font-bold tracking-wide text-ink-muted uppercase ${className}`}
    >
      {children}
    </th>
  )
}

export function Td({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <td className={`border-b border-border px-3 py-2 align-middle text-ink ${className}`}>{children}</td>
}
