'use client'

import { useRouter } from 'next/navigation'
import { BrandLogo } from '@/components/BrandLogo'
import { useEffect, useState } from 'react'
import {
  ArrowRightIcon,
  EyeIcon,
  EyeSlashIcon,
  LabIcon,
  PatientsIcon,
  ShieldIcon,
  StethoscopeIcon,
} from '@/components/icons'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { type SampleLogin, useDeploymentMeta } from '@/lib/meta'

const inputClass =
  'h-12 w-full rounded-xl border border-border-strong/70 bg-surface px-4 text-sm text-ink transition-colors placeholder:text-ink-faint focus:border-accent'
const labelClass = 'mb-2 block text-[13px] font-medium text-ink'

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

  function fill(sample: SampleLogin) {
    setEmail(sample.email)
    setPassword(sample.password)
    setError('')
  }

  const hospital = meta?.organization ?? 'Your hospital workspace'

  return (
    <div className="min-h-screen bg-surface lg:grid lg:grid-cols-[0.95fr_1fr]">
      <div className="relative m-4 hidden min-h-[calc(100svh-2rem)] flex-col justify-between overflow-hidden rounded-[28px] bg-rail p-10 text-white lg:flex xl:p-14">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-40 -right-48 size-[600px] rounded-full border border-white/10 bg-white/[0.02]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-32 -bottom-52 size-[650px] rounded-full border-[80px] border-white/[0.025]"
        />
        <div className="relative">
          <BrandLogo variant="light" className="w-[224px]" />
          <p className="mt-3 text-xs tracking-[0.04em] text-white/60">Hospital management system</p>
        </div>
        <div className="relative py-16">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[11px] font-medium tracking-wide text-white/80">
            <span className="size-1.5 rounded-full bg-[#b8b5ff]" /> Connected care starts here
          </span>
          <h1 className="mt-7 max-w-lg text-[48px] leading-[1.12] font-medium tracking-[-0.045em] xl:text-[58px]">
            More time for
            <br />
            <span className="text-[#b8b5ff]">what matters.</span>
          </h1>
          <p className="mt-6 max-w-[360px] text-[15px] leading-7 text-white/65">
            One workspace for your entire care team. Bring patients, people, and everyday hospital
            operations together.
          </p>
          <div className="mt-12 max-w-sm space-y-5">
            {[
              {
                icon: PatientsIcon,
                title: 'A complete patient picture',
                description: 'One record, throughout every visit.',
              },
              {
                icon: StethoscopeIcon,
                title: 'A more connected care team',
                description: 'From reception to consultation and beyond.',
              },
              {
                icon: LabIcon,
                title: 'Clarity at every step',
                description: 'Keep results, prescriptions, and billing in view.',
              },
            ].map(({ icon: Icon, title, description }) => (
              <div key={title} className="flex items-center gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-[#c9c6ff]">
                  <Icon className="size-5" />
                </span>
                <div>
                  <p className="text-[13px] font-medium">{title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-white/55">{description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="relative flex items-center gap-2 text-[11px] text-white/55">
          <ShieldIcon className="size-4" /> Healthier people. Brighter tomorrows.
        </div>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 lg:hidden">
            <BrandLogo className="w-[192px]" />
          </div>

          <div className="mb-9">
            <p className="mb-3 text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">
              {hospital} · Staff portal
            </p>
            <h2 className="text-[34px] leading-tight font-semibold tracking-[-0.04em] text-ink">
              Welcome back
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-ink-muted">
              Sign in to your account to continue to your workspace.
            </p>
          </div>

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
                placeholder="Enter your work email"
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
                  placeholder="Enter your password"
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
              className="mt-2 flex h-12 w-full items-center justify-center gap-3 rounded-xl bg-accent text-sm font-semibold text-white shadow-card transition-colors hover:bg-accent-hover disabled:opacity-60"
            >
              {isSubmitting ? 'Signing in…' : 'Sign in to workspace'}
              {!isSubmitting && <ArrowRightIcon className="size-4" />}
            </button>
          </form>

          <p className="mt-5 text-xs leading-5 text-ink-muted">
            Accounts lock after 10 failed attempts in 15 minutes. Ask an administrator to unlock
            yours.
          </p>

          {/* Served by the API only when the deployment is in demo mode, so a
              live hospital's sign-in page cannot render working credentials. */}
          {meta?.demo_mode && meta.sample_logins.length > 0 && (
            <details className="mt-8 rounded-xl border border-border bg-surface-muted/60 p-4">
              <summary className="text-[13px] font-semibold text-ink">
                Explore a demo account
                <span className="ml-2 rounded-md bg-abnormal-muted px-2 py-1 text-[10px] font-medium text-abnormal">
                  Demo
                </span>
              </summary>
              <p className="mt-3 mb-3 text-xs leading-5 text-ink-muted">
                Choose a role to fill in the sign-in form and explore its workspace.
              </p>
              <div className="grid max-h-[250px] gap-2 overflow-y-auto pr-1">
                {meta.sample_logins.map((sample) => (
                  <button
                    key={sample.email}
                    type="button"
                    onClick={() => fill(sample)}
                    className="rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition-colors hover:border-accent hover:bg-accent-muted"
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-[12px] font-bold text-ink">{sample.role}</span>
                      <span className="text-[10.5px] text-ink-faint">
                        {sample.facility ?? 'All facilities'}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-ink-muted">
                      {sample.email}
                    </span>
                  </button>
                ))}
              </div>
              <p className="mt-2.5 border-t border-border pt-2 text-[11px] text-ink-faint">
                Password for every demo account:{' '}
                <span className="font-mono text-[10.5px] text-ink-muted">
                  {meta.sample_logins[0].password}
                </span>
              </p>
            </details>
          )}
          <p className="mt-8 flex items-center justify-center gap-2 text-[11px] text-ink-faint">
            <ShieldIcon className="size-3.5" /> Authorized hospital personnel only
          </p>
        </div>
      </div>
    </div>
  )
}
