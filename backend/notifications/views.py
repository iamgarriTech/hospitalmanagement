from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer


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
