import Link from 'next/link'
import { AlertIcon } from './icons'
import { Badge } from './ui'

type HeaderPatient = {
  id: number
  hospital_number: string
  full_name: string
  sex: string
  age_years: number | null
  date_of_birth: string | null
  date_of_birth_is_estimated: boolean
  status: string
  blood_group?: string
  genotype?: string
  allergies?: { substance: string; reaction: string; severity: string; is_active: boolean }[]
  merged_into_hospital_number?: string | null
}

/**
 * The identity strip that sits above every clinical screen.
 *
 * Allergies are not tucked into a tab. A clinician about to prescribe, a nurse
 * about to give a drug and a pharmacist about to dispense must all see them
 * without deciding to look — so they get a red band, the reaction, and an icon
 * as well as the colour.
 *
 * Blood group and genotype sit here too because in this setting they are asked
 * for constantly and are useless if they take a click to find.
 */
export function PatientHeader({
  patient,
  action,
}: {
  patient: HeaderPatient
  action?: React.ReactNode
}) {
  const allergies = (patient.allergies ?? []).filter((entry) => entry.is_active)
  const severe = allergies.some((entry) => entry.severity === 'severe')

  return (
    <div className="overflow-hidden rounded-2xl border border-border bg-surface shadow-card">
      {patient.merged_into_hospital_number && (
        <p className="flex items-center gap-2 border-b border-border bg-abnormal-muted px-5 py-2.5 text-[12.5px] font-medium text-abnormal">
          <AlertIcon className="size-4 shrink-0" />
          This record was merged into {patient.merged_into_hospital_number}. It is kept for
          reference only — use the surviving record.
        </p>
      )}

      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[20px] leading-tight font-bold text-ink">{patient.full_name}</h2>
            {patient.status !== 'active' && <Badge tone="idle">{patient.status}</Badge>}
          </div>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-muted">
            <Link
              href={`/patients/${patient.id}`}
              className="font-mono text-[12px] font-semibold text-accent hover:underline"
            >
              {patient.hospital_number}
            </Link>
            <span className="capitalize">{patient.sex}</span>
            <span>
              {patient.age_years === null ? 'Age unknown' : `${patient.age_years} years`}
              {patient.date_of_birth_is_estimated && (
                <span className="ml-1 text-ink-faint">(estimated)</span>
              )}
            </span>
            {patient.blood_group && (
              <span>
                Blood group <span className="font-semibold text-ink">{patient.blood_group}</span>
              </span>
            )}
            {patient.genotype && (
              <span>
                Genotype <span className="font-semibold text-ink">{patient.genotype}</span>
              </span>
            )}
          </p>
        </div>
        {action}
      </div>

      {allergies.length > 0 ? (
        <div
          className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t px-5 py-2.5 ${
            severe ? 'border-critical/30 bg-critical-muted' : 'border-abnormal/30 bg-abnormal-muted'
          }`}
        >
          <span
            className={`inline-flex items-center gap-1.5 text-[11px] font-bold tracking-[0.08em] uppercase ${
              severe ? 'text-critical' : 'text-abnormal'
            }`}
          >
            <AlertIcon className="size-3.5" />
            Allergies
          </span>
          {allergies.map((entry) => (
            <span
              key={entry.substance}
              className={`text-[12.5px] font-semibold ${severe ? 'text-critical' : 'text-abnormal'}`}
            >
              {entry.substance}
              {entry.reaction && (
                <span className="font-normal opacity-80"> — {entry.reaction}</span>
              )}
              {entry.severity === 'severe' && (
                <span className="ml-1 text-[10.5px] font-bold uppercase">severe</span>
              )}
            </span>
          ))}
        </div>
      ) : (
        /* Said explicitly. "No allergies recorded" and "nobody has asked" are
           different facts, and a blank space reads as the first. */
        <p className="border-t border-border px-5 py-2 text-[12px] text-ink-faint">
          No allergies recorded.
        </p>
      )}
    </div>
  )
}
