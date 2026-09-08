from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.config_views import PermissionViewSet, RoleViewSet, StaffViewSet
from accounts.views import CsrfView, LoginView, LogoutView, MetaView, MeView
from audit.views import AuditEventViewSet
from billing.views import (
    CashierSessionViewSet,
    InvoiceViewSet,
    PaymentMethodViewSet,
    PaymentViewSet,
    ServiceCategoryViewSet,
    ServiceViewSet,
)
from clinical.views import EncounterViewSet, VitalSignsViewSet
from core.config_views import (
    ClinicViewSet,
    DepartmentViewSet,
    NumberSequenceViewSet,
    OrganizationViewSet,
)
from facilities.views import FacilityViewSet
from imaging.views import (
    ImagingModalityViewSet,
    ImagingOrderItemViewSet,
    ImagingOrderViewSet,
    ImagingProcedureViewSet,
    ImagingReportViewSet,
)
from inpatient.views import (
    AdmissionRequestViewSet,
    AdmissionViewSet,
    BedOccupancyViewSet,
    BedViewSet,
    EscalationThresholdViewSet,
    EscalationViewSet,
    FluidBalanceViewSet,
    MedicationAdministrationViewSet,
    NursingAssessmentViewSet,
    NursingNoteViewSet,
    RoomViewSet,
    ScheduledDoseViewSet,
    WardViewSet,
)
from laboratory.views import (
    LabOrderItemViewSet,
    LabOrderViewSet,
    LabResultViewSet,
    LabTestCategoryViewSet,
    LabTestViewSet,
)
from notifications.views import NotificationViewSet
from patients.views import PatientViewSet
from pharmacy.views import (
    MedicationCategoryViewSet,
    MedicationViewSet,
    PrescriptionItemViewSet,
    PrescriptionViewSet,
    StockBatchViewSet,
)
from visits.views import VisitViewSet

router = DefaultRouter()
router.register("facilities", FacilityViewSet, basename="facility")
router.register("patients", PatientViewSet, basename="patient")
router.register("visits", VisitViewSet, basename="visit")
router.register("encounters", EncounterViewSet, basename="encounter")
router.register("vitals", VitalSignsViewSet, basename="vitals")
router.register("lab-test-categories", LabTestCategoryViewSet, basename="labtestcategory")
router.register("lab-tests", LabTestViewSet, basename="labtest")
router.register("lab-orders", LabOrderViewSet, basename="laborder")
router.register("lab-order-items", LabOrderItemViewSet, basename="laborderitem")
router.register("lab-results", LabResultViewSet, basename="labresult")
router.register("imaging-modalities", ImagingModalityViewSet,
                basename="imagingmodality")
router.register("imaging-procedures", ImagingProcedureViewSet,
                basename="imagingprocedure")
router.register("imaging-orders", ImagingOrderViewSet, basename="imagingorder")
router.register("imaging-order-items", ImagingOrderItemViewSet,
                basename="imagingorderitem")
router.register("imaging-reports", ImagingReportViewSet, basename="imagingreport")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("medication-categories", MedicationCategoryViewSet,
                basename="medicationcategory")
router.register("medications", MedicationViewSet, basename="medication")
router.register("stock-batches", StockBatchViewSet, basename="stockbatch")
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register("prescription-items", PrescriptionItemViewSet, basename="prescriptionitem")
router.register("service-categories", ServiceCategoryViewSet, basename="servicecategory")
router.register("services", ServiceViewSet, basename="service")
router.register("payment-methods", PaymentMethodViewSet, basename="paymentmethod")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("cashier-sessions", CashierSessionViewSet, basename="cashiersession")
router.register("payments", PaymentViewSet, basename="payment")
router.register("roles", RoleViewSet, basename="role")
router.register("permissions", PermissionViewSet, basename="permission")
router.register("staff", StaffViewSet, basename="staff")
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("departments", DepartmentViewSet, basename="department")
router.register("clinics", ClinicViewSet, basename="clinic")
router.register("numbering", NumberSequenceViewSet, basename="numbersequence")
router.register("audit-events", AuditEventViewSet, basename="auditevent")
router.register("wards", WardViewSet, basename="ward")
router.register("rooms", RoomViewSet, basename="room")
router.register("beds", BedViewSet, basename="bed")
router.register("bed-occupancies", BedOccupancyViewSet, basename="bedoccupancy")
router.register("escalation-thresholds", EscalationThresholdViewSet,
                basename="escalationthreshold")
router.register("admission-requests", AdmissionRequestViewSet, basename="admissionrequest")
router.register("admissions", AdmissionViewSet, basename="admission")
router.register("nursing-assessments", NursingAssessmentViewSet,
                basename="nursingassessment")
router.register("nursing-notes", NursingNoteViewSet, basename="nursingnote")
router.register("fluid-balance", FluidBalanceViewSet, basename="fluidbalanceentry")
router.register("escalations", EscalationViewSet, basename="escalation")
router.register("scheduled-doses", ScheduledDoseViewSet, basename="scheduleddose")
router.register("administrations", MedicationAdministrationViewSet,
                basename="medicationadministration")

urlpatterns = [
    path("api/meta/", MetaView.as_view(), name="meta"),
    path("api/auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/me/", MeView.as_view(), name="me"),
    path("api/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
