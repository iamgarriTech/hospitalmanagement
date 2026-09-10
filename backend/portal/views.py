"""The patient portal.

**Every endpoint derives the patient from the session.** Not from a path
parameter, not from a query parameter, not from a body field. There is no
parameter anywhere in this module that names a patient, which is how AC-183's
"nothing else, ever, including no other patient's data through any parameter"
is satisfied — the request has no way to ask about somebody else.

`request.user.patient` is the only source, and it comes from a hashed session
token. A patient who edits a URL changes nothing.
"""
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent

from .authentication import COOKIE_NAME, PortalAuthentication
from .models import PortalAccount, PortalLoginAttempt, PortalSession
from .permissions import IsPortalPatient
from .serializers import (
    PortalBillSerializer,
    PortalLoginSerializer,
    PortalMedicationSerializer,
    PortalPasswordChangeSerializer,
    PortalResultSerializer,
    PortalVisitSerializer,
)


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _set_cookie(response, token, request):
    """The portal cookie: HttpOnly, its own name, short-lived.

    A different name from the staff session on purpose — the browser, the
    proxy and anybody reading a log can tell the two apart, and neither can
    ever be presented as the other.
    """
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=60 * 60 * 2,
        httponly=True,          # guarantee 9: not readable by JavaScript
        secure=request.is_secure(),
        samesite="Lax",
        path="/",
    )
    return response


class PortalLoginView(APIView):
    """Portal sign-in. Shares nothing with staff sign-in. AC-184."""

    authentication_classes = []
    permission_classes = []

    @extend_schema(request=PortalLoginSerializer,
                   responses={200: OpenApiTypes.OBJECT},
                   summary="Sign in to the patient portal")
    def post(self, request):
        serializer = PortalLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["login_identifier"].strip()
        password = serializer.validated_data["password"]
        ip = _client_ip(request)

        if PortalLoginAttempt.is_locked(identifier):
            AuditEvent.record(
                action="portal.login_locked_out", outcome=AuditEvent.DENIED,
                after={"identifier": identifier}, request=request,
            )
            return Response(
                {"detail": "Too many attempts. Try again in half an hour, or ask "
                           "the hospital to reset your password."},
                status=http.HTTP_429_TOO_MANY_REQUESTS,
            )

        account = PortalAccount.objects.select_related("patient").filter(
            login_identifier=identifier
        ).first()

        # One message and one code for every failure. A different response for
        # "no such account" tells anybody who asks which identifiers are
        # registered patients, which is itself a disclosure.
        if account is None or not account.is_active or not account.check_password(
            password
        ):
            PortalLoginAttempt.record(identifier, ip)
            AuditEvent.record(
                action="portal.login_failed", outcome=AuditEvent.DENIED,
                after={"identifier": identifier}, request=request,
            )
            return Response({"detail": "Those details do not match an account."},
                            status=http.HTTP_401_UNAUTHORIZED)

        session, token = PortalSession.start(
            account, ip_address=ip,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        account.last_login_at = timezone.now()
        account.save(update_fields=["last_login_at"])

        AuditEvent.record(
            action="portal.login_succeeded", actor=None,
            patient=account.patient, facility=account.patient.facility,
            after={"identifier": identifier, "session": session.pk},
            request=request,
        )
        response = Response({
            "patient_name": account.patient.full_name,
            "hospital_number": account.patient.hospital_number,
            "must_change_password": account.must_change_password,
            "expires_at": session.expires_at,
        })
        return _set_cookie(response, token, request)


class PortalLogoutView(APIView):
    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalPatient]

    @extend_schema(request=None, responses={204: None}, summary="Sign out")
    def post(self, request):
        request.user.session.end()
        AuditEvent.record(
            action="portal.logout", patient=request.user.patient,
            facility=request.user.patient.facility, request=request,
        )
        response = Response(status=http.HTTP_204_NO_CONTENT)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response


class PortalMeView(APIView):
    """Who is signed in, and nothing about anybody else."""

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalPatient]

    @extend_schema(responses={200: OpenApiTypes.OBJECT},
                   summary="The signed-in patient")
    def get(self, request):
        patient = request.user.patient
        return Response({
            "patient_name": patient.full_name,
            "hospital_number": patient.hospital_number,
            "date_of_birth": patient.date_of_birth,
            "must_change_password": request.user.account.must_change_password,
            "session_expires_at": request.user.session.expires_at,
        })

    @extend_schema(request=PortalPasswordChangeSerializer, responses={204: None},
                   summary="Change your own password")
    def post(self, request):
        serializer = PortalPasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = request.user.account
        if not account.check_password(serializer.validated_data["current_password"]):
            return Response({"current_password": ["That is not your current password."]},
                            status=http.HTTP_400_BAD_REQUEST)
        account.set_password(serializer.validated_data["new_password"])
        account.must_change_password = False
        account.save(update_fields=["password_hash", "must_change_password"])

        # Every other session ends. A patient changing their password because
        # somebody else has been in their account expects exactly that.
        PortalSession.objects.filter(
            account=account, ended_at__isnull=True
        ).exclude(pk=request.user.session.pk).update(ended_at=timezone.now())

        AuditEvent.record(
            action="portal.password_changed", patient=account.patient,
            facility=account.patient.facility, request=request,
        )
        return Response(status=http.HTTP_204_NO_CONTENT)


