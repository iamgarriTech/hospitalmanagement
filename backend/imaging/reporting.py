"""Scheduling, performing, reporting, verifying and amending an examination.

Out of the views because the rules are the substance: which states can follow
which, that an unverified report must not reach the requesting clinician as a
finding, and that an amendment appends rather than overwrites.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditEvent
from billing.models import charge
from notifications.models import Notification

from .models import ImagingOrderItem, ImagingReport


@transaction.atomic
def schedule(*, order_item, actor, when, note="", request=None):
    """Give an examination a slot. AC-95."""
    order_item.advance_to(ImagingOrderItem.SCHEDULED)
    order_item.scheduled_for = when
    order_item.scheduled_by = actor
    if note:
        order_item.technique_note = note
    order_item.save(
        update_fields=["status", "scheduled_for", "scheduled_by", "technique_note"]
    )
    order = order_item.order
    AuditEvent.record(
        action="imaging.scheduled",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={"procedure": order_item.procedure.code_short,
               "scheduled_for": when.isoformat()},
        request=request,
    )
    return order_item


@transaction.atomic
def perform(*, order_item, actor, at=None, accession_number="", views_taken="",
            technique_note="", contrast_given="", request=None):
    """Record that the examination actually happened.

    This is what the department bills and what the patient was exposed to, so it
    is a recorded act with a named operator rather than a status somebody set.
    The charge is raised here, not at ordering: a request that is never
    performed must not appear on a bill.
    """
    order_item.advance_to(ImagingOrderItem.PERFORMED)
    order_item.performed_at = at or timezone.now()
    order_item.performed_by = actor
    order_item.accession_number = accession_number
    order_item.views_taken = views_taken
    order_item.technique_note = technique_note or order_item.technique_note
    order_item.contrast_given = contrast_given
    order_item.save(update_fields=[
        "status", "performed_at", "performed_by", "accession_number", "views_taken",
        "technique_note", "contrast_given",
    ])

    order = order_item.order
    procedure = order_item.procedure
    if procedure.service_id and procedure.price_at(order.facility) is not None:
        charge(
            visit=order.visit,
            admission=order.admission,
            service_code=procedure.service.code,
            description=f"{procedure.name} — {order_item.performed_at:%d %b %Y}",
            source_type="imaging.ImagingOrderItem",
            source_id=order_item.pk,
            actor=actor,
        )

    AuditEvent.record(
        action="imaging.performed",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={
            "procedure": procedure.code_short,
            "accession_number": accession_number,
            "views": views_taken,
            "contrast": contrast_given,
        },
        request=request,
    )
    return order_item


@transaction.atomic
def write_report(*, order_item, actor, findings, conclusion, comparison="",
                 is_critical=False, critical_finding="", request=None):
    """Record a report against a performed examination. AC-96.

    Unverified. It is written here and released by `verify`, because typing a
    report and signing it off are different acts — the same separation the
    laboratory makes between entering a value and releasing it.
    """
    if not findings.strip() or not conclusion.strip():
        raise ValidationError(
            "A report needs both findings and a conclusion. The conclusion is "
            "what a clinician acts on."
        )
    if is_critical and not critical_finding.strip():
        raise ValidationError(
            {"critical_finding": "Say in one line what has to be acted on."}
        )
    if order_item.reports.filter(is_current=True).exists():
        raise ValidationError(
            "This examination already has a report. Amend it rather than "
            "writing a second."
        )

    order_item.advance_to(ImagingOrderItem.REPORTED)
    order_item.save(update_fields=["status"])

    report = ImagingReport.objects.create(
        order_item=order_item,
        findings=findings.strip(),
        conclusion=conclusion.strip(),
        comparison=comparison,
        is_critical=is_critical,
        critical_finding=critical_finding.strip(),
        reported_by=actor,
    )
    order = order_item.order
    AuditEvent.record(
        action="imaging.reported",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={"procedure": order_item.procedure.code_short,
               "critical": is_critical,
               "conclusion": report.conclusion[:200]},
        request=request,
    )
    return report


@transaction.atomic
def verify(*, report, actor, request=None):
    """Release a report to the requesting clinician. AC-96.

    Until this happens the report exists but reaches nobody: an unverified
    radiology report is a draft, and a clinician acting on a draft is acting on
    something the radiologist has not stood behind.
    """
    if report.is_verified:
        raise ValidationError("That report has already been verified.")
    if not report.is_current:
        raise ValidationError("That report has been superseded.")

    order_item = report.order_item
    if order_item.status != ImagingOrderItem.REPORTED:
        raise ValidationError(
            f"Only a reported examination can be verified (currently: "
            f"{order_item.get_status_display().lower()})."
        )

    report.verified_by = actor
    report.verified_at = timezone.now()
    report.save(update_fields=["verified_by", "verified_at"])

    order_item.advance_to(ImagingOrderItem.VERIFIED)
    order_item.save(update_fields=["status"])

    order = order_item.order
    Notification.objects.create(
        recipient=order.ordered_by,
        # A critical finding is a different kind of notification, not a louder
        # one: the department chases these until they are answered for.
        kind=Notification.CRITICAL_RESULT if report.is_critical
        else Notification.RESULT_READY,
        urgency=Notification.URGENT if report.is_critical else Notification.NORMAL,
        subject=f"{order_item.procedure.name} reported for {order.patient.full_name}",
        body=(
            f"CRITICAL: {report.critical_finding}" if report.is_critical
            else report.conclusion[:300]
        ),
        patient=order.patient,
        resource_type="imaging.ImagingReport",
        resource_id=str(report.pk),
    )
    AuditEvent.record(
        action="imaging.verified",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={"procedure": order_item.procedure.code_short,
               "critical": report.is_critical,
               "version": report.version},
        request=request,
    )
    if report.is_critical:
        AuditEvent.record(
            action="imaging.critical_finding_flagged",
            actor=actor,
            resource=order,
            patient=order.patient,
            facility=order.facility,
            after={"finding": report.critical_finding,
                   "requesting_clinician": order.ordered_by.email},
            request=request,
        )
    return report


@transaction.atomic
def amend_report(*, report, actor, reason, findings=None, conclusion=None,
                 is_critical=None, critical_finding=None, request=None):
    """Append a version. AC-97.

    The superseded report stays exactly as written and prints as amended. A
    radiologist correcting "no fracture" to "undisplaced fracture" must not
    erase the first report — somebody made a decision on it, and that decision
    is only explicable against what it said.
    """
    if not (reason or "").strip():
        raise ValidationError("A reason is required to amend a report.")
    if not report.is_current:
        raise ValidationError("That report has already been superseded.")
    if not report.is_verified:
        raise ValidationError(
            "That report is not verified yet, so there is nothing to amend — "
            "correct it before releasing it."
        )

    current = ImagingReport.objects.select_for_update().get(pk=report.pk)
    order_item = current.order_item
    order = order_item.order

    critical = current.is_critical if is_critical is None else is_critical
    finding = current.critical_finding if critical_finding is None else critical_finding
    if critical and not (finding or "").strip():
        raise ValidationError(
            {"critical_finding": "Say in one line what has to be acted on."}
        )

    ImagingReport.objects.filter(pk=current.pk).update(is_current=False)
    replacement = ImagingReport.objects.create(
        order_item=order_item,
        findings=(findings if findings is not None else current.findings).strip(),
        conclusion=(conclusion if conclusion is not None else current.conclusion).strip(),
        comparison=current.comparison,
        is_critical=critical,
        critical_finding=(finding or "").strip(),
        version=current.version + 1,
        is_current=True,
        amends=current,
        amendment_reason=reason.strip(),
        reported_by=actor,
        # An amendment is released in the same act. It is written by someone
        # holding the amend permission, which the verify permission also gates,
        # and leaving it provisional would mean the clinician keeps reading the
        # version now known to be wrong.
        verified_by=actor,
        verified_at=timezone.now(),
    )

    Notification.objects.create(
        recipient=order.ordered_by,
        kind=Notification.CRITICAL_RESULT if critical else Notification.RESULT_READY,
        # An amendment is always urgent, critical or not: the clinician has been
        # reading a version now known to be wrong.
        urgency=Notification.URGENT,
        subject=(
            f"AMENDED report: {order_item.procedure.name} for "
            f"{order.patient.full_name}"
        ),
        body=f"{reason.strip()} — now reads: {replacement.conclusion[:250]}",
        patient=order.patient,
        resource_type="imaging.ImagingReport",
        resource_id=str(replacement.pk),
    )
    AuditEvent.record(
        action="imaging.report_amended",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        before={"conclusion": current.conclusion, "critical": current.is_critical,
                "version": current.version},
        after={"conclusion": replacement.conclusion, "critical": replacement.is_critical,
               "version": replacement.version},
        reason=reason.strip(),
        request=request,
    )
    return replacement


@transaction.atomic
def acknowledge_critical(*, report, actor, action_taken, request=None):
    """Record that a critical finding reached someone. AC-98.

    Same requirement as a critical laboratory result: an acknowledgement with no
    action recorded is a tick box, not a record.
    """
    from .models import CriticalFindingAcknowledgement

    if not report.is_critical:
        raise ValidationError("That report has no critical finding.")
    if not (action_taken or "").strip():
        raise ValidationError(
            {"action_taken": "Say what was done about it."}
        )

    order = report.order_item.order
    acknowledgement = CriticalFindingAcknowledgement.objects.create(
        report=report, acknowledged_by=actor, action_taken=action_taken.strip()
    )
    AuditEvent.record(
        action="imaging.critical_finding_acknowledged",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={"finding": report.critical_finding,
               "minutes_to_acknowledge": acknowledgement.minutes_to_acknowledge},
        reason=acknowledgement.action_taken,
        request=request,
    )
    return acknowledgement


def unacknowledged_critical_findings(*, facility=None):
    """Verified critical findings nobody has answered for.

    The list the department chases. Mirrors the laboratory's, because the
    failure it guards against is the same one.
    """
    reports = ImagingReport.objects.filter(
        is_critical=True, is_current=True, verified_at__isnull=False,
        acknowledgements__isnull=True,
    ).select_related(
        "order_item__procedure", "order_item__order__patient",
        "order_item__order__ordered_by", "reported_by",
    ).order_by("verified_at")
    if facility is not None:
        reports = reports.filter(order_item__order__facility=facility)
    return reports
