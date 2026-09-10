'use client'

import { useState } from 'react'
import { AlertIcon } from '@/components/icons'
import { ApiError } from '@/lib/api'
import {
  type PortalBill, type PortalMedication, type PortalResult, type PortalVisit,
  usePortalBills, usePortalLogin, usePortalLogout, usePortalMe,
  usePortalMedication, usePortalPasswordChange, usePortalResults, usePortalVisits,
} from '@/lib/portal'
import { dateAndTime, fullDate, money } from '@/lib/workflow'

/**
 * The patient portal.
 *
 * One page, four sections, and nothing on it that names a patient — the
 * server decides whose records these are from the session cookie, so there is
 * no URL to edit and no parameter to change.
 *
 * Written plainly on purpose. The people reading this are unwell, worried, or
 * both, often on a phone with a poor connection, and the hospital's internal
 * vocabulary is not theirs. Results carry their reference range because a
 * number alone is a number somebody will search for and misread.
 */
export default function PortalPage() {
  const me = usePortalMe()

  if (me.isPending) {
    return (
      <main className="grid min-h-dvh place-items-center p-6">
        <p role="status" className="text-[14px] text-ink-muted">Loading…</p>
      </main>
    )
  }

  if (me.isError || !me.data) {
    return <SignIn />
  }

  if (me.data.must_change_password) {
    return <ChangePassword name={me.data.patient_name} />
  }

  return <Records me={me.data} />
}

function Shell({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <main className="mx-auto w-full max-w-2xl p-5 sm:p-8">
      <header className="mb-6">
        <p className="text-[11px] font-medium tracking-[0.12em] text-accent uppercase">
          VitaCore
        </p>
        <h1 className="mt-1 text-[22px] font-semibold text-ink">
          {title ?? 'Your records'}
        </h1>
      </header>
      {children}
    </main>
  )
}

