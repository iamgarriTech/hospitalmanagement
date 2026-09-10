"""Procedures, and the theatre they happen in.

One app rather than two. A theatre case *is* a procedure — one with a room, a
session and a team — and splitting them would put the operation note in one
app, the thing it describes in another, and a circular import between them.

Three shapes carry the weight here:

- `TheatreBooking.period` is a `tstzrange` under an exclusion constraint, so
  two operations cannot occupy one theatre at the same time. Same mechanism as
  bed occupancy, for the same reason: a read-then-write check loses the race
  that matters, and two teams arriving at one door is not recoverable by
  apologising afterwards.
- `OperationNoteVersion` appends rather than overwrites. Somebody may have made
  a decision on the superseded text.
- Billing hangs off `PerformedProcedure`, never off the request. A procedure
  that was requested and cancelled has not happened, and a patient must not be
  charged for it.
"""

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

ZERO = "0.00"


class ProcedureCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name_plural = "procedure categories"

    def __str__(self):
        return self.name


class Procedure(models.Model):
    """The catalogue. AC-158.

    Administrable at runtime, because the set of procedures a hospital does is
    a fact about that hospital rather than about this software.
    """

    category = models.ForeignKey(
        ProcedureCategory, on_delete=models.PROTECT, related_name="procedures"
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, unique=True)

    typical_duration_minutes = models.PositiveSmallIntegerField(
        default=30, help_text="Used to size a theatre booking, not to enforce one."
    )

    # A theatre case needs a room and a team; a dressing change needs neither.
    # The catalogue says which, so the request screen can ask for the right
    # things rather than asking for everything and hoping.
    requires_theatre = models.BooleanField(default=False)
    requires_consent = models.BooleanField(
        default=True,
        help_text="Whether written consent is required before it may be performed.",
    )
    requires_anaesthesia = models.BooleanField(default=False)

    # What it bills as. The price lives on the billing service, per facility,
    # so a procedure costs what that branch charges for it.
    billing_service = models.ForeignKey(
        "billing.Service", on_delete=models.PROTECT, null=True, blank=True,
        related_name="procedures",
        help_text="What this bills as. Without one it is recorded but not charged.",
    )

    preparation = models.TextField(
        blank=True, help_text="What the patient is told beforehand."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category__display_order", "name"]

    def __str__(self):
        return self.name


class ProcedureConsumable(models.Model):
    """What a procedure normally uses. AC-158, AC-160.

    A default rather than a rule: the pack is what usually gets opened, and
    what actually gets used is recorded against the performed procedure. A
    system that billed the default would bill for gloves nobody wore.
    """

    procedure = models.ForeignKey(
        Procedure, on_delete=models.CASCADE, related_name="consumables"
    )
    item = models.ForeignKey(
        "inventory.InventoryItem", on_delete=models.PROTECT,
        related_name="procedure_uses",
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["procedure", "item__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["procedure", "item"], name="one_consumable_line_per_procedure"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.item.name}"


class Theatre(models.Model):
    """A room operations happen in. AC-161."""

    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="theatres"
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20)
    # Where the theatre draws its consumables from, so a case can take stock
    # off the right shelf without somebody choosing it every time.
    store = models.ForeignKey(
        "inventory.Store", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="theatres",
    )
    is_active = models.BooleanField(default=True)
    out_of_service_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["facility", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "code"], name="theatre_code_unique_per_facility"
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.facility.code}"


class ProcedureRequest(models.Model):
    """A clinician asking for a procedure. AC-159.

    Separate from performing it, and from billing it. A request is a clinical
    decision that something should happen; whether it happened is a different
    fact, and the patient pays for the second one.
    """

    REQUESTED = "requested"
    SCHEDULED = "scheduled"
    PERFORMED = "performed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (REQUESTED, "Requested"), (SCHEDULED, "Scheduled"),
        (PERFORMED, "Performed"), (CANCELLED, "Cancelled"),
    ]

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENCY = "emergency"
    URGENCY_CHOICES = [
        (ROUTINE, "Routine"), (URGENT, "Urgent"), (EMERGENCY, "Emergency"),
    ]

    reference = models.CharField(max_length=30, unique=True)
    procedure = models.ForeignKey(
        Procedure, on_delete=models.PROTECT, related_name="requests"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="procedure_requests"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT,
        related_name="procedure_requests",
    )

    # One or the other, never both — an outpatient attendance or an inpatient
    # stay. Which one decides where the charge lands.
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="procedure_requests",
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.PROTECT, null=True, blank=True,
        related_name="procedure_requests",
    )

    indication = models.TextField(help_text="Why this patient needs this procedure.")
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default=ROUTINE)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=REQUESTED)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="procedure_requests",
    )
    requested_at = models.DateTimeField(default=timezone.now)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(indication=""),
                name="procedure_request_states_an_indication",
            ),
            models.CheckConstraint(
                condition=models.Q(visit__isnull=False) | models.Q(admission__isnull=False),
                name="procedure_request_belongs_to_an_episode",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="cancelled")
                | ~models.Q(cancellation_reason=""),
                name="cancelled_procedure_says_why",
            ),
        ]
        permissions = [
            ("request_procedure", "Can request a procedure"),
            ("schedule_procedure", "Can book a theatre"),
            ("perform_procedure", "Can record a procedure as performed"),
            ("record_consent", "Can record a patient's consent"),
            ("amend_operation_note", "Can amend an operation note"),
        ]

    def __str__(self):
        return f"{self.reference} — {self.procedure.name}"

    @property
    def is_open(self):
        return self.status in (self.REQUESTED, self.SCHEDULED)


