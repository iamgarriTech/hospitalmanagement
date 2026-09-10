"""Reports over HTTP, and their CSV export.

The screen and the export share the same row function, which is what makes
AC-177's "the same rows it shows on screen" true rather than intended — there
is no second query for the CSV to drift from.
"""
import csv

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditEvent
from core.permissions import HasPermission

from . import reports as _reports  # noqa: F401 — importing registers them
from .registry import REPORTS, available, check_reports_are_scoped, run

check_reports_are_scoped()


def _parse_date(raw):
    from datetime import datetime

    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d").date()


class ReportViewSet(viewsets.ViewSet):
    """AC-174 to AC-178.

    `list` is the catalogue of what this user may run; `retrieve` runs one.
    There is no endpoint that runs a report without resolving the caller's
    facilities first — `registry.run` is the only path, and it does that
    before anything else.
    """

    permission_classes = [HasPermission]
    # One permission to reach the section at all; each report then declares
    # its own, and the catalogue lists only the ones this caller may run. The
    # section permission is separate because "may see that reporting exists"
    # and "may read the finance figures" are different grants.
    required_permissions = {
        "list": "reporting.view_reports",
        "retrieve": "reporting.view_reports",
        "export": "reporting.view_reports",
    }

    def _run(self, request, key):
        if key not in REPORTS:
            return None, Response({"detail": "No such report."},
                                  status=http.HTTP_404_NOT_FOUND)
        report = REPORTS[key]
        if not (request.user.is_superuser
                or request.user.facilities_for(report.permission)):
            # 404 rather than 403: a report a caller may not run should not be
            # confirmed to exist, for the same reason an out-of-scope patient
            # is not.
            return None, Response({"detail": "No such report."},
                                  status=http.HTTP_404_NOT_FOUND)
        try:
            result = run(
                key, user=request.user,
                date_from=_parse_date(request.query_params.get("date_from")),
                date_to=_parse_date(request.query_params.get("date_to")),
                facility=request.query_params.get("facility") or None,
            )
        except ValueError:
            return None, Response({"detail": "Dates must be YYYY-MM-DD."},
                                  status=http.HTTP_400_BAD_REQUEST)
        return result, None

    @extend_schema(responses={200: OpenApiTypes.OBJECT},
                   summary="Which reports this user may run")
    def list(self, request):
        return Response([
            {
                "key": report.key, "title": report.title, "group": report.group,
                "description": report.description, "notes": report.notes,
                "is_snapshot": report.is_snapshot,
            }
            for report in available(request.user)
        ])

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", str, description="YYYY-MM-DD"),
            OpenApiParameter("date_to", str, description="YYYY-MM-DD"),
            OpenApiParameter("facility", int, description="Narrow to one facility"),
        ],
        responses={200: OpenApiTypes.OBJECT},
        summary="Run a report",
    )
    def retrieve(self, request, pk=None):
        result, refusal = self._run(request, pk)
        return refusal or Response(result)

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", str),
            OpenApiParameter("date_to", str),
            OpenApiParameter("facility", int),
        ],
        responses={200: OpenApiTypes.BINARY},
        summary="The same rows, as CSV",
    )
    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """AC-177. The same rows the screen shows, and the export is audited."""
        result, refusal = self._run(request, pk)
        if refusal is not None:
            return refusal

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="{result["key"]}-'
            f'{result["run_at"]:%Y%m%d-%H%M}.csv"'
        )
        writer = csv.writer(response)

        # The filters go into the file, not just the screen. A CSV that has
        # been emailed twice is exactly where "why do these disagree?" gets
        # asked, and the answer has to travel with it. AC-176.
        writer.writerow([result["title"]])
        writer.writerow(["Run at", result["run_at"].isoformat()])
        writer.writerow(["Run by", result["run_by"]])
        if not result["is_snapshot"]:
            writer.writerow(["From", result["filters"]["date_from"]])
            writer.writerow(["To", result["filters"]["date_to"]])
        else:
            writer.writerow(["Position as at", result["run_at"].isoformat()])
        writer.writerow(["Facilities", result["filters"]["facility_scope"]])
        if result["notes"]:
            writer.writerow(["Note", result["notes"]])
        writer.writerow([])

        columns = result["columns"]
        writer.writerow([column["label"] for column in columns])
        for row in result["rows"]:
            writer.writerow([row.get(column["key"], "") for column in columns])

        AuditEvent.record(
            action="report.exported", actor=request.user, resource=None,
            after={"report": result["key"], "rows": result["row_count"],
                   "filters": {
                       "date_from": str(result["filters"]["date_from"]),
                       "date_to": str(result["filters"]["date_to"]),
                       "facilities": result["filters"]["facilities"],
                   }},
            request=request,
        )
        return response
