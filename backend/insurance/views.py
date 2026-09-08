"""Insurance over HTTP.

Two shapes worth pointing at.

`ChargeCoverageViewSet` is read-only, with no write verb of any kind. The split
is decided when the charge is raised and the row is a record of that decision;
an endpoint that could edit it would be an endpoint that rewrites what a
patient owed last month.

Claims are driven by actions rather than by PATCH — `submit`, `acknowledge`,
`reject`, `resubmit` — because each is a rule with its own permission and its
own audit row, and a writable `status` field would let a client set `paid`.
"""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from billing.models import PaymentMethod
from core.permissions import FacilityScopedMixin, HasPermission
from facilities.models import Facility
from patients.models import Patient

from . import claims as claim_service
from .coverage import invoice_split, policies_for
from .models import (
    ChargeCoverage,
    ClaimBatch,
    ClaimLine,
    CoverageRule,
    InsuranceProvider,
    PatientPolicy,
    Plan,
    Preauthorisation,
    ProviderPayment,
)
from .serializers import (
    AssembleClaimSerializer,
    ChargeCoverageSerializer,
    ClaimBatchSerializer,
    CoverageRuleSerializer,
    DecidePreauthorisationSerializer,
    EligibilityCheckSerializer,
    InsuranceProviderSerializer,
    PatientPolicySerializer,
    PlanSerializer,
    PreauthorisationSerializer,
    ProviderPaymentSerializer,
    RecordProviderPaymentSerializer,
    RejectClaimSerializer,
    ResolveShortfallSerializer,
    SubmitClaimSerializer,
)


def _validation_response(error):
    detail = error.message_dict if hasattr(error, "message_dict") else error.messages
    return Response({"detail": detail}, status=http.HTTP_400_BAD_REQUEST)


