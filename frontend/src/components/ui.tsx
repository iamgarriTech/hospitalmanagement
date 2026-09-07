import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'

/**
 * Shared primitives, so no screen invents its own button or status pill.
 * Plain and bordered throughout — no shadows, no gradients. Clinical software
 * is read, not admired.
 */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const buttonVariants: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-hover disabled:opacity-50',
  secondary:
    'border border-border text-ink hover:border-border-strong hover:bg-surface-muted disabled:opacity-50',
  ghost: 'text-ink-muted hover:bg-surface-muted hover:text-ink disabled:opacity-50',
  danger: 'border border-critical/40 text-critical hover:bg-critical-muted disabled:opacity-50',
}

export function Button({
  variant = 'primary',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed ${buttonVariants[variant]} ${className}`}
      {...props}
    />
  )
}

/**
 * Clinical tones. `normal` is the only green in the system and `critical` the
 * only red, so both keep their meaning wherever they appear.
 */
export type Tone = 'idle' | 'progress' | 'normal' | 'abnormal' | 'critical' | 'accent'

const badgeTones: Record<Tone, string> = {
  idle: 'bg-idle-muted text-idle',
  progress: 'bg-progress-muted text-progress',
  normal: 'bg-normal-muted text-normal',
  abnormal: 'bg-abnormal-muted text-abnormal',
  critical: 'bg-critical-muted text-critical',
  accent: 'bg-accent-muted text-accent',
}

export function Badge({ tone = 'idle', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap ${badgeTones[tone]}`}
    >
      {children}
    </span>
  )
}

/**
 * A result flag. Always carries the word as well as the colour, and marks
 * critical values with a glyph too — printed reports are monochrome, some
 * staff have colour-vision deficiency, and ward monitors are not calibrated.
 */
export function ClinicalFlag({ flag, label }: { flag: string; label: string }) {
  if (!label) return <span className="text-ink-faint">—</span>
  const critical = flag.startsWith('critical')
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-bold tracking-wide uppercase ${
        critical ? 'bg-critical-muted text-critical' : 'bg-abnormal-muted text-abnormal'
      }`}
    >
      {critical && <span aria-hidden>▲</span>}
      {label}
    </span>
  )
}

export function Panel({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-lg border border-border bg-surface ${className}`}>{children}</div>
}

export function PanelHeader({
  title,
  hint,
  action,
}: {
  title: string
  hint?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
      <div>
        <h2 className="text-[13px] font-bold text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-[11.5px] text-ink-faint">{hint}</p>}
      </div>
      {action}
    </div>
  )
}

/**
 * Stat tiles use proportional figures: at display size a tabular "121" reads
 * loose, and tabular exists to align columns, not to stand alone.
 */
export function StatTile({
  label,
  value,
  hint,
  tone = 'idle',
  href,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: Tone
  href?: string
}) {
  const valueTone: Record<Tone, string> = {
    idle: 'text-ink',
    progress: 'text-progress',
    normal: 'text-normal',
    abnormal: 'text-abnormal',
    critical: 'text-critical',
    accent: 'text-accent',
  }
  const inner = (
    <>
      <div className="text-[12px] text-ink-muted">{label}</div>
      <div className={`mt-1 text-[26px] leading-none font-semibold [font-variant-numeric:normal] ${valueTone[tone]}`}>
        {value}
      </div>
      {hint && <div className="mt-1.5 text-[12px] text-ink-faint">{hint}</div>}
    </>
  )
  if (href) {
    return (
      <a
        href={href}
        className="block rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface-muted"
      >
        {inner}
      </a>
    )
  }
  return <Panel className="px-4 py-3">{inner}</Panel>
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-[13px] text-ink-faint">
      {children}
    </div>
  )
}

/* --- forms ------------------------------------------------------------- */

export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string
  hint?: string
  error?: string[]
  required?: boolean
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="text-[12px] font-semibold text-ink">
        {label}
        {required && <span className="ml-0.5 text-critical">*</span>}
      </span>
      {hint && <span className="mt-0.5 block text-[11.5px] text-ink-faint">{hint}</span>}
      <span className="mt-1 block">{children}</span>
      {error?.length ? (
        <span className="mt-1 block text-[11.5px] font-medium text-critical">{error.join(' ')}</span>
      ) : null}
    </label>
  )
}

const controlClass =
  'w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-faint disabled:bg-surface-muted'

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${controlClass} ${className}`} {...props} />
}

export function Select({ className = '', ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${controlClass} ${className}`} {...props} />
}

export function Textarea({ className = '', ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${controlClass} min-h-20 ${className}`} {...props} />
}
