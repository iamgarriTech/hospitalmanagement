"""No tables of its own — the facade reads the hospital's records.

The model below exists only to carry a permission, the same way
`reporting.ReportAccess` does. "May read the hospital through the external
API" is a distinct grant from any internal one: it is the surface a laboratory
analyser or a national reporting system reaches, and a hospital needs to be
able to give an integration exactly that and nothing else.
"""

from django.db import models


class ExternalApiAccess(models.Model):
    """A permission holder, not a record. No table is created."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("use_external_api", "Can read through the external API facade"),
        ]
        verbose_name_plural = "external API access"

    def __str__(self):
        return "external API access"