function Card({
  title, children, hint,
}: {
  title: string
  children: React.ReactNode
  hint?: string
}) {
  return (
    <section className="mb-5 rounded-xl border border-border bg-surface p-5">
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {hint && <p className="mt-0.5 text-[12.5px] text-ink-muted">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function SignIn() {
  const login = usePortalLogin()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  return (
    <Shell title="Sign in">
      <form
        className="rounded-xl border border-border bg-surface p-5"
        onSubmit={async (event) => {
          event.preventDefault()
          setError(null)
          try {
            await login.mutateAsync({
              login_identifier: identifier, password,
            })
          } catch (caught) {
            setError(
              caught instanceof ApiError
                ? caught.message
                : 'Something went wrong. Please try again.',
            )
          }
        }}
      >
        <p className="mb-4 text-[13.5px] leading-relaxed text-ink-muted">
          Use the phone number or email address the hospital registered for you,
          and the password they gave you.
        </p>

        {error && (
          <p
            role="alert"
            className="mb-4 flex items-start gap-2 rounded-lg border border-critical/30 bg-critical/5 px-3 py-2.5 text-[13px] leading-relaxed text-critical"
          >
            <AlertIcon className="mt-0.5 size-3.5 shrink-0" />
            {error}
          </p>
        )}

        <div className="grid gap-4">
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">
              Phone number or email
            </span>
            <input
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              autoComplete="username"
              inputMode="email"
              required
              className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[15px] text-ink"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
              className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[15px] text-ink"
            />
          </label>
          <button
            type="submit"
            disabled={login.isPending || !identifier || !password}
            className="rounded-lg bg-accent px-4 py-3 text-[15px] font-medium text-white transition disabled:opacity-50"
          >
            {login.isPending ? 'Signing in…' : 'Sign in'}
          </button>
        </div>

        <p className="mt-5 border-t border-border pt-4 text-[12.5px] leading-relaxed text-ink-muted">
          If you have forgotten your password, the hospital's records office can
          issue a new one. For anything about your treatment, contact the hospital
          directly — nobody reads messages sent through this page.
        </p>
      </form>
    </Shell>
  )
}

function ChangePassword({ name }: { name: string }) {
  const change = usePortalPasswordChange()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mismatch = again !== '' && next !== again

  return (
    <Shell title="Choose a password">
      <form
        className="rounded-xl border border-border bg-surface p-5"
        onSubmit={async (event) => {
          event.preventDefault()
          setError(null)
          try {
            await change.mutateAsync({
              current_password: current, new_password: next,
            })
          } catch (caught) {
            setError(
              caught instanceof ApiError
                ? Object.values(caught.fields).flat().join(' ') || caught.message
                : 'Something went wrong. Please try again.',
            )
          }
        }}
      >
        <p className="mb-4 text-[13.5px] leading-relaxed text-ink-muted">
          Hello {name}. The password the hospital gave you is temporary — choose
          your own before going on. Signing out of any other device happens
          automatically.
        </p>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded-lg border border-critical/30 bg-critical/5 px-3 py-2.5 text-[13px] leading-relaxed text-critical"
          >
            {error}
          </p>
        )}

        <div className="grid gap-4">
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">
              The password the hospital gave you
            </span>
            <input
              type="password" value={current} required
              autoComplete="current-password"
              onChange={(event) => setCurrent(event.target.value)}
              className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[15px] text-ink"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">Your new password</span>
            <input
              type="password" value={next} required minLength={12}
              autoComplete="new-password"
              onChange={(event) => setNext(event.target.value)}
              className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[15px] text-ink"
            />
            <span className="text-[12px] text-ink-muted">
              At least twelve characters. A short phrase you will remember is
              better than a short word with symbols in it.
            </span>
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-medium text-ink">Type it again</span>
            <input
              type="password" value={again} required
              autoComplete="new-password"
              onChange={(event) => setAgain(event.target.value)}
              className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[15px] text-ink"
            />
            {mismatch && (
              <span className="text-[12px] font-medium text-critical">
                Those two do not match.
              </span>
            )}
          </label>
          <button
            type="submit"
            disabled={
              change.isPending || !current || next.length < 12 || next !== again
            }
            className="rounded-lg bg-accent px-4 py-3 text-[15px] font-medium text-white transition disabled:opacity-50"
          >
            {change.isPending ? 'Saving…' : 'Save it'}
          </button>
        </div>
      </form>
    </Shell>
  )
}

function Records({ me }: { me: { patient_name: string; hospital_number: string } }) {
  const logout = usePortalLogout()
  const visits = usePortalVisits()
  const results = usePortalResults()
  const medication = usePortalMedication()
  const bills = usePortalBills()

  return (
    <Shell>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3 rounded-xl border border-border bg-surface px-5 py-4">
        <div>
          <p className="text-[15px] font-semibold text-ink">{me.patient_name}</p>
          <p className="text-[12.5px] text-ink-muted">{me.hospital_number}</p>
        </div>
        <button
          type="button"
          onClick={() => logout.mutateAsync().then(() => window.location.reload())}
          className="text-[13px] font-medium text-accent hover:underline"
        >
          Sign out
        </button>
      </div>

      <Card
        title="Your results"
        hint="Only results a laboratory scientist has checked and signed appear here."
      >
        {results.isPending ? (
          <p className="text-[13px] text-ink-muted">Loading…</p>
        ) : (results.data ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">
            You have no checked results yet. A result being absent does not mean it
            is normal — it means nobody has signed it off, and the hospital will be
            in touch.
          </p>
        ) : (
          <ul className="grid gap-3">
            {(results.data ?? []).map((result: PortalResult) => (
              <li key={result.id} className="border-b border-border pb-3 last:border-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[14px] font-medium text-ink">
                    {result.parameter}
                  </span>
                  <span
                    className={`text-[15px] font-semibold tabular-nums ${
                      result.flag && result.flag !== 'normal'
                        ? 'text-critical' : 'text-ink'
                    }`}
                  >
                    {result.value} {result.unit}
                  </span>
                </div>
                <p className="text-[12.5px] text-ink-muted">
                  {result.test}
                  {result.reference_range && ` · usual range ${result.reference_range}`}
                </p>
                {result.laboratory_comment && (
                  <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
                    {result.laboratory_comment}
                  </p>
                )}
                <p className="mt-0.5 text-[11.5px] text-ink-faint">
                  Checked {fullDate(result.verified_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 rounded-lg border border-border bg-surface-sunken/60 px-3 py-2.5 text-[12.5px] leading-relaxed text-ink-muted">
          A result outside the usual range is often not a problem, and one inside it
          does not always mean all is well. Please do not change any medication
          because of something you read here — speak to the hospital.
        </p>
      </Card>

      <Card title="Your medication" hint="What you have been prescribed.">
        {(medication.data ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">Nothing prescribed at present.</p>
        ) : (
          <ul className="grid gap-3">
            {(medication.data ?? []).map((item: PortalMedication) => (
              <li key={item.id} className="border-b border-border pb-3 last:border-0 last:pb-0">
                <p className="text-[14px] font-medium text-ink">{item.medication}</p>
                <p className="text-[13px] text-ink">
                  {item.dose} by {item.route}, {item.times_a_day}{' '}
                  {item.times_a_day === 1 ? 'time' : 'times'} a day for {item.days}{' '}
                  {item.days === 1 ? 'day' : 'days'}
                </p>
                {item.instructions && (
                  <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-muted">
                    {item.instructions}
                  </p>
                )}
                <p className="mt-0.5 text-[11.5px] text-ink-faint">
                  Prescribed {fullDate(item.prescribed_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Your visits" hint="When you came, and why.">
        {(visits.data ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">No visits recorded.</p>
        ) : (
          <ul className="grid gap-2.5">
            {(visits.data ?? []).map((visit: PortalVisit) => (
              <li key={visit.id} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-2.5 last:border-0 last:pb-0">
                <div>
                  <p className="text-[13.5px] font-medium text-ink">
                    {fullDate(visit.arrived_at)}
                  </p>
                  <p className="text-[12.5px] text-ink-muted">
                    {visit.facility}
                    {visit.clinic && ` · ${visit.clinic}`}
                  </p>
                </div>
                <p className="max-w-[22ch] text-right text-[12.5px] text-ink-muted">
                  {visit.reason}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Your bills" hint="What you have been charged, and what is left to pay.">
        {(bills.data ?? []).length === 0 ? (
          <p className="text-[13px] text-ink-muted">You have no bills.</p>
        ) : (
          <ul className="grid gap-3">
            {(bills.data ?? []).map((bill: PortalBill) => (
              <li key={bill.id} className="border-b border-border pb-3 last:border-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13.5px] font-medium text-ink">
                    {bill.invoice_number}
                  </span>
                  <span
                    className={`text-[15px] font-semibold ${
                      Number(bill.balance) > 0 ? 'text-critical' : 'text-normal'
                    }`}
                  >
                    {Number(bill.balance) > 0
                      ? `${money(bill.balance)} to pay`
                      : 'Paid'}
                  </span>
                </div>
                <p className="text-[12.5px] text-ink-muted">
                  {bill.facility} · {fullDate(bill.created_at)} ·{' '}
                  {money(bill.total)} in total
                </p>
                {bill.items.length > 0 && (
                  <ul className="mt-1.5 grid gap-0.5">
                    {bill.items.map((item, index) => (
                      <li key={index} className="text-[12px] text-ink-muted">
                        {item.quantity} × {item.description}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-[12.5px] leading-relaxed text-ink-muted">
          Payment is taken at the hospital's cash desk. This page cannot take a
          payment and never asks for card details.
        </p>
      </Card>

      <p className="mb-8 text-center text-[12px] leading-relaxed text-ink-faint">
        You are signed in to your own records only. If you think you can see
        somebody else's information, please tell the hospital immediately.
      </p>
    </Shell>
  )
}
