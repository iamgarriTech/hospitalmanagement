"""Pregnancy, antenatal care, and delivery.

Its own app because AC-173 requires a hospital that does not provide
maternity to be able to leave it alone entirely — no screens, no navigation,
no required fields anywhere else. Nothing outside this app imports from it,
and nothing here is referenced by the outpatient or inpatient flow, so a
hospital that never grants a maternity permission never sees it exist.

The one shape worth pointing at is `Delivery.baby`: it is a real
`patients.Patient`, not a name on the mother's record. A baby born in a
hospital needs their own chart from the first minute — observations, a weight,
possibly antibiotics — and recording them as an attribute of their mother is
how a newborn ends up with no record of their own resuscitation.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Pregnancy(models.Model):
    """One pregnancy. AC-171.

    The estimated delivery date carries how it was arrived at, because the
    three usual bases disagree by up to a fortnight and every decision about
    prematurity depends on which was used.
    """

    LMP = "lmp"
    ULTRASOUND = "ultrasound"
    EXAMINATION = "examination"
    UNCERTAIN = "uncertain"
    EDD_BASIS_CHOICES = [
        (LMP, "Last menstrual period"),
        (ULTRASOUND, "Ultrasound dating scan"),
        (EXAMINATION, "Clinical examination"),
        (UNCERTAIN, "Uncertain"),
    ]

    ONGOING = "ongoing"
    DELIVERED = "delivered"
    ENDED = "ended"
    TRANSFERRED = "transferred"
    STATUS_CHOICES = [
        (ONGOING, "Ongoing"), (DELIVERED, "Delivered"),
        (ENDED, "Ended before delivery"), (TRANSFERRED, "Care transferred out"),
    ]

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="pregnancies"
    )
    facility = models.ForeignKey(
        "facilities.Facility", on_delete=models.PROTECT, related_name="pregnancies"
    )

    last_menstrual_period = models.DateField(null=True, blank=True)
    estimated_delivery_date = models.DateField()
    edd_basis = models.CharField(max_length=12, choices=EDD_BASIS_CHOICES)
    edd_basis_note = models.CharField(
        max_length=255, blank=True,
        help_text="Which scan, at what gestation — so a later revision can be judged.",
    )

    # Obstetric history in the usual shorthand. Kept as plain integers rather
    # than parsed from a "G4P2+1" string, because that notation varies between
    # schools and a stored string cannot be counted.
    gravida = models.PositiveSmallIntegerField(
        default=1, help_text="Total pregnancies including this one."
    )
    parity = models.PositiveSmallIntegerField(
        default=0, help_text="Births after 28 weeks."
    )
    previous_losses = models.PositiveSmallIntegerField(default=0)

    risk_factors = models.TextField(
        blank=True,
        help_text="Recorded by the clinician. This software does not score risk.",
    )

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=ONGOING)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=255, blank=True)

    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pregnancies_booked"
    )
    booked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-booked_at", "-id"]
        verbose_name_plural = "pregnancies"
        constraints = [
            # One ongoing pregnancy per patient. A second is a data-entry
            # mistake, and it splits the antenatal record across two books.
            models.UniqueConstraint(
                fields=["patient"], condition=models.Q(status="ongoing"),
                name="one_ongoing_pregnancy_per_patient",
            ),
            models.CheckConstraint(
                condition=models.Q(status="ongoing")
                | models.Q(ended_at__isnull=False)
                | models.Q(status="delivered"),
                name="closed_pregnancy_has_an_end",
            ),
        ]
        permissions = [
            ("book_pregnancy", "Can book a pregnancy"),
            ("record_antenatal_visit", "Can record an antenatal visit"),
            ("record_delivery", "Can record a delivery"),
        ]

    def __str__(self):
        return f"{self.patient.full_name}, EDD {self.estimated_delivery_date}"

    def gestation_at(self, on=None):
        """Weeks and days, from the EDD. None where it cannot be worked out.

        Counted back from the estimated delivery date rather than forward from
        the last period, so a pregnancy re-dated by a scan reports the
        gestation the clinicians are actually using.
        """
        if self.estimated_delivery_date is None:
            return None
        on = on or timezone.localdate()
        days = 280 - (self.estimated_delivery_date - on).days
        if days < 0:
            return None
        return {"weeks": days // 7, "days": days % 7, "total_days": days}

    @property
    def is_open(self):
        return self.status == self.ONGOING


class AntenatalVisit(models.Model):
    """One antenatal contact. AC-171.

    Deliberately not a `visits.Visit`: an antenatal check may happen inside an
    ordinary attendance or as a community contact, and what matters here is
    the sequence of measurements against the pregnancy. Where there was a
    hospital attendance, it is linked.
    """

    pregnancy = models.ForeignKey(
        Pregnancy, on_delete=models.CASCADE, related_name="antenatal_visits"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="antenatal_visits",
    )
    sequence = models.PositiveSmallIntegerField()
    seen_at = models.DateTimeField(default=timezone.now)

    gestation_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    systolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    fundal_height_cm = models.PositiveSmallIntegerField(null=True, blank=True)
    fetal_heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    presentation = models.CharField(max_length=40, blank=True)

    urine_protein = models.CharField(max_length=20, blank=True)
    urine_glucose = models.CharField(max_length=20, blank=True)
    haemoglobin = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )

    notes = models.TextField(blank=True)
    next_appointment = models.DateField(null=True, blank=True)

    seen_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="antenatal_visits",
    )

    class Meta:
        ordering = ["pregnancy", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["pregnancy", "sequence"],
                name="one_antenatal_visit_per_sequence",
            ),
        ]

    def __str__(self):
        return f"ANC {self.sequence} — {self.pregnancy.patient.full_name}"


class Delivery(models.Model):
    """A birth. AC-172.

    One row per delivery episode; the babies hang off it, because twins are
    one labour and two patients.
    """

    SPONTANEOUS_VAGINAL = "svd"
    ASSISTED_VAGINAL = "assisted"
    CAESAREAN_ELECTIVE = "lscs_elective"
    CAESAREAN_EMERGENCY = "lscs_emergency"
    MODE_CHOICES = [
        (SPONTANEOUS_VAGINAL, "Spontaneous vaginal delivery"),
        (ASSISTED_VAGINAL, "Assisted vaginal delivery"),
        (CAESAREAN_ELECTIVE, "Caesarean section, elective"),
        (CAESAREAN_EMERGENCY, "Caesarean section, emergency"),
    ]

    pregnancy = models.OneToOneField(
        Pregnancy, on_delete=models.PROTECT, related_name="delivery"
    )
    admission = models.ForeignKey(
        "inpatient.Admission", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deliveries",
    )
    procedure = models.OneToOneField(
        "procedures.PerformedProcedure", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="delivery",
        help_text="Where it was a caesarean, the theatre record of it.",
    )

    delivered_at = models.DateTimeField()
    mode = models.CharField(max_length=15, choices=MODE_CHOICES)
    onset_of_labour = models.CharField(max_length=40, blank=True)
    duration_of_labour_minutes = models.PositiveIntegerField(null=True, blank=True)

    estimated_blood_loss_ml = models.PositiveIntegerField(null=True, blank=True)
    perineal_tear = models.CharField(max_length=40, blank=True)
    complications = models.TextField(blank=True)
    placenta_complete = models.BooleanField(null=True, blank=True)

    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="deliveries_attended",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="deliveries_recorded",
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-delivered_at", "-id"]
        verbose_name_plural = "deliveries"

    def __str__(self):
        return f"{self.get_mode_display()} — {self.pregnancy.patient.full_name}"

    @property
    def mother(self):
        return self.pregnancy.patient

    @property
    def facility_id(self):
        return self.pregnancy.facility_id


class Baby(models.Model):
    """A baby, and the patient record that is theirs. AC-172.

    `patient` is not nullable. A newborn who exists in this table but not in
    the patient register is a baby nobody can prescribe for, weigh, or admit —
    and the ones who need those things most are the ones whose delivery went
    badly. The constraint is what makes AC-172's negative unrepresentable
    rather than merely discouraged.
    """

    LIVE_BIRTH = "live"
    STILLBIRTH_FRESH = "stillbirth_fresh"
    STILLBIRTH_MACERATED = "stillbirth_macerated"
    OUTCOME_CHOICES = [
        (LIVE_BIRTH, "Live birth"),
        (STILLBIRTH_FRESH, "Fresh stillbirth"),
        (STILLBIRTH_MACERATED, "Macerated stillbirth"),
    ]

    delivery = models.ForeignKey(
        Delivery, on_delete=models.PROTECT, related_name="babies"
    )
    patient = models.OneToOneField(
        "patients.Patient", on_delete=models.PROTECT, related_name="birth_record"
    )
    birth_order = models.PositiveSmallIntegerField(
        default=1, help_text="1 for a singleton; 1 and 2 for twins."
    )

    outcome = models.CharField(max_length=22, choices=OUTCOME_CHOICES,
                               default=LIVE_BIRTH)
    birth_weight_grams = models.PositiveIntegerField(null=True, blank=True)
    apgar_one_minute = models.PositiveSmallIntegerField(null=True, blank=True)
    apgar_five_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    resuscitation = models.CharField(max_length=255, blank=True)
    congenital_abnormality = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["delivery", "birth_order"]
        verbose_name_plural = "babies"
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "birth_order"],
                name="one_baby_per_birth_order_per_delivery",
            ),
            models.CheckConstraint(
                condition=models.Q(apgar_one_minute__lte=10)
                | models.Q(apgar_one_minute__isnull=True),
                name="apgar_one_is_out_of_ten",
            ),
            models.CheckConstraint(
                condition=models.Q(apgar_five_minutes__lte=10)
                | models.Q(apgar_five_minutes__isnull=True),
                name="apgar_five_is_out_of_ten",
            ),
        ]

    def __str__(self):
        return f"Baby {self.birth_order} of {self.delivery.mother.full_name}"

    def clean(self):
        if self.outcome != self.LIVE_BIRTH and self.apgar_one_minute:
            raise ValidationError(
                "An Apgar score is a score for a live baby. Recording one against "
                "a stillbirth is a contradiction somebody will have to resolve."
            )
