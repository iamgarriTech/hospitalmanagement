from rest_framework import serializers

from .models import Notification, OutboundMessage


class NotificationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields = ["id", "kind", "urgency", "subject", "body", "patient", "patient_name",
                  "resource_type", "resource_id", "created_at", "read_at"]
        read_only_fields = fields


class OutboundMessageSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source="get_channel_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    attempts_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = OutboundMessage
        fields = ["id", "channel", "channel_display", "to_address", "subject",
                  "source_type", "source_id", "facility", "patient_reference",
                  "status", "status_display", "attempts", "max_attempts",
                  "attempts_left", "next_attempt_at", "last_error",
                  "provider_reference", "created_at", "sent_at", "failed_at"]
        read_only_fields = fields
        # `body` is deliberately absent. An operator chasing a stuck queue
        # needs to know a message failed and to whom, not to read what it
        # said — a result notification's text is clinical content.