class Consent(models.Model):
    """Recorded consent for a procedure. AC-159.

    Its own row rather than a flag, because "consented" is not a boolean: it
    has a time, a person who took it, what they said was discussed, and — where
    the patient could not consent themselves — who did and on what basis.

    The wording here is **not clinically or legally reviewed.** It is a record
    of a conversation, not a substitute for the hospital's own consent form.
    """

    PATIENT = "patient"
    NEXT_OF_KIN = "next_of_kin"
    TWO_DOCTORS = "two_doctors"
    GIVEN_BY_CHOICES = [
        (PATIENT, "The patient"),
        (NEXT_OF_KIN, "Next of kin or legal guardian"),
        (TWO_DOCTORS, "Two doctors, patient unable to consent"),
    ]

    request = models.OneToOneField(
        ProcedureRequest, on_delete=models.CASCADE, related_name="consent"
    )
    given_by = models.CharField(max_length=15, choices=GIVEN_BY_CHOICES, default=PATIENT)
    given_by_name = models.CharField(
        max_length=200, blank=True,
        help_text="Required where somebody other than the patient consented.",
    )
    relationship = models.CharField(max_length=80, blank=True)

    risks_discussed = models.TextField(
        help_text="What was explained: the procedure, its risks, and the alternatives."
    )
    interpreter_used = models.BooleanField(default=False)
    interpreter_name = models.CharField(max_length=200, blank=True)

    taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consents_taken"
    )
    taken_at = models.DateTimeField(default=timezone.now)

    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(risks_discussed=""),
                name="consent_records_what_was_discussed",
            ),
            # Somebody consenting for a patient has to be named. "Next of kin"
            # with no name is not a record of anything.
            models.CheckConstraint(
                condition=models.Q(given_by="patient")
                | ~models.Q(given_by_name=""),
                name="proxy_consent_names_the_person",
            ),
        ]

    def __str__(self):
        return f"Consent for {self.request.reference}"

    @property
    def is_valid(self):
        return self.withdrawn_at is None