class InsuranceProviderViewSet(viewsets.ModelViewSet):
    """Configuration: who covers patients here."""

    queryset = InsuranceProvider.objects.prefetch_related("plans")
    serializer_class = InsuranceProviderSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "insurance.view_insuranceprovider",
        "retrieve": "insurance.view_insuranceprovider",
        "create": "insurance.manage_coverage",
        "partial_update": "insurance.manage_coverage",
        "ageing": "insurance.view_claimbatch",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        if self.request.query_params.get("accepting") == "true":
            queryset = queryset.filter(is_accepting_claims=True)
        return queryset

    def perform_create(self, serializer):
        provider = serializer.save()
        AuditEvent.record(
            action="insurance.provider_added",
            actor=self.request.user,
            resource=provider,
            after={"name": provider.name, "code": provider.code,
                   "type": provider.provider_type},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = {
            "is_accepting_claims": serializer.instance.is_accepting_claims,
            "settlement_days": serializer.instance.settlement_days,
        }
        provider = serializer.save()
        AuditEvent.record(
            action="insurance.provider_changed",
            actor=self.request.user,
            resource=provider,
            before=before,
            after={"is_accepting_claims": provider.is_accepting_claims,
                   "settlement_days": provider.settlement_days},
            request=self.request,
        )

    @extend_schema(
        parameters=[OpenApiParameter("facility", int)],
        summary="What each provider owes, and for how long",
    )
    @action(detail=False, methods=["get"])
    def ageing(self, request):
        """AC-139. Scoped to the facilities the caller may see."""
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        if facility is not None and not request.user.has_permission(
            "insurance.view_claimbatch", facility
        ):
            return Response(
                {"detail": "Not your facility."}, status=http.HTTP_404_NOT_FOUND
            )
        if facility is None:
            granted = set(request.user.facilities_for("insurance.view_claimbatch"))
            rows = []
            if None in granted or request.user.is_superuser:
                rows = claim_service.ageing()
            else:
                for facility_id in granted:
                    rows.extend(claim_service.ageing(
                        facility=Facility.objects.get(pk=facility_id)
                    ))
            return Response(rows)
        return Response(claim_service.ageing(facility=facility))


class PlanViewSet(viewsets.ModelViewSet):
    """Configuration: what each plan covers."""

    queryset = Plan.objects.select_related("provider").prefetch_related(
        "rules__service", "rules__category"
    )
    serializer_class = PlanSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "insurance.view_plan",
        "retrieve": "insurance.view_plan",
        "create": "insurance.manage_coverage",
        "partial_update": "insurance.manage_coverage",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("provider"):
            queryset = queryset.filter(
                provider_id=self.request.query_params["provider"]
            )
        if self.request.query_params.get("include_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_update(self, serializer):
        """Editing a plan is audited because it changes what *future* charges
        cost. It cannot change past ones — see `ChargeCoverage` — and the audit
        row is what lets somebody prove that afterwards."""
        instance = serializer.instance
        before = {
            "default_scheme_percent": str(instance.default_scheme_percent),
            "annual_limit": str(instance.annual_limit or ""),
            "unruled_services": instance.unruled_services,
        }
        plan = serializer.save()
        AuditEvent.record(
            action="insurance.plan_changed",
            actor=self.request.user,
            resource=plan,
            before=before,
            after={"default_scheme_percent": str(plan.default_scheme_percent),
                   "annual_limit": str(plan.annual_limit or ""),
                   "unruled_services": plan.unruled_services},
            request=self.request,
        )


class CoverageRuleViewSet(viewsets.ModelViewSet):
    """Configuration: one plan's treatment of one service or category."""

    queryset = CoverageRule.objects.select_related(
        "plan__provider", "service", "category"
    )
    serializer_class = CoverageRuleSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    required_permissions = {
        "list": "insurance.view_coveragerule",
        "retrieve": "insurance.view_coveragerule",
        "create": "insurance.manage_coverage",
        "partial_update": "insurance.manage_coverage",
        "destroy": "insurance.manage_coverage",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("plan"):
            queryset = queryset.filter(plan_id=self.request.query_params["plan"])
        return queryset

    def perform_create(self, serializer):
        rule = serializer.save()
        AuditEvent.record(
            action="insurance.rule_added",
            actor=self.request.user,
            resource=rule,
            after={"plan": str(rule.plan), "target": str(rule.service or rule.category),
                   "basis": rule.basis},
            request=self.request,
        )


class PatientPolicyViewSet(viewsets.ModelViewSet):
    """A patient's cover, and the checks made against it."""

    queryset = PatientPolicy.objects.select_related(
        "patient", "plan__provider", "recorded_by"
    ).prefetch_related("eligibility_checks__checked_by", "plan__rules")
    serializer_class = PatientPolicySerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "insurance.view_patientpolicy",
        "retrieve": "insurance.view_patientpolicy",
        "create": "insurance.add_patientpolicy",
        "partial_update": "insurance.change_patientpolicy",
        "check_eligibility": "insurance.verify_eligibility",
        "for_patient": "insurance.view_patientpolicy",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("provider"):
            queryset = queryset.filter(plan__provider_id=params["provider"])
        if params.get("current") == "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        policy = serializer.save(recorded_by=self.request.user)
        AuditEvent.record(
            action="insurance.policy_recorded",
            actor=self.request.user,
            resource=policy,
            patient=policy.patient,
            after={"provider": policy.plan.provider.code, "plan": policy.plan.code,
                   "policy_number": policy.policy_number,
                   "starts_on": str(policy.starts_on),
                   "ends_on": str(policy.ends_on or "")},
            request=self.request,
        )

    @extend_schema(
        parameters=[OpenApiParameter("patient", int, required=True)],
        summary="What cover this patient has today",
    )
    @action(detail=False, methods=["get"], url_path="for-patient",
            url_name="for-patient")
    def for_patient(self, request):
        """For the point-of-service screens: what is in force *now*.

        Returns an empty list rather than an error for a self-paying patient —
        "no cover" is a normal answer, and most patients here are self-paying.
        """
        patient = Patient.objects.filter(pk=request.query_params.get("patient")).first()
        if patient is None:
            return Response(
                {"detail": "No such patient."}, status=http.HTTP_404_NOT_FOUND
            )
        policies = policies_for(patient)
        return Response({
            "patient": patient.pk,
            "patient_name": patient.full_name,
            "has_cover": bool(policies),
            "policies": PatientPolicySerializer(policies, many=True).data,
        })

    @extend_schema(
        request=EligibilityCheckSerializer,
        responses={201: PatientPolicySerializer},
        summary="Record what the provider said",
    )
    @action(detail=True, methods=["post"], url_path="eligibility",
            url_name="eligibility")
    def check_eligibility(self, request, pk=None):
        """AC-128. A record, not a flag: "they said yes on the 3rd" is a
        different fact from "this policy is valid", and it is the first one a
        provider disputes."""
        policy = self.get_object()
        serializer = EligibilityCheckSerializer(data={**request.data, "policy": policy.pk})
        serializer.is_valid(raise_exception=True)
        check = serializer.save(policy=policy, checked_by=request.user)
        AuditEvent.record(
            action="insurance.eligibility_checked",
            actor=request.user,
            resource=policy,
            patient=policy.patient,
            after={"outcome": check.outcome, "reference": check.reference,
                   "valid_until": str(check.valid_until or "")},
            reason=check.note,
            request=request,
        )
        return Response(
            self.get_serializer(self.get_object()).data, status=http.HTTP_201_CREATED
        )


class PreauthorisationViewSet(viewsets.ModelViewSet):
    """Asking a scheme to agree in advance, and recording the answer."""

    queryset = Preauthorisation.objects.select_related(
        "policy__plan__provider", "patient", "requested_by"
    ).prefetch_related("services")
    serializer_class = PreauthorisationSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "head", "options"]
    required_permissions = {
        "list": "insurance.view_preauthorisation",
        "retrieve": "insurance.view_preauthorisation",
        "create": "insurance.request_preauthorisation",
        "decide": "insurance.request_preauthorisation",
        "outstanding": "insurance.view_preauthorisation",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("patient"):
            queryset = queryset.filter(patient_id=params["patient"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("visit"):
            queryset = queryset.filter(visit_id=params["visit"])
        if params.get("admission"):
            queryset = queryset.filter(admission_id=params["admission"])
        return queryset

    def perform_create(self, serializer):
        policy = serializer.validated_data["policy"]
        authorisation = serializer.save(
            patient=policy.patient, requested_by=self.request.user
        )
        AuditEvent.record(
            action="insurance.preauthorisation_requested",
            actor=self.request.user,
            resource=authorisation,
            patient=policy.patient,
            after={"provider": policy.plan.provider.code,
                   "requested_for": authorisation.requested_for[:200],
                   "estimated": str(authorisation.estimated_amount or "")},
            request=self.request,
        )

    @extend_schema(summary="Authorisations nobody has an answer to yet")
    @action(detail=False, methods=["get"])
    def outstanding(self, request):
        """The chase list. A request nobody followed up is a claim that will be
        rejected months later."""
        queryset = self.get_queryset().filter(status=Preauthorisation.REQUESTED)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(
        request=DecidePreauthorisationSerializer,
        responses={200: PreauthorisationSerializer},
        summary="Record the provider's decision",
    )
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        from django.utils import timezone

        authorisation = self.get_object()
        if authorisation.status != Preauthorisation.REQUESTED:
            return Response(
                {"detail": f"That request is already {authorisation.status}."},
                status=http.HTTP_409_CONFLICT,
            )
        serializer = DecidePreauthorisationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        approved = data["outcome"] == "approved"
        authorisation.status = (
            Preauthorisation.APPROVED if approved else Preauthorisation.DECLINED
        )
        authorisation.reference = data.get("reference", "")
        authorisation.approved_amount = data.get("approved_amount")
        authorisation.valid_from = data.get("valid_from")
        authorisation.valid_until = data.get("valid_until")
        authorisation.decline_reason = data.get("decline_reason", "")
        authorisation.decided_at = timezone.now()
        authorisation.save(update_fields=[
            "status", "reference", "approved_amount", "valid_from", "valid_until",
            "decline_reason", "decided_at",
        ])

        AuditEvent.record(
            action="insurance.preauthorisation_decided",
            actor=request.user,
            outcome=AuditEvent.ALLOWED if approved else AuditEvent.DENIED,
            resource=authorisation,
            patient=authorisation.patient,
            after={"status": authorisation.status, "reference": authorisation.reference,
                   "valid_until": str(authorisation.valid_until or "")},
            reason=authorisation.decline_reason,
            request=request,
        )
        return Response(self.get_serializer(self.get_object()).data)


class ChargeCoverageViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """How charges were split.

    Read-only, with no write verb at all. The split is decided once, when the
    charge is raised; this is the record of that decision. An endpoint that
    could edit it would be an endpoint that rewrites what a patient owed.
    """

    queryset = ChargeCoverage.objects.none()
    serializer_class = ChargeCoverageSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "billing.view_invoice",
        "retrieve": "billing.view_invoice",
        "held": "insurance.view_claimbatch",
        "for_invoice": "billing.view_invoice",
    }

    def get_queryset(self):
        queryset = ChargeCoverage.objects.select_related(
            "invoice_item__invoice__patient", "invoice_item__service",
            "policy__plan__provider", "preauthorisation",
        )
        queryset = self._scope(queryset, field="invoice_item__invoice__facility_id")
        params = self.request.query_params
        if params.get("invoice"):
            queryset = queryset.filter(invoice_item__invoice_id=params["invoice"])
        if params.get("patient"):
            queryset = queryset.filter(invoice_item__invoice__patient_id=params["patient"])
        if params.get("provider"):
            queryset = queryset.filter(policy__plan__provider_id=params["provider"])
        return queryset

    @extend_schema(summary="Charges a scheme would pay for, that nobody can claim yet")
    @action(detail=False, methods=["get"])
    def held(self, request):
        """The billing office's work list. A held line that dropped off every
        list would be money the hospital never asks for."""
        rows = self.get_queryset().exclude(hold_reason="").filter(policy__isnull=False)
        return Response(self.get_serializer(rows, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("invoice", int, required=True)],
        summary="The scheme and patient shares of one invoice",
    )
    @action(detail=False, methods=["get"], url_path="invoice-split",
            url_name="invoice-split")
    def for_invoice(self, request):
        """AC-127. A cashier never asks a patient for the scheme's money."""
        from billing.models import Invoice

        invoice = Invoice.objects.filter(
            pk=request.query_params.get("invoice")
        ).prefetch_related("items__coverage").first()
        if invoice is None:
            return Response(
                {"detail": "No such invoice."}, status=http.HTTP_404_NOT_FOUND
            )
        if not request.user.has_permission("billing.view_invoice", invoice.facility):
            return Response(
                {"detail": "No such invoice."}, status=http.HTTP_404_NOT_FOUND
            )
        split = invoice_split(invoice)
        return Response({
            "invoice": invoice.pk,
            "invoice_number": invoice.invoice_number,
            "total": str(invoice.total),
            "scheme_share": str(split["scheme_share"]),
            "patient_share": str(split["patient_share"]),
            "unresolved": str(split["unresolved"]),
            "lines": self.get_serializer(
                [item.coverage for item in invoice.items.all()
                 if hasattr(item, "coverage")],
                many=True,
            ).data,
        })


class ClaimBatchViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Claims: assembled, submitted, and settled.

    Read-only as a resource with actions for every transition, because each
    transition is a rule with its own permission and audit row. A writable
    `status` field would let a client mark a claim paid.
    """

    queryset = ClaimBatch.objects.none()
    serializer_class = ClaimBatchSerializer
    permission_classes = [HasPermission]

    required_permissions = {
        "list": "insurance.view_claimbatch",
        "retrieve": "insurance.view_claimbatch",
        "claimable": "insurance.view_claimbatch",
        "assemble": "insurance.add_claimbatch",
        "submit": "insurance.submit_claim",
        "acknowledge": "insurance.record_claim_outcome",
        "reject": "insurance.record_claim_outcome",
        "resubmit": "insurance.add_claimbatch",
    }

    def get_queryset(self):
        queryset = ClaimBatch.objects.select_related(
            "provider", "facility", "resubmits", "submitted_by"
        ).prefetch_related(Prefetch("lines", queryset=ClaimLine.objects.all()))
        queryset = self._scope(queryset)
        params = self.request.query_params
        if params.get("provider"):
            queryset = queryset.filter(provider_id=params["provider"])
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("outstanding") == "true":
            queryset = queryset.exclude(
                status__in=[ClaimBatch.DRAFT, ClaimBatch.PAID, ClaimBatch.REJECTED]
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action in {"assemble", "resubmit"}:
            facility_id = request.data.get("facility")
            return (
                Facility.objects.filter(pk=facility_id).first() if facility_id else None
            )
        return None

    @extend_schema(
        parameters=[
            OpenApiParameter("provider", int, required=True),
            OpenApiParameter("facility", int, required=True),
            OpenApiParameter("period_start", str, required=True),
            OpenApiParameter("period_end", str, required=True),
        ],
        summary="What could go on a claim, before assembling one",
    )
    @action(detail=False, methods=["get"])
    def claimable(self, request):
        """A preview, so a billing officer sees what they are about to send."""
        provider = InsuranceProvider.objects.filter(
            pk=request.query_params.get("provider")
        ).first()
        facility = Facility.objects.filter(
            pk=request.query_params.get("facility")
        ).first()
        if provider is None or facility is None:
            return Response(
                {"detail": "Say which provider and facility."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if not request.user.has_permission("insurance.view_claimbatch", facility):
            return Response(
                {"detail": "Not your facility."}, status=http.HTTP_404_NOT_FOUND
            )
        rows = claim_service.claimable_coverages(
            provider=provider, facility=facility,
            period_start=request.query_params.get("period_start"),
            period_end=request.query_params.get("period_end"),
        )
        total = sum(row.scheme_amount for row in rows)
        return Response({
            "provider": provider.code,
            "lines": ChargeCoverageSerializer(rows, many=True).data,
            "total": str(total),
        })

    @extend_schema(
        request=AssembleClaimSerializer,
        responses={201: ClaimBatchSerializer},
        summary="Build a draft claim from charges already raised",
    )
    @action(detail=False, methods=["post"])
    def assemble(self, request):
        """AC-132. Nothing is retyped."""
        serializer = AssembleClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        provider = InsuranceProvider.objects.filter(pk=data["provider"]).first()
        facility = Facility.objects.filter(pk=data["facility"]).first()
        if provider is None or facility is None:
            return Response(
                {"detail": "No such provider or facility."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        resubmits = None
        if data.get("resubmits"):
            resubmits = ClaimBatch.objects.filter(pk=data["resubmits"]).first()
            if resubmits is None:
                return Response(
                    {"resubmits": ["No such claim."]}, status=http.HTTP_400_BAD_REQUEST
                )

        try:
            claim, skipped = claim_service.assemble(
                provider=provider, facility=facility,
                period_start=data["period_start"], period_end=data["period_end"],
                actor=request.user, resubmits=resubmits,
                reason=data.get("reason", ""), request=request,
            )
        except ValidationError as error:
            return _validation_response(error)

        body = self.get_serializer(
            ClaimBatch.objects.prefetch_related("lines").get(pk=claim.pk)
        ).data
        body["skipped"] = len(skipped)
        return Response(body, status=http.HTTP_201_CREATED)

    @extend_schema(request=SubmitClaimSerializer, responses={200: ClaimBatchSerializer})
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        claim = self.get_object()
        serializer = SubmitClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            claim_service.submit(
                claim=claim, actor=request.user, request=request,
                provider_reference=serializer.validated_data["provider_reference"],
            )
        except ValidationError as error:
            return Response({"detail": error.messages}, status=http.HTTP_409_CONFLICT)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(responses={200: ClaimBatchSerializer})
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        claim = self.get_object()
        try:
            claim_service.acknowledge(
                claim=claim, actor=request.user, request=request,
                provider_reference=request.data.get("provider_reference", ""),
            )
        except ValidationError as error:
            return Response({"detail": error.messages}, status=http.HTTP_409_CONFLICT)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(request=RejectClaimSerializer, responses={200: ClaimBatchSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """AC-136. Lines nobody names stay accepted, so a partial rejection
        does not throw away the accepted half."""
        claim = self.get_object()
        serializer = RejectClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data.get("line_reasons") or {}
        line_reasons = {int(key): value for key, value in raw.items()}
        try:
            claim_service.reject(
                claim=claim, actor=request.user,
                reason=serializer.validated_data["reason"],
                line_reasons=line_reasons, request=request,
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(
        request=AssembleClaimSerializer,
        responses={201: ClaimBatchSerializer},
        summary="Correct and resend a rejected claim",
    )
    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        """AC-135. One correction, and the charges move rather than duplicate."""
        rejected = self.get_object()
        payload = {
            "provider": rejected.provider_id,
            "facility": rejected.facility_id,
            "period_start": str(rejected.period_start),
            "period_end": str(rejected.period_end),
            "resubmits": rejected.pk,
            "reason": request.data.get("reason", ""),
        }
        serializer = AssembleClaimSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        try:
            claim, skipped = claim_service.assemble(
                provider=rejected.provider, facility=rejected.facility,
                period_start=rejected.period_start, period_end=rejected.period_end,
                actor=request.user, resubmits=rejected,
                reason=payload["reason"], request=request,
            )
        except ValidationError as error:
            return _validation_response(error)
        body = self.get_serializer(
            ClaimBatch.objects.prefetch_related("lines").get(pk=claim.pk)
        ).data
        body["skipped"] = len(skipped)
        return Response(body, status=http.HTTP_201_CREATED)


class ClaimLineViewSet(FacilityScopedMixin, viewsets.GenericViewSet):
    """One line, for resolving what a scheme did not pay."""

    queryset = ClaimLine.objects.none()
    serializer_class = ResolveShortfallSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "resolve_shortfall": "insurance.write_off_claim_shortfall",
    }

    def get_queryset(self):
        return self._scope(
            ClaimLine.objects.select_related("claim__provider", "claim__facility",
                                             "coverage__invoice_item__invoice"),
            field="claim__facility_id",
        )

    @extend_schema(
        request=ResolveShortfallSerializer,
        summary="Write off, or move to the patient, what the scheme did not pay",
    )
    @action(detail=True, methods=["post"], url_path="shortfall",
            url_name="shortfall")
    def resolve_shortfall(self, request, pk=None):
        """AC-137 (negative).

        A shortfall goes somewhere explicit or nowhere at all: written off with
        a reason, or moved to the patient with a reason. Leaving it as an
        unexplained gap is how a hospital loses money quietly, and moving it to
        a patient without saying why is how it loses trust loudly.
        """
        line = self.get_object()
        serializer = ResolveShortfallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            claim_service.resolve_shortfall(
                line=line, actor=request.user,
                write_off=data["write_off"],
                move_to_patient=data["move_to_patient"],
                reason=data["reason"], request=request,
            )
        except ValidationError as error:
            return _validation_response(error)
        from .serializers import ClaimLineSerializer

        return Response(ClaimLineSerializer(self.get_object()).data)


class ProviderPaymentViewSet(FacilityScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Money in from a scheme, applied line by line."""

    queryset = ProviderPayment.objects.none()
    serializer_class = ProviderPaymentSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "insurance.view_providerpayment",
        "retrieve": "insurance.view_providerpayment",
        "record": "insurance.add_providerpayment",
    }

    def get_queryset(self):
        queryset = ProviderPayment.objects.select_related(
            "provider", "facility", "method", "recorded_by"
        ).prefetch_related("allocations__line")
        queryset = self._scope(queryset)
        if self.request.query_params.get("provider"):
            queryset = queryset.filter(
                provider_id=self.request.query_params["provider"]
            )
        return queryset

    def facility_for_permission(self, request):
        if self.action == "record":
            facility_id = request.data.get("facility")
            return (
                Facility.objects.filter(pk=facility_id).first() if facility_id else None
            )
        return None

    @extend_schema(
        request=RecordProviderPaymentSerializer,
        responses={201: ProviderPaymentSerializer},
        summary="Record a payment and allocate it to claim lines",
    )
    @action(detail=False, methods=["post"])
    def record(self, request):
        """AC-137. Per line, so a short payment is visible against the line it
        short-paid rather than as a lump difference on a claim."""
        serializer = RecordProviderPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        provider = InsuranceProvider.objects.filter(pk=data["provider"]).first()
        facility = Facility.objects.filter(pk=data["facility"]).first()
        method = PaymentMethod.objects.filter(pk=data["method"]).first()
        if provider is None or facility is None or method is None:
            return Response(
                {"detail": "No such provider, facility or payment method."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        allocations = {}
        for entry in data["allocations"]:
            line = ClaimLine.objects.filter(pk=entry["line"]).select_related(
                "claim"
            ).first()
            if line is None:
                return Response(
                    {"allocations": [f"No claim line {entry['line']}."]},
                    status=http.HTTP_400_BAD_REQUEST,
                )
            allocations[line] = entry["amount"]

        try:
            payment = claim_service.record_payment(
                provider=provider, facility=facility, reference=data["reference"],
                amount=data["amount"], received_on=data["received_on"],
                method=method, actor=request.user, allocations=allocations,
                note=data.get("note", ""), request=request,
            )
        except ValidationError as error:
            return _validation_response(error)
        return Response(
            self.get_serializer(
                ProviderPayment.objects.prefetch_related("allocations").get(pk=payment.pk)
            ).data,
            status=http.HTTP_201_CREATED,
        )
