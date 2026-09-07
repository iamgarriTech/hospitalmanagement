'use client'

import Link from 'next/link'
import { useState } from 'react'
import { AlertIcon, SearchIcon } from '@/components/icons'
import { PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, EmptyState, Input, Panel } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { usePatientSearch } from '@/lib/queries'
import { useDebounced } from '@/lib/useDebounced'

/**
 * Patient search.
 *
 * One box, because reception types whatever the patient handed them — a
 * hospital number, a phone number, a name, a date of birth — and being made to
 * pick a field first is a step that exists only for the database's benefit.
 */
export default function PatientsPage() {
  const { can } = useAuth()
  const [term, setTerm] = useState('')
  const held = useDebounced(term.trim())
  const search = usePatientSearch(held, can('patients.view_patient'))

  const rows = search.data?.results ?? []
  const total = search.data?.count ?? 0

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Medical records
      </div>
      <PageHeading
        title="Patients"
        subtitle="Search by hospital number, name, phone number, or date of birth."
        action={
          can('patients.add_patient') && (
            <Link
              href="/patients/new"
              className="inline-flex items-center justify-center rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
            >
              Register a patient
            </Link>
          )
        }
      />

      <div className="mt-6 max-w-xl">
        <label htmlFor="patient-search" className="sr-only">
          Search patients
        </label>
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" />
          <Input
            id="patient-search"
            type="search"
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="ILS/2026/00001, 08031234567, Amina Yusuf, 1991-04-17"
            className="py-2.5 pl-9"
          />
        </div>
        {held && (
          <p className="mt-2 text-[12px] text-ink-muted" role="status">
            {search.isFetching
              ? 'Searching…'
              : `${total} match${total === 1 ? '' : 'es'} for “${held}”`}
          </p>
        )}
      </div>

      <Panel className="mt-5">
        {!held ? (
          <div className="p-5">
            <EmptyState>Type at least part of a name, number or date to search.</EmptyState>
          </div>
        ) : search.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">
            Searching…
          </p>
        ) : search.isError ? (
          <p role="alert" className="px-5 py-10 text-center text-[13px] text-ink-muted">
            Unable to search right now.
          </p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>
              Nobody matches “{held}”.
              {can('patients.add_patient') && (
                <>
                  {' '}
                  <Link href="/patients/new" className="font-semibold text-accent hover:underline">
                    Register a new patient
                  </Link>
                  .
                </>
              )}
            </EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={820}>
            <thead>
              <tr>
                <Th>Hospital number</Th>
                <Th>Name</Th>
                <Th>Sex</Th>
                <Th>Age</Th>
                <Th>Phone</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="hover:bg-surface-muted/50">
                  <Td className="font-mono text-[11.5px]">
                    <Link
                      href={`/patients/${row.id}`}
                      className="font-semibold text-accent hover:underline"
                    >
                      {row.hospital_number}
                    </Link>
                  </Td>
                  <Td className="font-semibold">{row.full_name}</Td>
                  <Td className="text-ink-muted capitalize">{row.sex}</Td>
                  <Td className="text-ink-muted">
                    {row.age_years === null ? (
                      <span className="text-ink-faint">Unknown</span>
                    ) : (
                      <>
                        {row.age_years}y
                        {row.date_of_birth_is_estimated && (
                          <span className="ml-1 text-[10.5px] text-ink-faint">est.</span>
                        )}
                      </>
                    )}
                  </Td>
                  <Td className="text-ink-muted">{row.phone_primary || '—'}</Td>
                  <Td>
                    {row.status === 'active' ? (
                      <Badge tone="normal">Active</Badge>
                    ) : row.status === 'merged' ? (
                      <Badge tone="idle">
                        <AlertIcon className="size-3" />
                        Merged
                      </Badge>
                    ) : (
                      <Badge tone="idle" >{row.status}</Badge>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}
