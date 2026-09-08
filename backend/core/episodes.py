"""What a clinical record belongs to: an attendance, or an admission.

Phase 2 gave encounters, laboratory orders, prescriptions and invoices a
nullable `admission` alongside `visit`, because an inpatient stay outlives the
attendance that started it — a daily review on day nine has nothing to do with
that morning's outpatient queue, and a direct admission has no visit at all.

Three create paths made the same assumption ("there is a visit; read the patient
and facility off it") and all three raised a KeyError on an inpatient record.
The rule is one line long, but it has to be the same line in every one of them:
the patient and facility come from whichever episode is set.
"""
from django.core.exceptions import ValidationError


def episode_owner(*, visit=None, admission=None):
    """The patient and facility a record belongs to.

    Admission first: where both are present — an inpatient whose stay began at
    an outpatient attendance — the stay is the current context, and it is the
    stay's facility that matters after a transfer between branches.
    """
    if admission is not None:
        return admission.patient, admission.facility
    if visit is not None:
        return visit.patient, visit.facility
    raise ValidationError(
        "A clinical record belongs to an attendance or to an admission."
    )


def facility_from_request(request):
    """The facility a POST is aimed at, for the permission check.

    Resolved before the serializer runs, so it looks at raw request data rather
    than validated objects. Returns None when neither is given, and the
    permission class then fails closed.
    """
    from inpatient.models import Admission
    from visits.models import Visit

    admission_id = request.data.get("admission")
    if admission_id:
        admission = Admission.objects.filter(
            pk=admission_id
        ).select_related("facility").first()
        if admission is not None:
            return admission.facility
    visit_id = request.data.get("visit")
    if visit_id:
        visit = Visit.objects.filter(pk=visit_id).select_related("facility").first()
        if visit is not None:
            return visit.facility
    return None
