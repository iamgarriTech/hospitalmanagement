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
from clinical.views import (
    EncounterViewSet,
    ReferralViewSet,
    VitalSignsViewSet,
)
from core.config_views import (
    ClinicViewSet,
    DepartmentViewSet,
    LimitationsView,
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
from insurance.views import (
    ChargeCoverageViewSet,
    ClaimBatchViewSet,
    ClaimLineViewSet,
    CoverageRuleViewSet,
    InsuranceProviderViewSet,
    PatientPolicyViewSet,
    PlanViewSet,
    PreauthorisationViewSet,
    ProviderPaymentViewSet,
)
from integration.views import VERSION as FACADE_VERSION
from integration.views import (
    ConditionFacade,
    EncounterFacade,
    FacadeRootView,
    MedicationRequestFacade,
    ObservationFacade,
    PatientFacade,
)
from inventory.views import (
    GoodsReceiptViewSet,
    InventoryItemViewSet,
    ItemCategoryViewSet,
    PurchaseOrderViewSet,
    PurchaseRequestViewSet,
    RaiseOrderView,
    StockAdjustmentViewSet,
    StockAlertViewSet,
    StockMovementViewSet,
    StockRecordViewSet,
    StockTransferViewSet,
    StoreViewSet,
    SupplierInvoiceViewSet,
    SupplierViewSet,
)
from laboratory.views import (
    LabOrderItemViewSet,
    LabOrderViewSet,
    LabResultViewSet,
    LabTestCategoryViewSet,
    LabTestViewSet,
)
from maternity.views import DeliveryViewSet, PregnancyViewSet
from notifications.views import NotificationViewSet, OutboxViewSet
from patients.views import PatientViewSet
from pharmacy.views import (
    MedicationCategoryViewSet,
    MedicationViewSet,
    PrescriptionItemViewSet,
    PrescriptionViewSet,
    StockBatchViewSet,
)
from portal.views import (
    PortalAccountAdminViewSet,
    PortalLoginView,
    PortalLogoutView,
    PortalMeView,
    PortalRecordViewSet,
)
from procedures.views import (
    OperationNoteViewSet,
    PerformedProcedureViewSet,
    ProcedureCategoryViewSet,
    ProcedureRequestViewSet,
    ProcedureViewSet,
    TheatreBookingViewSet,
    TheatreListView,
    TheatreViewSet,
)
from reporting.views import ReportViewSet
from visits.views import (
    EmergencyEpisodeViewSet,
    TriageScaleViewSet,
    VisitViewSet,
)

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
router.register("insurance-providers", InsuranceProviderViewSet,
                basename="insuranceprovider")
router.register("insurance-plans", PlanViewSet, basename="plan")
router.register("coverage-rules", CoverageRuleViewSet, basename="coveragerule")
router.register("patient-policies", PatientPolicyViewSet, basename="patientpolicy")
router.register("preauthorisations", PreauthorisationViewSet,
                basename="preauthorisation")
router.register("charge-coverage", ChargeCoverageViewSet, basename="chargecoverage")
router.register("claims", ClaimBatchViewSet, basename="claimbatch")
router.register("claim-lines", ClaimLineViewSet, basename="claimline")
router.register("provider-payments", ProviderPaymentViewSet,
                basename="providerpayment")

router.register("item-categories", ItemCategoryViewSet, basename="itemcategory")
router.register("inventory-items", InventoryItemViewSet, basename="inventoryitem")
router.register("stores", StoreViewSet, basename="store")
router.register("stock-records", StockRecordViewSet, basename="stockrecord")
router.register("stock-movements", StockMovementViewSet, basename="stockmovement")
router.register("stock-transfers", StockTransferViewSet, basename="stocktransfer")
router.register("stock-adjustments", StockAdjustmentViewSet,
                basename="stockadjustment")
router.register("stock-alerts", StockAlertViewSet, basename="stockalert")

router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("purchase-requests", PurchaseRequestViewSet,
                basename="purchaserequest")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchaseorder")
router.register("raise-purchase-order", RaiseOrderView, basename="raisepurchaseorder")
router.register("goods-receipts", GoodsReceiptViewSet, basename="goodsreceipt")
router.register("supplier-invoices", SupplierInvoiceViewSet,
                basename="supplierinvoice")

router.register("procedure-categories", ProcedureCategoryViewSet,
                basename="procedurecategory")
router.register("procedures", ProcedureViewSet, basename="procedure")
router.register("theatres", TheatreViewSet, basename="theatre")
router.register("procedure-requests", ProcedureRequestViewSet,
                basename="procedurerequest")
router.register("theatre-bookings", TheatreBookingViewSet, basename="theatrebooking")
router.register("theatre-list", TheatreListView, basename="theatrelist")
router.register("performed-procedures", PerformedProcedureViewSet,
                basename="performedprocedure")
router.register("operation-notes", OperationNoteViewSet, basename="operationnote")
router.register("referrals", ReferralViewSet, basename="referral")
router.register("triage-scales", TriageScaleViewSet, basename="triagescale")
router.register("emergency-episodes", EmergencyEpisodeViewSet,
                basename="emergencyepisode")

router.register("pregnancies", PregnancyViewSet, basename="pregnancy")
router.register("deliveries", DeliveryViewSet, basename="delivery")
router.register("reports", ReportViewSet, basename="report")
router.register("outbox", OutboxViewSet, basename="outbox")
router.register("portal-accounts", PortalAccountAdminViewSet,
                basename="portalaccount")

# The external API facade, versioned in the path. AC-179. A separate router
# so the version is a real prefix rather than a query parameter somebody can
# forget — and so v2 can exist beside v1 without touching it.
portal_router = DefaultRouter()
portal_router.register("record", PortalRecordViewSet, basename="portal-record")

facade = DefaultRouter()
facade.register("", FacadeRootView, basename="facade-root")
facade.register("Patient", PatientFacade, basename="facade-patient")
facade.register("Encounter", EncounterFacade, basename="facade-encounter")
facade.register("Condition", ConditionFacade, basename="facade-condition")
facade.register("Observation", ObservationFacade, basename="facade-observation")
facade.register("MedicationRequest", MedicationRequestFacade,
                basename="facade-medicationrequest")

urlpatterns = [
    path("api/meta/", MetaView.as_view(), name="meta"),
    path("api/limitations/", LimitationsView.as_view(), name="limitations"),
    path("api/auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/me/", MeView.as_view(), name="me"),
    # The portal is mounted under its own prefix with its own authentication.
    # Nothing here shares a session with the staff API above.
    path("api/portal/auth/login/", PortalLoginView.as_view(), name="portal-login"),
    path("api/portal/auth/logout/", PortalLogoutView.as_view(), name="portal-logout"),
    path("api/portal/auth/me/", PortalMeView.as_view(), name="portal-me"),
    path("api/portal/", include(portal_router.urls)),
    path("api/", include(router.urls)),
    path(f"api/fhir/{FACADE_VERSION}/", include(facade.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
