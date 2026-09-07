from django.contrib.auth.models import Permission
from facilities.models import Facility
from rest_framework import serializers

from .models import User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RoleAssignmentSummarySerializer(serializers.Serializer):
    role = serializers.CharField(source="role.name")
    facility = serializers.CharField(source="facility.code", default=None)


class UserSerializer(serializers.ModelSerializer):
    roles = RoleAssignmentSummarySerializer(source="role_assignments", many=True, read_only=True)
    permissions = serializers.SerializerMethodField()
    facilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "staff_id", "is_active", "is_superuser",
                  "roles", "permissions", "facilities"]
        read_only_fields = fields

    def get_permissions(self, user) -> list[str]:
        """Every permission this user holds anywhere, as `app_label.codename`.

        The UI decides which screens and buttons to show from this rather than
        from role names, so a hospital inventing a role does not need a frontend
        release. It mirrors the server's check and is deliberately flattened
        across facilities — it is a convenience for rendering, never the
        enforcement point. Every request is re-checked server-side, with scope.
        """
        if user.is_superuser:
            return ["*"]
        return sorted(
            {
                f"{app_label}.{codename}"
                for app_label, codename in Permission.objects.filter(
                    roles__assignments__user=user
                ).values_list("content_type__app_label", "codename").distinct()
            }
        )

    def get_facilities(self, user) -> list[dict]:
        """Facilities this user is assigned to. An organization-wide assignment
        contributes every facility, which is what the facility picker needs."""
        assignments = user.role_assignments.select_related("facility").all()
        if any(assignment.facility_id is None for assignment in assignments):
            queryset = Facility.objects.filter(is_active=True)
        else:
            queryset = Facility.objects.filter(
                id__in={a.facility_id for a in assignments}, is_active=True
            )
        return [
            {"id": facility.id, "code": facility.code, "name": facility.name,
             "timezone": facility.timezone}
            for facility in queryset
        ]
