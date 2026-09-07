from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = ["id", "kind", "urgency", "subject", "body", "patient", "patient_name",
                  "resource_type", "resource_id", "created_at", "read_at"]
        read_only_fields = fields
