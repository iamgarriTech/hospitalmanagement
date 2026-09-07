from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.db.models import Q, Value
from django.db.models.functions import Concat, Trim
from django.utils import timezone

from core.models import Coding


class NumberSequence(models.Model):
    """Configurable identifier formats (a Phase 1 configuration area).

    Allocation is serialized, so two simultaneous registrations cannot collide (AC-8).
    The unique constraint on the resulting column is the backstop.
    """

    key = models.CharField(max_length=50, unique=True)
    prefix = models.CharField(max_length=12, blank=True)
    include_year = models.BooleanField(default=True)
    width = models.PositiveSmallIntegerField(default=5)
    separator = models.CharField(max_length=2, default="/")
    next_value = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.key} (next {self.next_value})"

    def format(self, value):
        parts = [self.prefix] if self.prefix else []
        if self.include_year:
            parts.append(str(timezone.now().year))
        parts.append(str(value).zfill(self.width))
        return self.separator.join(parts)

    @classmethod
    def allocate(cls, key):
        with transaction.atomic():
            sequence = cls.objects.select_for_update().get(key=key)
            value = sequence.next_value
            sequence.next_value = value + 1
            sequence.save(update_fields=["next_value"])
            return sequence.format(value)


class Patient(models.Model):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DECEASED = "deceased"
    MERGED = "merged"
    STATUS_CHOICES = [
        (ACTIVE, "Active"),
        (INACTIVE, "Inactive"),
        (DECEASED, "Deceased"),
        (MERGED, "Merged into another record"),
    ]

    SEX_CHOICES = [
        ("female", "Female"),
        ("male", "Male"),
        ("other", "Other"),
        ("unknown", "Unknown"),
    ]
    BLOOD_GROUPS = [(g, g) for g in ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")]
    # Relevant where sickle cell disease is prevalent; optional everywhere else.
    GENOTYPES = [(g, g) for g in ("AA", "AS", "AC", "SS", "SC", "CC")]

    hospital_number = models.CharField(max_length=40, unique=True, editable=False)

    family_name = models.CharField(max_length=100)
    given_name = models.CharField(max_length=100)
    other_names = models.CharField(max_length=100, blank=True)

    date_of_birth = models.DateField(null=True, blank=True)
    date_of_birth_is_estimated = models.BooleanField(
        default=False,
        help_text="True where the patient does not know an exact date of birth.",
    )
    sex = models.CharField(max_length=10, choices=SEX_CHOICES)

    phone_primary = models.CharField(max_length=30, blank=True, db_index=True)
    phone_alternate = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    address_line = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="Nigeria")

    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, blank=True)
    genotype = models.CharField(max_length=2, choices=GENOTYPES, blank=True)

    facility = models.ForeignKey(
        "facilities.Facility",
        on_delete=models.PROTECT,
        related_name="patients",
        help_text="Where the patient was registered.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="merged_from",
        help_text="Set when this record was merged away. The record itself is kept.",
    )

    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="patients_registered",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Maintained by the database so it cannot drift from its source columns.
    search_name = models.GeneratedField(
        expression=Trim(
            Concat(
                "given_name", Value(" "), "other_names", Value(" "), "family_name"
            )
        ),
        output_field=models.TextField(),
        db_persist=True,
    )

    class Meta:
        ordering = ["family_name", "given_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(merged_into__isnull=True) | Q(status="merged"),
                name="merged_patient_has_merged_status",
            ),
            models.CheckConstraint(
                condition=~Q(merged_into=models.F("id")),
                name="patient_not_merged_into_itself",
            ),
        ]
        indexes = [
            models.Index(fields=["family_name", "given_name"]),
            models.Index(fields=["date_of_birth"]),
            # Declared here as well as in migration 0002, or the autodetector treats the
            # index as stray state and drops it on the next unrelated Meta change.
            GinIndex(
                name="patient_search_name_trgm",
                fields=["search_name"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                name="patient_phone_trgm",
                fields=["phone_primary"],
                opclasses=["gin_trgm_ops"],
            ),
        ]
        permissions = [
            ("merge_patient", "Can merge duplicate patient records"),
            ("register_duplicate_patient", "Can register a patient despite a suspected duplicate"),
            ("view_patient_access_log", "Can see who has accessed a patient record"),
        ]

    def __str__(self):
        return f"{self.hospital_number} — {self.full_name}"

    @property
    def full_name(self):
        return " ".join(
            part for part in (self.given_name, self.other_names, self.family_name) if part
        )

    @property
    def age_years(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        return (
            today.year
            - self.date_of_birth.year
            - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        )

    def save(self, *args, **kwargs):
        if not self.hospital_number:
            self.hospital_number = NumberSequence.allocate("hospital_number")
        self.hospital_number = self.hospital_number.upper()
        return super().save(*args, **kwargs)


class PatientAllergy(Coding):
    """Shown on every clinical screen's patient header, and checked at prescribing."""

    SEVERITIES = [("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    substance = models.CharField(max_length=200)
    reaction = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITIES, blank=True)
    is_active = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta:
        verbose_name_plural = "patient allergies"
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.substance} ({self.severity or 'unspecified'})"


class PatientChronicCondition(Coding):
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="chronic_conditions"
    )
    condition = models.CharField(max_length=200)
    noted_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return self.condition


class NextOfKin(models.Model):
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="next_of_kin"
    )
    full_name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_emergency_contact = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "next of kin"

    def __str__(self):
        return f"{self.full_name} ({self.relationship})"
