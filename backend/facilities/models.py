from django.db import models


class Organization(models.Model):
    """The hospital group. One per deployment — tenancy is a deployment boundary."""

    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Facility(models.Model):
    """A site: hospital, branch, clinic building, diagnostic centre.

    Prices, services, inventory and staffing vary by facility, and access is scoped to
    it. Operational records reach their facility through this model.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="facilities"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True)
    timezone = models.CharField(
        max_length=64,
        default="Africa/Lagos",
        help_text="Timestamps are stored in UTC and rendered in this zone.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "facilities"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Department(models.Model):
    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="departments"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"], name="department_code_unique_per_facility"
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.facility.code}"


class Clinic(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="clinics"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["department", "code"], name="clinic_code_unique_per_department"
            )
        ]
        ordering = ["name"]

    @property
    def facility(self):
        return self.department.facility

    def __str__(self):
        return self.name