class PortalRecordViewSet(viewsets.ViewSet):
    """What a patient may see of their own record. AC-183, AC-185.

    Four things, each read from the session's patient. There is no parameter
    in any of these that names a patient — the only patient reachable from a
    portal session is that session's own.
    """

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalPatient]

    @extend_schema(responses={200: PortalVisitSerializer(many=True)},
                   summary="Your appointments and attendances")
    @action(detail=False, methods=["get"])
    def visits(self, request):
        from visits.models import Visit

        records = Visit.objects.filter(
            patient=request.user.patient
        ).select_related("facility", "clinic").order_by("-arrived_at")[:50]
        return Response(PortalVisitSerializer(records, many=True).data)

    @extend_schema(responses={200: PortalResultSerializer(many=True)},
                   summary="Your verified results")
    @action(detail=False, methods=["get"])
    def results(self, request):
        """AC-185. Verified only.

        An unverified result is a number nobody has signed. Showing one to a
        patient means they may act on a figure a scientist is about to
        correct — and they will read it before anybody can explain it.
        """
        from laboratory.models import LabResult

        records = LabResult.objects.filter(
            order_item__order__patient=request.user.patient,
            is_current=True,
            order_item__verified_at__isnull=False,
        ).select_related(
            "order_item__test", "order_item__order", "parameter"
        ).order_by("-order_item__verified_at")[:100]
        return Response(PortalResultSerializer(records, many=True).data)

    @extend_schema(responses={200: PortalMedicationSerializer(many=True)},
                   summary="Your current medication")
    @action(detail=False, methods=["get"])
    def medication(self, request):
        from pharmacy.models import PrescriptionItem

        records = PrescriptionItem.objects.filter(
            prescription__patient=request.user.patient,
            prescription__status__in=["active", "partially_dispensed", "dispensed"],
        ).exclude(status="cancelled").select_related(
            "medication", "prescription"
        ).order_by("-prescription__prescribed_at")[:50]
        return Response(PortalMedicationSerializer(records, many=True).data)

    @extend_schema(responses={200: PortalBillSerializer(many=True)},
                   summary="Your bills")
    @action(detail=False, methods=["get"])
    def bills(self, request):
        from billing.models import Invoice

        records = Invoice.objects.filter(
            patient=request.user.patient
        ).exclude(status=Invoice.DRAFT).select_related(
            "facility"
        ).prefetch_related("items", "payments__refunds").order_by("-created_at")[:50]
        return Response(PortalBillSerializer(records, many=True).data)


class PortalAccountAdminViewSet(viewsets.ModelViewSet):
    """Staff creating and suspending portal logins.

    This one *is* a staff endpoint — it is how a records officer gives a
    patient access — so it sits behind the ordinary staff session and
    permission system. It can create an account and suspend one; it cannot
    read anything through it.
    """

    from core.permissions import HasPermission  # noqa: PLC0415 — avoids a cycle

    queryset = PortalAccount.objects.none()
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "portal.view_portalaccount",
        "retrieve": "portal.view_portalaccount",
        "create": "portal.manage_portal_accounts",
        "partial_update": "portal.manage_portal_accounts",
        "reset_password": "portal.manage_portal_accounts",
    }

    def get_serializer_class(self):
        from .serializers import PortalAccountSerializer

        return PortalAccountSerializer

    def get_queryset(self):
        return PortalAccount.objects.select_related("patient", "created_by")

    def perform_create(self, serializer):
        account = serializer.save(created_by=self.request.user)
        AuditEvent.record(
            action="portal_account.created", actor=self.request.user,
            resource=account, patient=account.patient,
            facility=account.patient.facility,
            after={"identifier": account.login_identifier},
            request=self.request,
        )

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT},
                   summary="Issue a new temporary password")
    @action(detail=True, methods=["post"], url_path="reset-password",
            url_name="reset-password")
    def reset_password(self, request, pk=None):
        import secrets

        account = self.get_object()
        temporary = secrets.token_urlsafe(9)
        account.set_password(temporary)
        account.must_change_password = True
        account.save(update_fields=["password_hash", "must_change_password"])
        # Every live session ends: a reset exists because somebody has lost
        # control of the account.
        PortalSession.objects.filter(
            account=account, ended_at__isnull=True
        ).update(ended_at=timezone.now())

        AuditEvent.record(
            action="portal_account.password_reset", actor=request.user,
            resource=account, patient=account.patient,
            facility=account.patient.facility, request=request,
        )
        # Returned once, to be handed to the patient. Never stored in clear
        # and never in the audit row.
        return Response({
            "temporary_password": temporary,
            "note": "Give this to the patient. It is not stored and cannot be "
                    "shown again. They must change it when they sign in.",
        })
