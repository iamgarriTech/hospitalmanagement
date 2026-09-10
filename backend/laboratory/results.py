"""Result entry, verification and amendment.

Kept out of the views because the rules are the substance: which reference range applies,
what counts as critical, who must be told, and what happens to a value that turns out to
be wrong after it was verified.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditEvent
from notifications import outbox
from notifications.models import Notification, OutboundMessage

from .models import LabOrderItem, LabResult


def _as_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValidationError(f"{value!r} is not a number.")


def _classify(parameter, numeric, patient):
    """Pick the range that applies to this patient and flag the value against it."""
    reference = parameter.range_for(sex=patient.sex, age_years=patient.age_years)
    if reference is None or numeric is None:
        return LabResult.NORMAL, None
    return reference.classify(numeric), reference


@transaction.atomic
def enter_results(*, order_item, entries, actor, request=None):
    """Record values for the parameters of one ordered test.

    A test with a dozen parameters produces a dozen rows, each flagged on its own.
    """
    if order_item.status not in (LabOrderItem.PROCESSING, LabOrderItem.RESULTED):
        raise ValidationError(
            f"Results can only be entered once the specimen is being processed "
            f"(currently: {order_item.get_status_display().lower()})."
        )

    valid_parameters = {
        parameter.pk: parameter for parameter in order_item.test.parameters.all()
    }
    if not valid_parameters:
        raise ValidationError(f"{order_item.test.name} has no parameters configured.")

    patient = order_item.order.patient
    created = []
    for entry in entries:
        parameter = valid_parameters.get(entry.get("parameter"))
        if parameter is None:
            raise ValidationError(
                f"Parameter {entry.get('parameter')} does not belong to "
                f"{order_item.test.name}."
            )
        if LabResult.objects.filter(
            order_item=order_item, parameter=parameter, is_current=True
        ).exists():
            raise ValidationError(
                f"{parameter.name} already has a result. Amend it instead of re-entering."
            )

        numeric = _as_decimal(entry.get("value_numeric"))
        flag, reference = _classify(parameter, numeric, patient)
        created.append(
            LabResult.objects.create(
                order_item=order_item,
                parameter=parameter,
                value_numeric=numeric,
                value_text=entry.get("value_text", "") or "",
                unit=parameter.unit,
                flag=flag,
                range_low=reference.low if reference else None,
                range_high=reference.high if reference else None,
                range_note=reference.note if reference else "",
                entered_by=actor,
                comment=entry.get("comment", "") or "",
            )
        )

    if order_item.status == LabOrderItem.PROCESSING:
        order_item.advance_to(LabOrderItem.RESULTED)
        order_item.save(update_fields=["status"])

    AuditEvent.record(
        action="lab.results_entered",
        actor=actor,
        resource=order_item.order,
        patient=patient,
        facility=order_item.order.facility,
        after={
            "test": order_item.test.short_code,
            "values": {
                result.parameter.name: f"{result.display_value} {result.unit}".strip()
                for result in created
            },
            "flags": {
                result.parameter.name: result.flag
                for result in created if result.is_abnormal
            },
        },
        request=request,
    )

    # Critical values are communicated on entry, not on verification: waiting for a
    # second pair of eyes before telling anyone is how a critical result gets missed.
    for result in created:
        if result.is_critical:
            _raise_critical_alert(result, actor=actor, request=request)

    return created


def _raise_critical_alert(result, *, actor, request=None):
    order = result.order_item.order
    Notification.objects.create(
        recipient=order.ordered_by,
        kind=Notification.CRITICAL_RESULT,
        urgency=Notification.URGENT,
        subject=f"CRITICAL: {result.parameter.name} {result.display_value} "
                f"{result.unit}".strip(),
        body=(
            f"{order.patient.full_name} ({order.patient.hospital_number}) — "
            f"{result.order_item.test.name}. "
            f"{result.parameter.name} is {result.flag_label.lower()} at "
            f"{result.display_value} {result.unit} "
            f"(reference {result.reference_text or 'not configured'}). "
            f"Acknowledge and record the action taken."
        ),
        patient=order.patient,
        resource_type="laboratory.LabResult",
        resource_id=str(result.pk),
    )
    _email_the_clinician(result)
    AuditEvent.record(
        action="lab.critical_result_flagged",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={
            "parameter": result.parameter.name,
            "value": result.display_value,
            "flag": result.flag,
            "notified": order.ordered_by.email,
        },
        request=request,
    )


def _email_the_clinician(result):
    """Nudge the ordering clinician outside the application. AC-181.

    Queued, never sent from here. `outbox.queue` is one INSERT and cannot
    reach the network, so a mail provider having a bad afternoon cannot slow
    down or roll back the transaction that has just recorded a potassium of
    7.2 — guarantee 10. Whether the message ever leaves the building is
    settled later by `manage.py send_outbox`, where the only thing at risk is
    the message.

    **The body carries no clinical detail.** An in-app notification is read by
    somebody who has authenticated; an email is read by whoever holds the
    phone. So this says a result is waiting and where to look, and the number
    itself stays inside the hospital.
    """
    order = result.order_item.order
    clinician = order.ordered_by
    if not clinician.email:
        return None
    return outbox.queue(
        channel=OutboundMessage.EMAIL,
        to_address=clinician.email,
        subject="A critical laboratory result needs you",
        body=(
            f"A result flagged critical is waiting for you at "
            f"{order.facility.name}. Sign in to see it and record what you "
            f"did about it.\n\n"
            f"This message deliberately contains no clinical detail."
        ),
        source_type="laboratory.LabResult",
        source_id=result.pk,
        facility=order.facility,
        patient_reference=order.patient.hospital_number,
    )


@transaction.atomic
def verify_results(*, order_item, actor, comment="", request=None):
    """Release a result to the ordering clinician.

    Entry and verification are separate permissions on purpose: whoever typed the number
    is not automatically the person who signs it off.
    """
    if order_item.status != LabOrderItem.RESULTED:
        raise ValidationError(
            f"Only a resulted test can be verified (currently: "
            f"{order_item.get_status_display().lower()})."
        )
    if not order_item.results.filter(is_current=True).exists():
        raise ValidationError("There are no results to verify.")

    order_item.advance_to(LabOrderItem.VERIFIED)
    order_item.verified_by = actor
    order_item.verified_at = timezone.now()
    if comment:
        order_item.laboratory_comment = comment
    order_item.save(
        update_fields=["status", "verified_by", "verified_at", "laboratory_comment"]
    )

    order = order_item.order
    abnormal = [
        result for result in order_item.results.filter(is_current=True)
        if result.is_abnormal
    ]
    Notification.objects.create(
        recipient=order.ordered_by,
        kind=Notification.RESULT_READY,
        urgency=Notification.URGENT if abnormal else Notification.NORMAL,
        subject=f"{order_item.test.name} verified for {order.patient.full_name}",
        body=(
            f"{len(abnormal)} abnormal value(s)." if abnormal else "All values within range."
        ),
        patient=order.patient,
        resource_type="laboratory.LabOrderItem",
        resource_id=str(order_item.pk),
    )
    AuditEvent.record(
        action="lab.results_verified",
        actor=actor,
        resource=order,
        patient=order.patient,
        facility=order.facility,
        after={
            "test": order_item.test.short_code,
            "abnormal": [result.parameter.name for result in abnormal],
        },
        reason=comment,
        request=request,
    )
    return order_item


@transaction.atomic
def amend_result(*, result, actor, reason, value_numeric=None, value_text=None,
                 comment="", request=None):
    """Supersede a result. The old value stays on the record, marked as amended."""
    if not (reason or "").strip():
        raise ValidationError("A reason is required to amend a result.")
    if not result.is_current:
        raise ValidationError("That result has already been superseded.")

    current = LabResult.objects.select_for_update().get(pk=result.pk)
    order_item = current.order_item
    patient = order_item.order.patient

    numeric = _as_decimal(value_numeric) if value_numeric is not None else current.value_numeric
    text = value_text if value_text is not None else current.value_text
    flag, reference = _classify(current.parameter, numeric, patient)

    LabResult.objects.filter(pk=current.pk).update(is_current=False)
    replacement = LabResult.objects.create(
        order_item=order_item,
        parameter=current.parameter,
        value_numeric=numeric,
        value_text=text,
        unit=current.parameter.unit,
        flag=flag,
        range_low=reference.low if reference else None,
        range_high=reference.high if reference else None,
        range_note=reference.note if reference else "",
        version=current.version + 1,
        is_current=True,
        amends=current,
        amendment_reason=reason.strip(),
        entered_by=actor,
        comment=comment or current.comment,
    )

    AuditEvent.record(
        action="lab.result_amended",
        actor=actor,
        resource=order_item.order,
        patient=patient,
        facility=order_item.order.facility,
        before={
            "parameter": current.parameter.name,
            "value": current.display_value,
            "flag": current.flag,
        },
        after={"value": replacement.display_value, "flag": replacement.flag,
               "version": replacement.version},
        reason=reason.strip(),
        request=request,
    )
    if replacement.is_critical and not current.is_critical:
        _raise_critical_alert(replacement, actor=actor, request=request)
    return replacement
