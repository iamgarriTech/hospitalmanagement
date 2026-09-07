from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.views import CsrfView, LoginView, LogoutView, MetaView, MeView
from facilities.views import FacilityViewSet
from patients.views import PatientViewSet
from billing.views import (
    CashierSessionViewSet,
    InvoiceViewSet,
    PaymentMethodViewSet,
    PaymentViewSet,
    ServiceCategoryViewSet,
    ServiceViewSet,
)
from clinical.views import EncounterViewSet, VitalSignsViewSet
from laboratory.views import (
    LabOrderItemViewSet,
    LabOrderViewSet,
    LabResultViewSet,
    LabTestCategoryViewSet,
    LabTestViewSet,
)
from notifications.views import NotificationViewSet
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
