"""Write the emergency ward snapshots. Run from cron, not by hand.

Every 15 minutes is a reasonable default: a snapshot older than that is worse
than useless on a ward round, and more often than that writes patient data to
disk more than the clinical purpose needs.
"""
from django.core.management.base import BaseCommand

from inpatient.models import Ward
from inpatient.snapshot import snapshot_root, write_ward_snapshot


class Command(BaseCommand):
    help = "Write a read-only HTML snapshot of each active ward's inpatients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--facility", help="Limit to one facility, by code.", default=None
        )
        parser.add_argument(
            "--ward", help="Limit to one ward, by code.", default=None
        )

    def handle(self, *args, **options):
        wards = Ward.objects.filter(is_active=True).select_related("facility")
        if options["facility"]:
            wards = wards.filter(facility__code=options["facility"])
        if options["ward"]:
            wards = wards.filter(code=options["ward"])

        if not wards.exists():
            self.stderr.write("No active wards matched.")
            return

        for ward in wards:
            path = write_ward_snapshot(ward)
            self.stdout.write(f"{ward.facility.code}/{ward.code} → {path}")
        self.stdout.write(
            self.style.SUCCESS(f"{wards.count()} snapshot(s) in {snapshot_root()}")
        )
