"""The per-ward read-only snapshot.

The connectivity decision rules out offline write replication — two nurses
recording different outcomes for one dose have no safe automatic merge, and
picking wrong is a patient-safety event. What it promises instead is that total
server failure must not leave a ward blind, and this is that promise: a
self-contained HTML file per ward, written to disk on a schedule, openable in a
browser with no server, no network and no database.

It is deliberately a **file**, not an endpoint. An endpoint that needs the
application running answers a different question from the one being asked here.

The tradeoff is real and worth stating plainly: this puts patient names,
allergies and diagnoses in a file outside the database, where the audit log
cannot see it being read. It is scoped as narrowly as the clinical purpose
allows — the current occupants of one ward, nothing historical, no contact
details, no financial data — the file is written owner-and-group readable only,
and `WARD_SNAPSHOT_ROOT` is a setting so a deployment can put it on an encrypted
volume. A ward that cannot find out what its patients are allergic to is the
worse risk, but it is a choice, not a free win.
"""
import html
import os
from pathlib import Path

from django.conf import settings
from django.utils import timezone


def snapshot_root():
    root = Path(
        getattr(settings, "WARD_SNAPSHOT_ROOT", None) or settings.BASE_DIR / "snapshots"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def ward_snapshot_data(ward):
    """Everything the snapshot shows, assembled from the live record.

    Only what a ward needs to keep working without a screen: who is in which
    bed, what they must not be given, what they are on, why they are here and
    who is responsible for them.
    """
    from .models import Bed, BedOccupancy, ScheduledDose

    occupancies = (
        BedOccupancy.objects.filter(
            bed__room__ward=ward, period__endswith__isnull=True
        )
        .select_related(
            "bed__room", "patient", "admission__responsible_consultant"
        )
        .prefetch_related("patient__allergies")
        .order_by("bed__room__code", "bed__code")
    )

    rows = []
    for occupancy in occupancies:
        admission = occupancy.admission
        # Active medication, by name and directions — enough to carry on giving
        # it, not enough to prescribe from.
        medication = []
        seen = set()
        for dose in ScheduledDose.objects.filter(
            admission=admission, cancelled_at__isnull=True
        ).select_related("prescription_item__medication").order_by("due_at"):
            item = dose.prescription_item
            if item.pk in seen or item.status == "cancelled":
                continue
            seen.add(item.pk)
            medication.append(
                f"{item.medication} — {item.dose_unit and ''}"
                f"{item.route}, {item.frequency_per_day}/day"
            )

        rows.append({
            "bed": str(occupancy.bed),
            "room": occupancy.bed.room.code,
            "name": occupancy.patient.full_name,
            "hospital_number": occupancy.patient.hospital_number,
            "sex": occupancy.patient.get_sex_display(),
            "age_years": occupancy.patient.age_years,
            "allergies": [
                allergy.substance
                for allergy in occupancy.patient.allergies.all()
                if allergy.is_active
            ] or ["None recorded"],
            "diagnosis": admission.admission_diagnosis,
            "consultant": admission.responsible_consultant.full_name,
            "admission_number": admission.admission_number,
            "admitted_at": occupancy.period.lower,
            "medication": medication or ["None on the chart"],
        })

    return {
        "ward": ward.name,
        "code": ward.code,
        "facility": ward.facility.name,
        "generated_at": timezone.now(),
        "beds_total": Bed.objects.filter(room__ward=ward, is_active=True).count(),
        "patients": rows,
    }


def render(data):
    """A single self-contained HTML file: no stylesheet, no script, no fonts.

    Everything is inline because the file has to render from a USB stick on a
    machine with no network. Styled for paper as well as screen — the realistic
    use of this file is that somebody prints it.
    """
    def esc(value):
        return html.escape(str(value))

    rows = []
    for patient in data["patients"]:
        allergies = ", ".join(esc(item) for item in patient["allergies"])
        allergy_class = (
            "none" if patient["allergies"] == ["None recorded"] else "allergy"
        )
        medication = "<br>".join(esc(item) for item in patient["medication"])
        rows.append(f"""
      <tr>
        <td class="bed">{esc(patient['bed'])}</td>
        <td>
          <strong>{esc(patient['name'])}</strong><br>
          <span class="muted">{esc(patient['hospital_number'])} ·
          {esc(patient['sex'])} · {esc(patient['age_years'])}y ·
          {esc(patient['admission_number'])}</span>
        </td>
        <td class="{allergy_class}">{allergies}</td>
        <td>{esc(patient['diagnosis'])}<br>
          <span class="muted">{esc(patient['consultant'])}</span></td>
        <td class="drugs">{medication}</td>
      </tr>""")

    body = "".join(rows) or (
        '<tr><td colspan="5" class="muted">No patients on this ward.</td></tr>'
    )
    stamp = data["generated_at"].strftime("%d %b %Y %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{esc(data['code'])} ward snapshot — {stamp}</title>
<style>
  body {{ font: 13px/1.45 -apple-system, Segoe UI, Roboto, sans-serif;
          margin: 24px; color: #14181f; }}
  h1 {{ font-size: 19px; margin: 0 0 2px; }}
  .stamp {{ color: #6b7280; margin: 0 0 4px; }}
  .warn {{ border: 1px solid #b45309; background: #fffbeb; color: #7c2d12;
           padding: 8px 10px; margin: 12px 0 16px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #d1d5db; padding: 6px 8px;
            vertical-align: top; text-align: left; }}
  th {{ background: #f3f4f6; font-size: 11px; text-transform: uppercase;
        letter-spacing: .04em; }}
  .bed {{ font-weight: 700; white-space: nowrap; }}
  .muted {{ color: #6b7280; font-size: 11px; }}
  .allergy {{ background: #fef2f2; color: #991b1b; font-weight: 600; }}
  .none {{ color: #6b7280; }}
  .drugs {{ font-size: 11px; }}
  @media print {{ body {{ margin: 0; font-size: 11px; }} .warn {{ border-width: 2px; }} }}
</style></head><body>
<h1>{esc(data['ward'])} ({esc(data['code'])}) — {esc(data['facility'])}</h1>
<p class="stamp">{len(data['patients'])} of {data['beds_total']} beds occupied ·
generated {stamp}</p>
<div class="warn"><strong>Emergency snapshot. Read-only, and out of date the
moment it was written ({stamp}).</strong> Nothing recorded on paper while the
system is down is in the system. Enter it when the system returns.</div>
<table>
  <thead><tr>
    <th>Bed</th><th>Patient</th><th>Allergies</th>
    <th>Working diagnosis / consultant</th><th>Active medication</th>
  </tr></thead>
  <tbody>{body}
  </tbody>
</table>
</body></html>
"""


def write_ward_snapshot(ward):
    """Write one ward's snapshot and return the path.

    Written to a temporary name and renamed into place, so a ward opening the
    file while it is being regenerated never reads half a page.
    """
    data = ward_snapshot_data(ward)
    target = snapshot_root() / f"ward-{ward.facility.code}-{ward.code}.html"
    staging = target.with_suffix(".html.partial")
    staging.write_text(render(data), encoding="utf-8")
    # Patient data on disk: not world-readable.
    os.chmod(staging, 0o640)
    staging.replace(target)
    return target
