"""Drain the outbound message queue.

Run from cron — every minute is fine. There is no broker and no Celery: the
queue is a table, the worker is this command, and `select_for_update(
skip_locked=True)` means two overlapping runs cannot send the same message
twice.

Deliberately not a daemon. A cron job that has stopped running is visible in
the outbox as a growing pending count; a daemon that has died quietly is
visible nowhere.
"""

from django.core.management.base import BaseCommand

from notifications import outbox


class Command(BaseCommand):
    help = "Send queued SMS and email messages, with backoff on failure."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=50,
            help="How many to attempt in this run.",
        )
        parser.add_argument(
            "--show-queue", action="store_true",
            help="Print the queue summary and send nothing.",
        )

    def handle(self, *args, **options):
        if options["show_queue"]:
            for label, value in outbox.summary().items():
                self.stdout.write(f"  {label:16} {value}")
            return

        # No provider is configured in this repository. `console_sender`
        # records that nothing actually left the building rather than
        # pretending a message was delivered — see AC-189.
        counts = outbox.send_pending(outbox.console_sender,
                                     limit=options["limit"])
        self.stdout.write(
            f"sent {counts['sent']}, retrying {counts['retrying']}, "
            f"failed {counts['failed']}, skipped {counts['skipped']}"
        )
        if counts["failed"]:
            self.stdout.write(self.style.WARNING(
                f"{counts['failed']} message(s) have given up. They are still in "
                f"the outbox, marked failed."
            ))
