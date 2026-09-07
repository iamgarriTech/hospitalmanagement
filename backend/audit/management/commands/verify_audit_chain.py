from django.core.management.base import BaseCommand

from audit.models import AuditEvent


class Command(BaseCommand):
    help = "Verify the audit log hash chain and report any tampering."

    def handle(self, *args, **options):
        total = AuditEvent.objects.count()
        ok, problems = AuditEvent.verify_chain()
        if ok:
            self.stdout.write(self.style.SUCCESS(f"Chain intact across {total} events."))
            return
        self.stderr.write(self.style.ERROR(f"Chain broken ({len(problems)} problems):"))
        for problem in problems:
            self.stderr.write(f"  - {problem}")
        raise SystemExit(1)
