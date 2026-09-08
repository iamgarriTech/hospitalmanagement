'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useState } from 'react'
import { ErrorNotice, LoadingNotice, PageHeading, PageShell } from '@/components/PageShell'
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Panel,
  PanelHeader,
  Select,
  Textarea,
} from '@/components/ui'
import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import {
  type AdmissionRequestRow,
  useAdmit,
  useBeds,
  useDeclineAdmissionRequest,
  usePendingAdmissionRequests,
  useWards,
} from '@/lib/inpatient'
import { dateAndTime, waitedFor } from '@/lib/workflow'

/**
 * Requests waiting for a bed.
 *
 * A request and an admission are separate on purpose: a clinician decides a
 * patient needs a bed, and the ward decides which bed and when. So this screen
 * is the ward's, not the requesting clinician's — its job is to turn a queue of
 * requests into allocated beds, urgent first and longest-waiting after that.
 *
 * Admitting from a request carries the reason, diagnosis, consultant and
 * originating visit forward. Nothing clinical is retyped here, because a
 * retyped diagnosis is a different diagnosis.
 */
export default function AdmissionRequestsPage() {
  const { can } = useAuth()
  const wards = useWards()
  const [wardFilter, setWardFilter] = useState<number | null>(null)
  const requests = usePendingAdmissionRequests(wardFilter ?? undefined)
  const searchParams = useSearchParams()
  const preselectedBed = Number(searchParams.get('bed')) || null

  const rows = requests.data ?? []
  const urgent = rows.filter((row) => row.priority === 'urgent').length

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Inpatient
      </div>
      <PageHeading
        title="Admission requests"
        subtitle="Patients a clinician has asked to admit, waiting for a bed."
        action={
          <Link
            href="/wards"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[13px] font-semibold text-ink hover:bg-surface-muted"
          >
            Bed board
          </Link>
        }
      />

      <div className="mb-5 max-w-xs">
        <Field label="Ward">
          <Select
            value={wardFilter ?? ''}
            onChange={(event) =>
              setWardFilter(event.target.value ? Number(event.target.value) : null)
            }
          >
            <option value="">All wards</option>
            {wards.data?.map((ward) => (
              <option key={ward.id} value={ward.id}>
                {ward.name} — {ward.occupancy.available} free
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {requests.isError && <ErrorNotice>Could not load the requests.</ErrorNotice>}
      {requests.isLoading && <LoadingNotice>Loading requests…</LoadingNotice>}

      {rows.length === 0 && !requests.isLoading && (
        <EmptyState>
          No requests are waiting for a bed. A clinician creates one from the
          patient&apos;s record when they decide someone needs admitting.
        </EmptyState>
      )}

      {rows.length > 0 && (
        <>
          {urgent > 0 && (
            <p className="mb-4 rounded-md border border-abnormal/30 bg-abnormal-muted px-4 py-3 text-[12.5px] font-medium text-abnormal">
              {urgent} urgent request{urgent === 1 ? '' : 's'} waiting.
            </p>
          )}
          <ul className="space-y-4">
            {rows.map((request) => (
              <li key={request.id}>
                <RequestCard
                  request={request}
                  canAdmit={can('inpatient.admit_patient')}
                  canDecide={can('inpatient.decide_admissionrequest')}
                  preselectedBed={preselectedBed}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </PageShell>
  )
}

function RequestCard({
  request,
  canAdmit,
  canDecide,
  preselectedBed,
}: {
  request: AdmissionRequestRow
  canAdmit: boolean
  canDecide: boolean
  preselectedBed: number | null
}) {
  const router = useRouter()
  const admit = useAdmit()
  const decline = useDeclineAdmissionRequest()
  // Only beds that can actually take a patient: in service, not being cleaned
  // or repaired, and empty.
  const beds = useBeds({ ward: String(request.ward), state: 'available' })
  const [bedId, setBedId] = useState<number | null>(preselectedBed)
  const [declining, setDeclining] = useState(false)
  const [reason, setReason] = useState('')

  const admitError =
    admit.error instanceof ApiError
      ? Object.values(admit.error.fields).flat().join(' ') || admit.error.message
      : null
  const declineError =
    decline.error instanceof ApiError ? decline.error.message : null

  const options = beds.data ?? []

  return (
    <Panel>
      <PanelHeader
        title={request.patient_detail.full_name}
        hint={
          <>
            {request.patient_detail.hospital_number} ·{' '}
            {request.patient_detail.sex}
            {request.patient_detail.age_years !== null &&
              ` · ${request.patient_detail.age_years}y`}{' '}
            · requested by {request.requested_by_name} ·{' '}
            {dateAndTime(request.requested_at)}
          </>
        }
        action={
          <div className="flex items-center gap-2">
            {request.priority === 'urgent' && <Badge tone="critical">Urgent</Badge>}
            <Badge tone={request.waiting_minutes > 240 ? 'abnormal' : 'idle'}>
              Waiting {waitedFor(request.waiting_minutes)}
            </Badge>
          </div>
        }
      />
      <div className="grid gap-5 p-5 lg:grid-cols-2">
        <dl className="space-y-3 text-[13px]">
          <div>
            <dt className="text-[11.5px] font-semibold text-ink-muted">
              Working diagnosis
            </dt>
            <dd className="mt-0.5 text-ink">{request.working_diagnosis}</dd>
          </div>
          <div>
            <dt className="text-[11.5px] font-semibold text-ink-muted">
              Reason for admission
            </dt>
            <dd className="mt-0.5 leading-relaxed text-ink">{request.reason}</dd>
          </div>
          <div>
            <dt className="text-[11.5px] font-semibold text-ink-muted">
              Responsible consultant
            </dt>
            <dd className="mt-0.5 text-ink">{request.consultant_name}</dd>
          </div>
          <div>
            <dt className="text-[11.5px] font-semibold text-ink-muted">Ward requested</dt>
            <dd className="mt-0.5 text-ink">{request.ward_name}</dd>
          </div>
          {request.allergies.length ? (
            <div>
              <dt className="text-[11.5px] font-semibold text-critical">Allergies</dt>
              <dd className="mt-0.5 font-semibold text-critical">
                <span aria-hidden>▲ </span>
                {request.allergies.join(', ')}
              </dd>
            </div>
          ) : null}
        </dl>

        <div className="space-y-3 rounded-xl bg-surface-muted/50 p-4">
          {!canAdmit && !canDecide && (
            <p className="text-[12.5px] text-ink-muted">
              You can see this request but not act on it.
            </p>
          )}

          {canAdmit && (
            <>
              {admitError && <p role="alert" className="text-[12.5px] font-medium text-critical">{admitError}</p>}
              <Field
                label="Bed"
                hint={
                  options.length
                    ? 'Only beds that can take a patient now are listed.'
                    : 'No bed on this ward is free. Free one on the board, or move the request.'
                }
                required
              >
                <Select
                  value={bedId ?? ''}
                  onChange={(event) =>
                    setBedId(event.target.value ? Number(event.target.value) : null)
                  }
                  disabled={options.length === 0}
                >
                  <option value="">Choose a bed…</option>
                  {options.map((bed) => (
                    <option key={bed.id} value={bed.id}>
                      {bed.label} (room {bed.room_code})
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                disabled={bedId === null || admit.isPending}
                onClick={() =>
                  admit.mutate(
                    { request: request.id, bed: bedId as number },
                    {
                      onSuccess: (admission) => router.push(`/wards/${admission.id}`),
                    },
                  )
                }
              >
                {admit.isPending ? 'Admitting…' : 'Admit into this bed'}
              </Button>
              <p className="text-[11px] leading-relaxed text-ink-faint">
                The diagnosis, reason, consultant and originating visit carry
                forward from the request. Nothing is retyped.
              </p>
            </>
          )}

          {canDecide && (
            <div className="border-t border-border pt-3">
              {declineError && (
                <p role="alert" className="mb-2 text-[12.5px] font-medium text-critical">
                  {declineError}
                </p>
              )}
              {declining ? (
                <div className="space-y-2">
                  <Field
                    label="Why is this being declined?"
                    hint="Recorded on the request and audited."
                    required
                  >
                    <Textarea
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="No isolation bed available; referred to Ikeja."
                    />
                  </Field>
                  <div className="flex gap-2">
                    <Button
                      variant="danger"
                      disabled={!reason.trim() || decline.isPending}
                      onClick={() =>
                        decline.mutate({ id: request.id, reason: reason.trim() })
                      }
                    >
                      Decline request
                    </Button>
                    <Button variant="ghost" onClick={() => setDeclining(false)}>
                      Keep it
                    </Button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setDeclining(true)}
                  className="text-[12px] font-medium text-ink-muted hover:text-critical"
                >
                  Decline this request
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </Panel>
  )
}
