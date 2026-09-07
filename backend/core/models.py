from django.db import models


class Coding(models.Model):
    """A value carrying the terminology it came from.

    Stored as system + code + display + version rather than a bare string, so a record
    coded today does not re-render differently under a future code set, and so more than
    one terminology can coexist (ICD-10 now, SNOMED where a deployment licenses it).
    """

    code_system = models.CharField(
        max_length=64, blank=True, help_text="e.g. ICD-10, LOINC, ATC"
    )
    code = models.CharField(max_length=64, blank=True)
    code_display = models.CharField(max_length=255, blank=True)
    code_version = models.CharField(
        max_length=32, blank=True, help_text="Release of the code system used."
    )

    class Meta:
        abstract = True

    @property
    def coding(self):
        if not self.code:
            return None
        return {
            "system": self.code_system,
            "code": self.code,
            "display": self.code_display,
            "version": self.code_version,
        }
