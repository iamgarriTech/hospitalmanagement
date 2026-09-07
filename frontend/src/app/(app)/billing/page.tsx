'use client'

import Link from 'next/link'
import { PageHeading, PageShell, TableFrame, Td, Th } from '@/components/PageShell'
import { Badge, Button, EmptyState, Panel, PanelHeader } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { useCashierSessions } from '@/lib/billing'
import { useOutstandingInvoices } from '@/lib/queries'
import { money, shortMoney } from '@/lib/workflow'

/**
 * The cash desk.
 *
 * Largest balance first, because that is the collection priority — and the
 * total outstanding is stated rather than left to be added up mentally.
 */
export default function BillingPage() {
  const { can } = useAuth()
  const invoices = useOutstandingInvoices()
  const sessions = useCashierSessions(can('billing.view_cashiersession'))

  const rows = [...(invoices.data ?? [])].sort((a, b) => Number(b.balance) - Number(a.balance))
  const total = rows.reduce((sum, invoice) => sum + Number(invoice.balance), 0)
  const openSession = (sessions.data ?? []).find((session) => session.status === 'open')

  return (
    <PageShell>
      <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-[0.1em] text-accent uppercase">
        Cash desk
      </div>
      <PageHeading
        title="Outstanding invoices"
        subtitle={
          invoices.isLoading
            ? 'Loading…'
            : `${rows.length} unpaid · ${money(total)} outstanding`
        }
        action={
          <div className="flex gap-2">
            {can('billing.view_cashiersession') && (
              <Link
                href="/billing/till"
                className={`inline-flex items-center rounded-lg px-3 py-2 text-[13px] font-semibold ${
                  openSession
                    ? 'border border-border text-ink hover:bg-surface-muted'
                    : 'bg-accent text-white hover:bg-accent-hover'
                }`}
              >
                {openSession ? 'My till' : 'Open a till'}
              </Link>
            )}
            <Button variant="secondary" onClick={() => invoices.refetch()} disabled={invoices.isFetching}>
              {invoices.isFetching ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      {!openSession && can('billing.add_payment') && (
        <p className="mt-5 rounded-lg border border-abnormal/30 bg-abnormal-muted px-4 py-3 text-[12.5px] font-medium text-abnormal">
          You have no open till. Payments have to land in a cashier session so the day can be
          reconciled — open one before taking money.
        </p>
      )}

      <Panel className="mt-5">
        <PanelHeader title="Unpaid" hint="Largest balance first" />
        {invoices.isLoading ? (
          <p role="status" className="px-5 py-10 text-center text-[13px] text-ink-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>Nothing outstanding.</EmptyState>
          </div>
        ) : (
          <TableFrame minWidth={860}>
            <thead>
              <tr>
                <Th>Invoice</Th>
                <Th>Patient</Th>
                <Th>Status</Th>
                <Th className="text-right">Total</Th>
                <Th className="text-right">Paid</Th>
                <Th className="text-right">Balance</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((invoice) => (
                <tr key={invoice.id} className="hover:bg-surface-muted/50">
                  <Td className="font-mono text-[11.5px]">
                    <Link
                      href={`/billing/${invoice.id}`}
                      className="font-semibold text-accent hover:underline"
                    >
                      {invoice.invoice_number}
                    </Link>
                  </Td>
                  <Td>
                    <span className="font-semibold">{invoice.patient_name}</span>
                    <div className="text-[11px] text-ink-faint">{invoice.hospital_number}</div>
                  </Td>
                  <Td>
                    <Badge tone={invoice.status === 'draft' ? 'idle' : 'abnormal'}>
                      {invoice.status === 'draft' ? 'Draft' : 'Unpaid'}
                    </Badge>
                  </Td>
                  <Td className="text-right text-ink-muted">{money(invoice.total)}</Td>
                  <Td className="text-right text-ink-muted">{money(invoice.amount_paid)}</Td>
                  <Td className="text-right font-semibold text-abnormal">
                    {money(invoice.balance)}
                  </Td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <Td className="font-semibold" />
                <Td />
                <Td />
                <Td />
                <Td className="text-right text-[11px] tracking-wide text-ink-muted uppercase">
                  Total
                </Td>
                <Td className="text-right text-[15px] font-bold text-ink">{shortMoney(total)}</Td>
              </tr>
            </tfoot>
          </TableFrame>
        )}
      </Panel>
    </PageShell>
  )
}
