from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditEvent

from .models import FailedLoginAttempt
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
