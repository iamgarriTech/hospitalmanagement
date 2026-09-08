from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent

from .models import FailedLoginAttempt, RoleAssignment
from .serializers import LoginSerializer, UserSerializer

DETAIL_RESPONSE = inline_serializer(
    name="Detail", fields={"detail": drf_serializers.CharField()}
)


@extend_schema(
    responses={200: DETAIL_RESPONSE},
    summary="Set the CSRF cookie",
    tags=["auth"],
)
@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    """Sets the CSRF cookie so the SPA can echo it back on writes."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie set"})


@extend_schema(
    responses={200: OpenApiResponse(description="Deployment metadata for the sign-in screen")},
    summary="Public deployment metadata",
    tags=["auth"],
)
class MetaView(APIView):
    """What the sign-in screen needs before anyone has signed in.

    Sample logins are served from here rather than hardcoded in the frontend for
    two reasons: a hardcoded list drifts from the seed the moment a role is
    renamed, and — more importantly — production must be able to withhold them.
    When DEMO_MODE is off this returns an empty list, so there is no build of the
    frontend that can leak working credentials.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from facilities.models import Organization

        organization = Organization.objects.first()
        return Response(
            {
                # The hospital's own name, not the product's: staff signing in
                # should see where they work.
                "organization": organization.name if organization else None,
                "demo_mode": settings.DEMO_MODE,
                "sample_logins": self._sample_logins() if settings.DEMO_MODE else [],
            }
        )

    @staticmethod
    def _sample_logins():
        """One account per role that has one, ordered the way the hospital runs
        so an evaluator can walk it top to bottom: the outpatient day, then the
        inpatient stay, then the back office."""
        order = [
            # Outpatient
            "Receptionist", "Nurse", "Doctor", "Consultant",
            "Laboratory Scientist", "Laboratory Technician",
            "Radiographer", "Radiologist", "Imaging Registrar",
            "Pharmacist",
            # Inpatient
            "Ward Doctor", "Ward Nurse", "Ward Manager",
            # Back office
            "Cashier", "Accountant", "Medical Records Officer",
            "Hospital Administrator",
        ]
        seen = {}
        for assignment in (
            RoleAssignment.objects.select_related("user", "role", "facility")
            .filter(user__is_active=True)
            .order_by("user_id")
        ):
            role = assignment.role.name
            if role in seen or not assignment.user.email.endswith("@demo.test"):
                continue
            seen[role] = {
                "role": role,
                "name": assignment.user.full_name,
                "email": assignment.user.email,
                "password": settings.DEMO_PASSWORD,
                "facility": assignment.facility.code if assignment.facility else None,
            }
        ranked = sorted(
            seen.values(),
            key=lambda entry: order.index(entry["role"]) if entry["role"] in order else 99,
        )
        return ranked


@extend_schema(
    request=LoginSerializer,
    responses={
        200: UserSerializer,
        401: OpenApiResponse(DETAIL_RESPONSE, "Invalid credentials"),
        429: OpenApiResponse(DETAIL_RESPONSE, "Locked after repeated failures"),
    },
    summary="Log in",
    tags=["auth"],
)
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        if FailedLoginAttempt.is_locked(email):
            AuditEvent.record(
                action="login.locked_out",
                outcome=AuditEvent.DENIED,
                after={"email": email},
                request=request,
            )
            return Response(
                {
                    "detail": (
                        f"Account locked after {settings.FAILED_LOGIN_LIMIT} failed "
                        f"attempts. Try again later or contact an administrator."
                    )
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, email=email, password=password)
        if user is None:
            FailedLoginAttempt.objects.create(
                email=email, ip_address=request.META.get("REMOTE_ADDR")
            )
            AuditEvent.record(
                action="login.failed",
                outcome=AuditEvent.DENIED,
                after={"email": email},
                request=request,
            )
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        AuditEvent.record(action="login.succeeded", actor=user, request=request)
        return Response(UserSerializer(user).data)


@extend_schema(
    request=None, responses={204: None}, summary="Log out", tags=["auth"]
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        logout(request)
        AuditEvent.record(action="logout", actor=user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    responses={200: UserSerializer}, summary="Current user and roles", tags=["auth"]
)
class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)
