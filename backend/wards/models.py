"""Wards, rooms, beds and who is in them.

Two modelling decisions carry this whole phase.

**Occupancy is a period, and the database refuses overlaps.** A bed occupancy is
a `tstzrange` and an exclusion constraint forbids two overlapping ranges on the
same bed. Two patients in one bed is therefore not something the application
prevents — it is something PostgreSQL will not store, however many nurses press
Admit at the same instant. Application-level checking here would be a race
waiting to happen, and the failure mode is a patient in someone else's bed.

**"Occupied" is derived, never stored.** A bed carries only its *service* state —
available, reserved, being cleaned, unavailable for maintenance — and whether it
is occupied comes from whether an open occupancy exists. A boolean saying
"occupied" alongside a row saying who is in it is two sources of truth that will
disagree eventually, and the disagreement would be discovered by putting someone
in an occupied bed.
"""
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone


class Ward(models.Model):
    GENERAL = "general"
    MALE = "male"
    FEMALE = "female"
    PAEDIATRIC = "paediatric"
    MATERNITY = "maternity"
    INTENSIVE = "intensive"
    ISOLATION = "isolation"
    TYPE_CHOICES = [
        (GENERAL, "General"), (MALE, "Male"), (FEMALE, "Female"),
        (PAEDIATRIC, "Paediatric"), (MATERNITY, "Maternity"),
        (INTENSIVE, "Intensive care"), (ISOLATION, "Isolation"),
    ]

    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="wards"
    )
    department = models.ForeignKey(
        "facilities.Department", on_delete=models.PROTECT, null=True, blank=True,
        related_name="wards",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    ward_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default=GENERAL)

    # Bed nights are billed through the ordinary service and price machinery, so
    # a ward's rate is per facility and changes are audited like any other price.
    nightly_service = models.ForeignKey(
        "billing.Service", on_delete=models.PROTECT, null=True, blank=True,
        related_name="wards", help_text="Service used to charge each bed night.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["facility", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"], name="ward_code_unique_per_facility"
            )
        ]
        permissions = [
            ("manage_beds", "Can change bed availability and take beds out of service"),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def bed_count(self):
        return Bed.objects.filter(room__ward=self, is_active=True).count()

    def occupancy(self):
        """Derived from live occupancies, never from a counter.

        A stored count is a second source of truth that drifts, and the way you
        find out it has drifted is by allocating an occupied bed.
        """
        beds = Bed.objects.filter(room__ward=self, is_active=True)
        occupied = BedOccupancy.objects.filter(
            bed__in=beds, period__endswith__isnull=True
        ).count()
        states = {}
        for bed in beds.select_related("room"):
            states[bed.state] = states.get(bed.state, 0) + 1
        return {
            "beds": beds.count(),
            "occupied": occupied,
            "available": states.get(Bed.AVAILABLE, 0),
            "reserved": states.get(Bed.RESERVED, 0),
            "cleaning": states.get(Bed.CLEANING, 0),
            "maintenance": states.get(Bed.MAINTENANCE, 0),
        }


class Room(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.PROTECT, related_name="rooms")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ward", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["ward", "code"], name="room_code_unique_per_ward"
            )
        ]

    def __str__(self):
        return f"{self.ward.code}/{self.code}"


class Bed(models.Model):
    """A bed, and what it is available for.

    Deliberately no "occupied" state: see the module docstring. `state` reports
    occupancy when someone is in it, and the service state otherwise.
    """

    AVAILABLE = "available"
    RESERVED = "reserved"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"
    SERVICE_STATES = [
        (AVAILABLE, "Available"),
        (RESERVED, "Reserved"),
        (CLEANING, "Being cleaned"),
        (MAINTENANCE, "Unavailable for maintenance"),
    ]
    OCCUPIED = "occupied"

    # The states a patient may not be put into.
    NOT_ALLOCATABLE = {CLEANING, MAINTENANCE}

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="beds")
    code = models.CharField(max_length=20)
    service_state = models.CharField(
        max_length=15, choices=SERVICE_STATES, default=AVAILABLE
    )
    state_note = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["room", "code"]
        constraints = [
            models.UniqueConstraint(fields=["room", "code"], name="bed_code_unique_per_room")
        ]

    def __str__(self):
        return f"{self.room.ward.code}/{self.room.code}/{self.code}"

    @property
    def ward(self):
        return self.room.ward

    @property
    def current_occupancy(self):
        return self.occupancies.filter(period__endswith__isnull=True).first()

    @property
    def is_occupied(self):
        return self.occupancies.filter(period__endswith__isnull=True).exists()

    @property
    def state(self):
        return self.OCCUPIED if self.is_occupied else self.service_state

    def set_service_state(self, state, *, note=""):
        """Change what the bed is available for.

        Refuses to mark an occupied bed available: the patient in it is the
        authority on whether it is free.
        """
        if self.is_occupied and state == self.AVAILABLE:
            raise ValidationError(
                f"{self} is occupied. It becomes available when the patient leaves."
            )
        self.service_state = state
        self.state_note = note
        self.save(update_fields=["service_state", "state_note"])
        return self


