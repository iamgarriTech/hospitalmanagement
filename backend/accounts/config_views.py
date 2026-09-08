"""Runtime administration of roles, permissions and staff access.

Roles are database rows, so this is how a hospital creates one — the PRD's
requirement that permissions are not hard-coded is only real if there is a
screen for it. Every change here is a security-relevant event and is audited
with before/after values.
"""
from django.contrib.auth.models import Permission
from django.db import models
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission

from .models import Role, RoleAssignment, User
from .serializers import UserSerializer


class PermissionSerializer(serializers.ModelSerializer):
    app_label = serializers.CharField(source="content_type.app_label", read_only=True)
    codename_full = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ["id", "name", "codename", "app_label", "codename_full"]

    def get_codename_full(self, permission) -> str:
        return f"{permission.content_type.app_label}.{permission.codename}"


class RoleSerializer(serializers.ModelSerializer):
    permission_codes = serializers.SerializerMethodField()
    assignment_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "name", "description", "discount_limit", "permissions",
                  "permission_codes", "assignment_count", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_permission_codes(self, role) -> list[str]:
        return sorted(
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in role.permissions.all()
        )

    def get_assignment_count(self, role) -> int:
        return role.assignments.count()


class RoleAssignmentSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    facility_code = serializers.CharField(
        source="facility.code", read_only=True, default=None
    )

    class Meta:
        model = RoleAssignment
        fields = ["id", "user", "user_email", "user_name", "role", "role_name",
                  "facility", "facility_code", "granted_at"]
        read_only_fields = ["id", "granted_at"]


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """Every permission the system defines, for building roles."""

    queryset = Permission.objects.select_related("content_type").exclude(
        # Django's own bookkeeping models are not hospital concepts and only
        # clutter the role builder.
        content_type__app_label__in=["contenttypes", "sessions", "auth"]
    ).order_by("content_type__app_label", "codename")
    serializer_class = PermissionSerializer
    permission_classes = [HasPermission]
    pagination_class = None
    required_permissions = {
        "list": "accounts.view_role",
        "retrieve": "accounts.view_role",
    }


class RoleViewSet(viewsets.ModelViewSet):
    """Create and change roles at runtime."""

    queryset = Role.objects.prefetch_related("permissions__content_type", "assignments")
    serializer_class = RoleSerializer
    permission_classes = [HasPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    required_permissions = {
        "list": "accounts.view_role",
        "retrieve": "accounts.view_role",
        "create": "accounts.add_role",
        "partial_update": "accounts.change_role",
        "assign": "accounts.change_roleassignment",
        "revoke": "accounts.delete_roleassignment",
    }

    def perform_create(self, serializer):
        role = serializer.save()
        AuditEvent.record(
            action="role.created",
            actor=self.request.user,
            resource=role,
            after={"name": role.name,
                   "permissions": serializer.data.get("permission_codes", [])},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = sorted(
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in serializer.instance.permissions.all()
        )
        before_limit = str(serializer.instance.discount_limit)
        role = serializer.save()
        after = sorted(
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in role.permissions.all()
        )
        AuditEvent.record(
            action="role.permissions_changed",
            actor=self.request.user,
            resource=role,
            before={"permissions": before, "discount_limit": before_limit},
            after={"permissions": after, "discount_limit": str(role.discount_limit)},
            request=self.request,
        )

    @extend_schema(request=RoleAssignmentSerializer, summary="Grant this role to a user")
    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        role = self.get_object()
        user = User.objects.filter(pk=request.data.get("user")).first()
        if user is None:
            return Response({"user": ["No such user."]}, status=http.HTTP_400_BAD_REQUEST)
        facility_id = request.data.get("facility") or None
        assignment, created = RoleAssignment.objects.get_or_create(
            user=user, role=role, facility_id=facility_id,
            defaults={"granted_by": request.user},
        )
        if created:
            AuditEvent.record(
                action="role.assigned",
                actor=request.user,
                resource=user,
                facility=assignment.facility,
                after={"user": user.email, "role": role.name,
                       "facility": assignment.facility.code if assignment.facility else None},
                request=request,
            )
        return Response(
            RoleAssignmentSerializer(assignment).data,
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK,
        )

    @extend_schema(summary="Revoke an assignment of this role")
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        role = self.get_object()
        assignment = RoleAssignment.objects.filter(
            pk=request.data.get("assignment"), role=role
        ).select_related("user", "facility").first()
        if assignment is None:
            return Response({"assignment": ["No such assignment."]},
                            status=http.HTTP_400_BAD_REQUEST)
        snapshot = {"user": assignment.user.email, "role": role.name,
                    "facility": assignment.facility.code if assignment.facility else None}
        actor_user = assignment.user
        assignment.delete()
        AuditEvent.record(
            action="role.revoked",
            actor=request.user,
            resource=actor_user,
            before=snapshot,
            request=request,
        )
        return Response(status=http.HTTP_204_NO_CONTENT)


class StaffViewSet(viewsets.ReadOnlyModelViewSet):
    """Staff accounts and what they hold."""

    queryset = User.objects.none()
    serializer_class = UserSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "accounts.view_user",
        "retrieve": "accounts.view_user",
    }

    def get_queryset(self):
        queryset = User.objects.prefetch_related(
            "role_assignments__role", "role_assignments__facility"
        ).order_by("full_name")
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                models.Q(full_name__icontains=search) | models.Q(email__icontains=search)
            )
        return queryset
