from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.views import CsrfView, LoginView, LogoutView, MeView
from facilities.views import FacilityViewSet
from patients.views import PatientViewSet
from visits.views import VisitViewSet

router = DefaultRouter()
router.register("facilities", FacilityViewSet, basename="facility")
router.register("patients", PatientViewSet, basename="patient")
router.register("visits", VisitViewSet, basename="visit")

urlpatterns = [
    path("api/auth/csrf/", CsrfView.as_view(), name="csrf"),
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/auth/me/", MeView.as_view(), name="me"),
    path("api/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
