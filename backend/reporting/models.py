"""No tables.

Reports are live queries over the other apps — AC-178 forbids serving one
from a stored aggregate that could drift from the records it summarises, so
there is nothing here to store.

The model below exists only to hang a permission on. Django attaches
permissions to models, and "may open the reports section at all" is a real
permission that belongs to no other app. `managed = False` means no table is
ever created for it.
"""

from django.db import models


class ReportAccess(models.Model):
    """A permission holder, not a record. No table is created."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("view_reports", "Can open the reports section"),
        ]
        verbose_name_plural = "report access"

    def __str__(self):
        # Never instantiated; the linter asks for one and it costs nothing.
        return "report access"