class BedOccupancy(models.Model):
    """Who was in a bed, and for what period.

    The exclusion constraint below is the whole point of the model. An ongoing
    occupancy has an unbounded upper end, which still overlaps for the purposes
    of the constraint, so a second admission to the same bed is rejected by the
    database rather than caught by a check that a race can slip past.
    """

    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="occupancies")
    admission = models.ForeignKey(
        "admissions.Admission", on_delete=models.PROTECT, related_name="occupancies"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="bed_occupancies"
    )
    # `[started, ended)` — an open occupancy has no upper bound.
    period = DateTimeRangeField()

    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="bed_allocations",
    )
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="bed_releases",
    )
    reason_ended = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name_plural = "bed occupancies"
        ordering = ["bed", "period"]
        constraints = [
            # Two patients cannot occupy one bed. Not "should not" — cannot.
            ExclusionConstraint(
                name="one_patient_per_bed_at_a_time",
                expressions=[
                    ("period", RangeOperators.OVERLAPS),
                    ("bed", RangeOperators.EQUAL),
                ],
            ),
            # And one patient cannot be in two beds at once.
            ExclusionConstraint(
                name="one_bed_per_patient_at_a_time",
                expressions=[
                    ("period", RangeOperators.OVERLAPS),
                    ("patient", RangeOperators.EQUAL),
                ],
            ),
        ]
        indexes = [models.Index(fields=["admission"])]

    def __str__(self):
        return f"{self.patient.full_name} in {self.bed}"

    @property
    def started_at(self):
        return self.period.lower

    @property
    def ended_at(self):
        return self.period.upper

    @property
    def is_open(self):
        return self.period.upper is None

    @property
    def nights(self):
        """Nights occupied, counted by calendar date rather than by 24-hour
        blocks — a hospital charges for the night a patient slept in the bed,
        not for elapsed hours."""
        end = self.period.upper or timezone.now()
        return max((end.date() - self.period.lower.date()).days, 0)

    @classmethod
    @transaction.atomic
    def allocate(cls, *, bed, admission, actor=None, at=None):
        """Put a patient in a bed, or fail.

        The database enforces exclusivity; this adds the states a bed must not be
        allocated from, and reports them by name so the ward knows what to do
        about it.
        """
        bed = Bed.objects.select_related("room__ward").get(pk=bed.pk)
        if not bed.is_active:
            raise ValidationError(f"{bed} is not in service.")
        if bed.service_state in Bed.NOT_ALLOCATABLE:
            raise ValidationError(
                f"{bed} is {bed.get_service_state_display().lower()}"
                + (f" — {bed.state_note}" if bed.state_note else "")
                + "."
            )
        started = at or timezone.now()
        return cls.objects.create(
            bed=bed,
            admission=admission,
            patient=admission.patient,
            period=DateTimeTZRange(started, None),
            allocated_by=actor,
        )

    @transaction.atomic
    def close(self, *, actor=None, at=None, reason=""):
        """End the occupancy. The bed goes for cleaning, not straight back to
        available — a bed a patient has just left is not ready for the next one."""
        if not self.is_open:
            raise ValidationError("That occupancy has already ended.")
        ended = at or timezone.now()
        if ended <= self.period.lower:
            raise ValidationError("An occupancy cannot end before it began.")
        self.period = DateTimeTZRange(self.period.lower, ended)
        self.ended_by = actor
        self.reason_ended = reason
        self.save(update_fields=["period", "ended_by", "reason_ended"])
        Bed.objects.filter(pk=self.bed_id).update(service_state=Bed.CLEANING)
        return self


class EscalationThreshold(models.Model):
    """When an observation has to be escalated, per ward.

    Configurable per ward because the same figure means different things in
    intensive care and on a general ward, and a single hospital-wide threshold
    would either cry wolf or stay silent.
    """

    MEASUREMENTS = [
        ("temperature_c", "Temperature (°C)"),
        ("systolic_bp", "Systolic BP (mmHg)"),
        ("diastolic_bp", "Diastolic BP (mmHg)"),
        ("pulse_bpm", "Pulse (bpm)"),
        ("respiratory_rate", "Respiratory rate"),
        ("oxygen_saturation", "Oxygen saturation (%)"),
        ("blood_glucose_mmol", "Blood glucose (mmol/L)"),
    ]

    ward = models.ForeignKey(
        Ward, on_delete=models.CASCADE, related_name="escalation_thresholds"
    )
    measurement = models.CharField(max_length=30, choices=MEASUREMENTS)
    low = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    high = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    instruction = models.CharField(
        max_length=255, blank=True,
        help_text="What the nurse should do. Shown with the alert.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ward", "measurement"]
        constraints = [
            models.UniqueConstraint(
                fields=["ward", "measurement"], name="one_threshold_per_ward_measurement"
            ),
            models.CheckConstraint(
                condition=models.Q(low__isnull=False) | models.Q(high__isnull=False),
                name="threshold_bounds_at_least_one",
            ),
        ]

    def __str__(self):
        return f"{self.ward.code} {self.measurement}"

    def breached_by(self, value):
        """Returns 'low', 'high' or None."""
        if value is None:
            return None
        if self.low is not None and value < self.low:
            return "low"
        if self.high is not None and value > self.high:
            return "high"
        return None
