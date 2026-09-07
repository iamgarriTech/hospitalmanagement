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

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "staff_id", "is_active", "is_superuser", "roles"]
        read_only_fields = fields
