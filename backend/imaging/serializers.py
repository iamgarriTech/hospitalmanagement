from rest_framework import serializers

from patients.serializers import PatientSummarySerializer

from .models import (
    CriticalFindingAcknowledgement,
    ImagingModality,
    ImagingOrder,
    ImagingOrderItem,
    ImagingProcedure,
    ImagingReport,
)


class ImagingModalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagingModality
        fields = ["id", "name", "code", "display_order", "is_active"]


class ImagingProcedureSerializer(serializers.ModelSerializer):
    """AC-94. Modality, body part, preparation and price."""

    modality_name = serializers.CharField(source="modality.name", read_only=True)
    modality_code = serializers.CharField(source="modality.code", read_only=True)
    price = serializers.SerializerMethodField()

    class Meta:
        model = ImagingProcedure
        fields = [
            "id", "modality", "modality_name", "modality_code", "name", "code_short",
            "body_part", "preparation_instructions", "service", "price",
            "typical_minutes", "requires_contrast", "contraindications", "is_active",
            "code_system", "code", "code_display", "code_version",
        ]

    def get_price(self, procedure) -> str | None:
        """Per facility, resolved for the caller's facility where one is given.

        Priced through the ordinary service machinery rather than a column here,
        so a change is audited like any other price change.
        """
        facility = self.context.get("facility")
        if facility is None or procedure.service_id is None:
            return None
        amount = procedure.price_at(facility)
        return str(amount) if amount is not None else None


class CriticalFindingAcknowledgementSerializer(serializers.ModelSerializer):
    acknowledged_by_name = serializers.CharField(
        source="acknowledged_by.full_name", read_only=True
    )
    minutes_to_acknowledge = serializers.IntegerField(read_only=True)

    class Meta:
        model = CriticalFindingAcknowledgement
        fields = [
            "id", "report", "acknowledged_by", "acknowledged_by_name",
            "acknowledged_at", "action_taken", "minutes_to_acknowledge",
        ]
        read_only_fields = fields


class ImagingReportSerializer(serializers.ModelSerializer):
    reported_by_name = serializers.CharField(source="reported_by.full_name", read_only=True)
    verified_by_name = serializers.CharField(
        source="verified_by.full_name", read_only=True, default=None
    )
    is_verified = serializers.BooleanField(read_only=True)
    is_amended = serializers.BooleanField(read_only=True)
    status_label = serializers.CharField(read_only=True)
    needs_acknowledgement = serializers.BooleanField(read_only=True)
    acknowledgements = CriticalFindingAcknowledgementSerializer(many=True, read_only=True)

    class Meta:
        model = ImagingReport
        fields = [
            "id", "order_item", "findings", "conclusion", "comparison",
            "is_critical", "critical_finding", "version", "is_current", "amends",
            "amendment_reason", "reported_by", "reported_by_name", "reported_at",
            "verified_by", "verified_by_name", "verified_at", "is_verified",
            "is_amended", "status_label", "needs_acknowledgement", "acknowledgements",
        ]
        read_only_fields = fields


