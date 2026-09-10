from django.core.exceptions import ValidationError
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission

from . import outbox
from .models import Notification, OutboundMessage
from .serializers import NotificationSerializer, OutboundMessageSerializer


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """A user's own notifications.

    No permission codename: these are addressed to the requesting user, and the queryset
    is the boundary. Nobody can read anyone else's.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    # For schema introspection only; get_queryset scopes to the requesting user.
    queryset = Notification.objects.none()

    def get_queryset(self):
        queryset = Notification.objects.filter(
            recipient=self.request.user
        ).select_related("patient")
        if self.request.query_params.get("unread") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        return queryset

    @extend_schema(request=None, responses={200: None}, summary="Mark one as read")
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        updated = self.get_queryset().filter(pk=pk, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response({"marked_read": updated})


class OutboxViewSet(viewsets.ReadOnlyModelViewSet):
    """The outbound queue. AC-182.

    Read-only apart from `retry`. A failed message stays visible and is never
    deleted, because "the patient was told" and "we tried to tell them and
    could not" have to be different answers afterwards.
    """

    queryset = OutboundMessage.objects.none()
    serializer_class = OutboundMessageSerializer
    permission_classes = [HasPermission]
    required_permissions = {
        "list": "notifications.view_outbox",
        "retrieve": "notifications.view_outbox",
        "retry": "notifications.retry_outbound_message",
        "summary": "notifications.view_outbox",
    }

    def get_queryset(self):
        queryset = OutboundMessage.objects.all()
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status__in=params["status"].split(","))
        if params.get("failed") == "true":
            queryset = queryset.filter(status=OutboundMessage.FAILED)
        return queryset

    @extend_schema(request=None, responses={200: OutboundMessageSerializer},
                   summary="Put a failed message back in the queue")
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        message = self.get_object()
        try:
            outbox.retry(message, actor=request.user)
        except ValidationError as refusal:
            return Response({"detail": refusal.messages},
                            status=status.HTTP_409_CONFLICT)
        AuditEvent.record(
            action="outbox.retried", actor=request.user, resource=message,
            facility=message.facility,
            after={"channel": message.channel, "to": message.to_address,
                   "previous_error": message.last_error},
            request=request,
        )
        return Response(self.get_serializer(message).data)

    @extend_schema(responses={200: OpenApiTypes.OBJECT},
                   summary="What is stuck, and what gave up")
    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(outbox.summary())