class TheatreBooking(models.Model):
    """A slot in a theatre. AC-161.

    `period` is a range under an exclusion constraint. Two operations in one
    theatre at one time is not a scheduling annoyance — it is two teams and two
    patients arriving at one door — and a check in Python loses exactly the
    race that produces it.
    """

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (SCHEDULED, "Scheduled"), (IN_PROGRESS, "In progress"),
        (COMPLETED, "Completed"), (CANCELLED, "Cancelled"),
    ]

    theatre = models.ForeignKey(
        Theatre, on_delete=models.PROTECT, related_name="bookings"
    )
    request = models.ForeignKey(
        ProcedureRequest, on_delete=models.PROTECT, related_name="bookings"
    )
    period = DateTimeRangeField(help_text="When the theatre is held.")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=SCHEDULED)

    lead_surgeon = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="theatre_bookings_led",
    )
    anaesthetist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="theatre_bookings_anaesthetised",
    )

    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="theatre_bookings_made",
    )
    booked_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["period"]
        constraints = [
            # AC-161, in the database. Cancelled bookings are excluded from the
            # check: a slot that was given up is free, and holding it forever
            # would make the theatre list useless within a week.
            ExclusionConstraint(
                name="one_operation_per_theatre_at_a_time",
                expressions=[
                    ("theatre", RangeOperators.EQUAL),
                    ("period", RangeOperators.OVERLAPS),
                ],
                condition=models.Q(status__in=["scheduled", "in_progress", "completed"]),
            ),
        ]

    def __str__(self):
        return f"{self.theatre.code} {self.period.lower:%d %b %H:%M}"

    @property
    def facility_id(self):
        return self.theatre.facility_id