class ImagingOrderItemSerializer(serializers.ModelSerializer):
    procedure_name = serializers.CharField(source="procedure.name", read_only=True)
    procedure_code = serializers.CharField(source="procedure.code_short", read_only=True)
    modality = serializers.CharField(source="procedure.modality.name", read_only=True)
    body_part = serializers.CharField(source="procedure.body_part", read_only=True)
    preparation_instructions = serializers.CharField(
        source="procedure.preparation_instructions", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    allowed_transitions = serializers.SerializerMethodField()
    performed_by_name = serializers.CharField(
        source="performed_by.full_name", read_only=True, default=None
    )
    report = serializers.SerializerMethodField()
    report_history = serializers.SerializerMethodField()

    class Meta:
        model = ImagingOrderItem
        fields = [
            "id", "order", "procedure", "procedure_name", "procedure_code", "modality",
            "body_part", "preparation_instructions", "status", "status_display",
            "allowed_transitions", "cancelled_reason", "scheduled_for", "performed_at",
            "performed_by", "performed_by_name", "accession_number", "views_taken",
            "technique_note", "contrast_given", "report", "report_history",
        ]
        read_only_fields = fields

    def get_allowed_transitions(self, item) -> list[str]:
        """Sent from the server so the client offers only legal moves. A second
        copy of the state machine in the browser is the one that would drift."""
        return sorted(item.TRANSITIONS.get(item.status, set()))

    def get_report(self, item) -> dict | None:
        """AC-96.

        An unverified report does not reach the requesting clinician as a
        finding. Whoever is allowed to see the draft — the department, and
        anyone who may verify — gets the text; everyone else is told a report
        exists and is not yet released, which is true and actionable, rather
        than being shown a provisional conclusion they might act on.
        """
        report = item.current_report
        if report is None:
            return None
        if report.is_verified or self.context.get("may_see_drafts"):
            return ImagingReportSerializer(report, context=self.context).data
        return {
            "id": report.pk,
            "status_label": report.status_label,
            "is_verified": False,
            "reported_at": report.reported_at,
            "awaiting_verification": True,
        }

    def get_report_history(self, item) -> list:
        """Superseded reports, so an amendment can be read against what it
        replaced. AC-97."""
        return [
            {
                "id": report.pk,
                "version": report.version,
                "findings": report.findings,
                "conclusion": report.conclusion,
                "amendment_reason": report.amendment_reason,
                "reported_by": report.reported_by.full_name,
                "reported_at": report.reported_at,
                "status_label": report.status_label,
            }
            for report in sorted(item.reports.all(), key=lambda r: r.version)
            if not report.is_current
        ]


class ImagingOrderSerializer(serializers.ModelSerializer):
    items = ImagingOrderItemSerializer(many=True, read_only=True)
    procedures = serializers.PrimaryKeyRelatedField(
        queryset=ImagingProcedure.objects.filter(is_active=True),
        many=True, write_only=True,
    )
    patient_detail = PatientSummarySerializer(source="patient", read_only=True)
    ordered_by_name = serializers.CharField(source="ordered_by.full_name", read_only=True)
    preparation = serializers.SerializerMethodField()

    class Meta:
        model = ImagingOrder
        fields = [
            "id", "order_number", "visit", "admission", "patient", "patient_detail",
            "facility", "ordered_by", "ordered_by_name", "ordered_at", "priority",
            "clinical_question", "relevant_history", "is_pregnant", "items",
            "procedures", "preparation",
        ]
        read_only_fields = [
            "id", "order_number", "patient", "facility", "ordered_by", "ordered_at",
        ]

    def get_preparation(self, order) -> list:
        """Collected onto the order so the ward sees it at once. "Nil by mouth
        for six hours" reaching the ward late is a cancelled slot and a patient
        who fasted for nothing."""
        return [
            {"procedure": item.procedure.name,
             "instructions": item.procedure.preparation_instructions}
            for item in order.items.all()
            if item.procedure.preparation_instructions
        ]

    def validate(self, attrs):
        if self.instance is None and (
            attrs.get("visit") is None and attrs.get("admission") is None
        ):
            raise serializers.ValidationError(
                "An imaging request belongs to an attendance or to an admission."
            )
        if not (attrs.get("clinical_question") or "").strip():
            raise serializers.ValidationError({
                "clinical_question": "Say what needs answering. A request with no "
                                     "question gets a description back, not an answer."
            })
        return attrs


# --- actions ------------------------------------------------------------------

class ScheduleSerializer(serializers.Serializer):
    scheduled_for = serializers.DateTimeField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class PerformSerializer(serializers.Serializer):
    accession_number = serializers.CharField(required=False, allow_blank=True, default="")
    views_taken = serializers.CharField(required=False, allow_blank=True, default="")
    technique_note = serializers.CharField(required=False, allow_blank=True, default="")
    contrast_given = serializers.CharField(required=False, allow_blank=True, default="")
    performed_at = serializers.DateTimeField(required=False, allow_null=True)


class ReportSerializer(serializers.Serializer):
    findings = serializers.CharField()
    conclusion = serializers.CharField()
    comparison = serializers.CharField(required=False, allow_blank=True, default="")
    is_critical = serializers.BooleanField(default=False)
    critical_finding = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs.get("is_critical") and not (attrs.get("critical_finding") or "").strip():
            raise serializers.ValidationError({
                "critical_finding": "Say in one line what has to be acted on."
            })
        return attrs


class AmendReportSerializer(serializers.Serializer):
    reason = serializers.CharField()
    findings = serializers.CharField(required=False, allow_null=True)
    conclusion = serializers.CharField(required=False, allow_null=True)
    is_critical = serializers.BooleanField(required=False, allow_null=True, default=None)
    critical_finding = serializers.CharField(required=False, allow_null=True)


class AcknowledgeFindingSerializer(serializers.Serializer):
    action_taken = serializers.CharField()


class CancelItemSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
