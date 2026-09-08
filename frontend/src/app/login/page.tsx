'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { BrandLogo } from '@/components/BrandLogo'
import {
  BedIcon,
  BillingIcon,
  EyeIcon,
  EyeSlashIcon,
  ImagingIcon,
  LabIcon,
  PatientsIcon,
  PharmacyIcon,
  QueueIcon,
  ShieldIcon,
  StethoscopeIcon,
} from '@/components/icons'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useDeploymentMeta } from '@/lib/meta'

const inputClass =
  'h-12 w-full rounded-xl border border-border-strong/70 bg-surface px-4 text-sm text-ink transition-colors placeholder:text-ink-faint focus:border-accent'
const labelClass = 'mb-2 block text-[13px] font-medium text-ink'

/**
 * What the system covers. A statement of scope, not a pitch: staff already
 * work here and do not need persuading, but a sign-in page with nothing on it
 * tells a new member of staff nothing about where they have landed.
 *
 * These are the areas that actually exist, in the order the hospital runs.
 * Adding one here that has not been built would be the worst kind of lie to
 * put on a login screen.
 */
const AREAS = [
  { icon: PatientsIcon, label: 'Patient records' },
  { icon: QueueIcon, label: 'Clinic queue' },
  { icon: StethoscopeIcon, label: 'Consultations' },
  { icon: LabIcon, label: 'Laboratory' },
  { icon: ImagingIcon, label: 'Radiology' },
  { icon: BedIcon, label: 'Wards & beds' },
  { icon: PharmacyIcon, label: 'Pharmacy' },
  { icon: BillingIcon, label: 'Billing' },
]

/**
 * The staff sign-in screen.
 *
 * The form is deliberately plain — one heading, two fields, and the single
 * operational fact that affects staff, which is that repeated failures lock the
 * account. No marketing: this is the first thing a nurse sees at the start of a
 * shift, and the job is to get them in.
 *
 * Demo accounts are a select rather than a list of cards. There are seventeen
 * roles, and seventeen buttons in a scrolling box is a worse way to pick one.
 * It renders only when the *server* says the deployment is in demo mode, so no
 * build of this page can show working credentials on a live hospital's login
 * screen.
 */
export default function LoginPage() {
  const { user, isLoading, login } = useAuth()
  const router = useRouter()
  const { data: meta } = useDeploymentMeta()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isSubmitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!isLoading && user) router.replace('/')
  }, [isLoading, user, router])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!email.trim() || !password) {
      setError('Both fields are required.')
      return
    }
    setError('')
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      router.replace('/')
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Cannot reach the hospital server. Check the connection to it and try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const hospital = meta?.organization ?? null

  return (
    <div className="min-h-screen bg-surface lg:grid lg:grid-cols-[0.9fr_1fr]">
      <div className="relative m-4 hidden min-h-[calc(100svh-2rem)] flex-col justify-between overflow-hidden rounded-[28px] bg-rail p-10 text-white lg:flex xl:p-14">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-40 -right-48 size-[620px] rounded-full border border-white/10 bg-white/[0.02]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-40 -bottom-56 size-[680px] rounded-full border-[72px] border-white/[0.022]"
        />

        <div className="relative">
          <BrandLogo variant="light" className="w-[214px]" />
          <p className="mt-3 text-xs tracking-wider text-white/55">
            Hospital management system
          </p>
        </div>

        <div className="relative py-10">
          <h1 className="max-w-lg text-[40px] leading-[1.14] font-medium tracking-[-0.04em] xl:text-[46px]">
            {hospital ? (
              <>
                {hospital},
                <br />
                <span className="text-[#b8b5ff]">on one record.</span>
              </>
            ) : (
              <>
                One patient,
                <br />
                <span className="text-[#b8b5ff]">one record.</span>
              </>
            )}
          </h1>
          <p className="mt-5 max-w-[380px] text-[15px] leading-7 text-white/60">
            From the front desk to the ward and back to the cash desk — the same
            record, wherever the patient is.
          </p>

          <ul className="mt-11 grid max-w-md grid-cols-2 gap-x-6 gap-y-3.5">
            {AREAS.map(({ icon: Icon, label }) => (
              <li key={label} className="flex items-center gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-[#c9c6ff]">
                  <Icon className="size-4" />
                </span>
                <span className="text-[13px] text-white/80">{label}</span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative flex items-center gap-2 text-[11px] text-white/50">
          <ShieldIcon className="size-4" /> Authorised hospital personnel only
        </p>
      </div>

      <div className="flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-[400px]">
          <div className="mb-9 lg:hidden">
            <BrandLogo className="w-[186px]" />
          </div>

          <h2 className="text-[30px] leading-tight font-semibold tracking-[-0.035em] text-ink">
            Sign in
          </h2>
          <p className="mt-2 mb-8 text-sm text-ink-muted">
            {hospital ? `${hospital} · staff portal` : 'Staff portal'}
          </p>

          <form onSubmit={submit} noValidate>
            <div className="mb-5">
              <label htmlFor="email" className={labelClass}>
                Email address
              </label>
              <input
                id="email"
                type="email"
                name="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@hospital.test"
                className={inputClass}
              />
            </div>

            <div className="mb-5">
              <label htmlFor="password" className={labelClass}>
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className={`${inputClass} pr-11`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((shown) => !shown)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute top-1/2 right-1 flex size-10 -translate-y-1/2 items-center justify-center rounded-lg text-ink-faint transition-colors hover:text-ink-muted"
                >
                  {showPassword ? (
                    <EyeSlashIcon className="size-4" />
                  ) : (
                    <EyeIcon className="size-4" />
                  )}
                </button>
              </div>
            </div>

            {error && (
              <p
                role="alert"
                className="mb-4 rounded-md border border-critical/30 bg-critical-muted px-3 py-2.5 text-[12.5px] font-medium text-critical"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="mt-1 flex h-12 w-full items-center justify-center rounded-xl bg-accent text-sm font-semibold text-white shadow-card transition-colors hover:bg-accent-hover disabled:opacity-60"
            >
              {isSubmitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <p className="mt-4 text-xs leading-5 text-ink-faint">
            Ten failed attempts in fifteen minutes locks the account. An
            administrator can unlock it.
          </p>

          {meta?.demo_mode && meta.sample_logins.length > 0 && (
            <div className="mt-8 rounded-xl border border-border bg-surface-muted/60 p-4">
              <label htmlFor="demo-role" className="text-[12.5px] font-semibold text-ink">
                Demo account
                <span className="ml-2 rounded bg-abnormal-muted px-1.5 py-0.5 text-[10px] font-medium text-abnormal">
                  Demo mode
                </span>
              </label>
              <select
                id="demo-role"
                defaultValue=""
                onChange={(event) => {
                  const sample = meta.sample_logins.find(
                    (entry) => entry.email === event.target.value,
                  )
                  if (!sample) return
                  setEmail(sample.email)
                  setPassword(sample.password)
                  setError('')
                }}
                className="mt-2 h-11 w-full rounded-lg border border-border bg-surface px-3 text-[13px] text-ink"
              >
                <option value="">Choose a role to fill the form…</option>
                {meta.sample_logins.map((sample) => (
                  <option key={sample.email} value={sample.email}>
                    {sample.role}
                    {sample.facility ? ` — ${sample.facility}` : ' — all facilities'}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-[11px] leading-5 text-ink-faint">
                Fills the email and password above, then press Sign in. Each role
                sees only its own work.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
