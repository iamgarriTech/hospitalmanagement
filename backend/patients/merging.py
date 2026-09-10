"""Merging duplicate records without losing anything.

Nothing is deleted: the merged-away record is kept, marked, and pointed at the survivor,
so an old chart number, referral letter or receipt still resolves.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from audit.models import AuditEvent

from .models import Patient

# Audit rows are append-only and must keep saying which record was actually used at the
# time, so they are never reassigned to the surviving patient.
NEVER_REASSIGNED = {("audit", "auditevent")}


def _reassignable_relations():
    """Every FK pointing at Patient, discovered rather than listed.

    A hand-maintained list is how a merge silently starts orphaning data three modules
    later. This picks up encounters, invoices and results as they are added.
    """
    for relation in Patient._meta.related_objects:
        if not (relation.one_to_many or relation.one_to_one):
            continue
        model = relation.related_model
        label = (model._meta.app_label, model._meta.model_name)
        if label in NEVER_REASSIGNED:
            continue
        if model is Patient:  # the merged_into self-reference
            continue
        yield relation


@transaction.atomic
def merge_patients(*, source, target, actor, reason, request=None):
    if source.pk == target.pk:
        raise ValidationError("A patient cannot be merged into themselves.")
    if source.status == Patient.MERGED:
        raise ValidationError(
            f"{source.hospital_number} was already merged into "
            f"{source.merged_into.hospital_number}."
        )
    if target.status == Patient.MERGED:
        raise ValidationError(
            f"{target.hospital_number} is itself a merged record; merge into the survivor."
        )
    if not reason:
        raise ValidationError("A reason is required to merge patient records.")

    source = Patient.objects.select_for_update().get(pk=source.pk)
    target = Patient.objects.select_for_update().get(pk=target.pk)

    moved = {}
    for relation in _reassignable_relations():
        # Through the model's own manager rather than the reverse accessor.
        # A reverse *one-to-one* accessor raises when there is nothing on the
        # other side, so `getattr(source, ...)` blows up on a patient who
        # happens to have no birth record — which is nearly all of them. A
        # filtered update works the same way for both kinds of relation.
        model = relation.related_model
        field = relation.field.name
        try:
            with transaction.atomic():
                count = model._base_manager.filter(**{field: source}).update(
                    **{field: target}
                )
        except IntegrityError:
            # A one-to-one that the survivor already has: two records that each
            # carry the same singular thing. Merging them would need somebody to
            # decide which is right, and that is not a decision this function
            # can make.
            raise ValidationError(
                f"Both records carry a {model._meta.verbose_name}, and a patient "
                f"can only have one. Resolve that before merging."
            )
        if count:
            moved[model._meta.label] = count

    source.status = Patient.MERGED
    source.merged_into = target
    source.save(update_fields=["status", "merged_into", "updated_at"])

    AuditEvent.record(
        action="patient.merged_away",
        actor=actor,
        resource=source,
        patient=source,
        before={"status": Patient.ACTIVE, "merged_into": None},
        after={
            "status": Patient.MERGED,
            "merged_into": target.hospital_number,
            "records_moved": moved,
        },
        reason=reason,
        request=request,
    )
    AuditEvent.record(
        action="patient.merge_received",
        actor=actor,
        resource=target,
        patient=target,
        after={"merged_from": source.hospital_number, "records_moved": moved},
        reason=reason,
        request=request,
    )
    return target, moved