class PerformedProcedure(models.Model):
    """A procedure that actually happened. AC-160, AC-163.

    This is what bills, and it is the only thing that does. A request is an
    intention; a cancelled request is an intention that came to nothing; only
    this row means the patient had the procedure.
    """

    COMPLETED = "completed"
    ABANDONED = "abandoned"
    OUTCOME_CHOICES = [
        (COMPLETED, "Completed"),
        (ABANDONED, "Abandoned before completion"),
    ]

    request = models.OneToOneField(
        ProcedureRequest, on_delete=models.PROTECT, related_name="performed"
    )
    booking = models.OneToOneField(
        TheatreBooking, on_delete=models.PROTECT, null=True, blank=True,
        related_name="performed",
    )

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES, default=COMPLETED)

    lead_clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="procedures_led",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="procedures_recorded",
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    # Set once the charge is raised, so a retry cannot bill twice and so
    # somebody can see whether this has reached the bill at all.
    is_billed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(finished_at__gt=models.F("started_at")),
                name="procedure_finishes_after_it_starts",
            ),
        ]

    def __str__(self):
        return f"{self.request.procedure.name} for {self.request.patient.full_name}"

    @property
    def facility_id(self):
        return self.request.facility_id

    @property
    def duration_minutes(self):
        return int((self.finished_at - self.started_at).total_seconds() // 60)


class ProcedureTeamMember(models.Model):
    """Who was in the room. AC-160."""

    SURGEON = "surgeon"
    ASSISTANT = "assistant"
    ANAESTHETIST = "anaesthetist"
    SCRUB_NURSE = "scrub_nurse"
    CIRCULATING_NURSE = "circulating_nurse"
    OTHER = "other"
    ROLE_CHOICES = [
        (SURGEON, "Surgeon"), (ASSISTANT, "Assistant"),
        (ANAESTHETIST, "Anaesthetist"), (SCRUB_NURSE, "Scrub nurse"),
        (CIRCULATING_NURSE, "Circulating nurse"), (OTHER, "Other"),
    ]

    performed = models.ForeignKey(
        PerformedProcedure, on_delete=models.CASCADE, related_name="team"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="procedure_team_roles",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    class Meta:
        ordering = ["performed", "role"]
        constraints = [
            models.UniqueConstraint(
                fields=["performed", "member", "role"],
                name="one_role_per_person_per_procedure",
            ),
        ]

    def __str__(self):
        return f"{self.member.full_name} ({self.get_role_display()})"


class ProcedureConsumableUsed(models.Model):
    """What was actually used, and the stock movement that took it. AC-160.

    `movement` is not nullable, for the same reason a goods receipt line's is
    not: consumables recorded as used but never taken off stock means a store
    that believes it holds boxes it does not have, discovered at the next case.
    """

    performed = models.ForeignKey(
        PerformedProcedure, on_delete=models.CASCADE, related_name="consumables_used"
    )
    item = models.ForeignKey(
        "inventory.InventoryItem", on_delete=models.PROTECT,
        related_name="procedure_consumption",
    )
    quantity = models.PositiveIntegerField()
    movement = models.ForeignKey(
        "inventory.StockMovement", on_delete=models.PROTECT,
        related_name="procedure_uses",
    )

    class Meta:
        ordering = ["performed", "item__name"]

    def __str__(self):
        return f"{self.quantity} × {self.item.name}"


class ProcedureMedication(models.Model):
    """Medication given during the procedure. AC-160.

    Recorded here rather than on the drug chart because a drug given on the
    table is given by the anaesthetist in the moment, not scheduled and
    administered against a prescription.
    """

    performed = models.ForeignKey(
        PerformedProcedure, on_delete=models.CASCADE, related_name="medications"
    )
    medication = models.ForeignKey(
        "pharmacy.Medication", on_delete=models.PROTECT,
        related_name="procedure_administrations",
    )
    dose = models.CharField(max_length=80)
    route = models.CharField(max_length=30)
    given_at = models.DateTimeField(default=timezone.now)
    given_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="procedure_medications_given",
    )

    class Meta:
        ordering = ["performed", "given_at"]

    def __str__(self):
        return f"{self.medication.generic_name} {self.dose} {self.route}"


class OperationNote(models.Model):
    """The record of what was done. AC-162.

    A container; the text lives in versions. Amending appends rather than
    overwrites, because somebody may have made a decision on the superseded
    text and needs to be able to see what it said.
    """

    performed = models.OneToOneField(
        PerformedProcedure, on_delete=models.CASCADE, related_name="note"
    )
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Operation note — {self.performed}"

    @property
    def current(self):
        return self.versions.filter(is_current=True).first()


class OperationNoteVersion(models.Model):
    """One immutable revision of an operation note. AC-162."""

    note = models.ForeignKey(
        OperationNote, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)

    findings = models.TextField()
    procedure_performed = models.TextField(
        help_text="What was actually done, which is not always what was requested."
    )
    closure = models.TextField(blank=True)
    estimated_blood_loss_ml = models.PositiveIntegerField(null=True, blank=True)
    specimens_taken = models.CharField(max_length=255, blank=True)
    complications = models.TextField(blank=True)
    post_operative_instructions = models.TextField(blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="operation_note_versions",
    )
    created_at = models.DateTimeField(default=timezone.now)
    amendment_reason = models.TextField(
        blank=True, help_text="Required on every version after the first."
    )

    class Meta:
        ordering = ["note", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["note", "version_number"], name="one_version_number_per_note"
            ),
            models.UniqueConstraint(
                fields=["note"], condition=models.Q(is_current=True),
                name="one_current_version_per_note",
            ),
            models.CheckConstraint(
                condition=~models.Q(findings=""),
                name="operation_note_records_findings",
            ),
            # An amendment with no reason is an overwrite wearing a version
            # number. AC-162.
            models.CheckConstraint(
                condition=models.Q(version_number=1) | ~models.Q(amendment_reason=""),
                name="amended_note_states_a_reason",
            ),
        ]

    def __str__(self):
        return f"v{self.version_number} of {self.note}"

    def clean(self):
        if self.version_number > 1 and not self.amendment_reason.strip():
            raise ValidationError(
                "An amendment needs a reason. The superseded text stays on the "
                "record, and somebody reading it needs to know why it changed."
            )
