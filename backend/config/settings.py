"""Single settings module, driven by environment variables.

Deliberately not split into base/dev/prod — one file with env switches is easier to
reason about, and every difference between environments is visible in one place.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    FAILED_LOGIN_LIMIT=(int, 10),
    FAILED_LOGIN_WINDOW_MINUTES=(int, 15),
    FAILED_LOGIN_LOCKOUT_MINUTES=(int, 30),
)
environ.Env.read_env(REPO_ROOT / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-not-for-deployment")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# pytest-django forces settings.DEBUG to False after this module is imported, so
# anything that needs to know what *this deployment* chose — the security
# settings derived from it, and the tests asserting they were derived correctly —
# has to read it from here rather than from settings.DEBUG.
DEPLOYMENT_DEBUG = DEBUG

# No django.contrib.admin: it writes straight through the ORM, bypassing the DRF
# permission classes and producing none of the audit rows the system guarantees.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "core",
    "accounts",
    "facilities",
    "patients",
    "visits",
    "clinical",
    "laboratory",
    # Its own app, parallel to `laboratory`: a different department, different
    # staff, no specimen, and a report that is prose rather than numbers against
    # reference ranges.
    "imaging",
    "pharmacy",
    "billing",
    "insurance",
    # One app for inpatient care: the admission, its bed, the drug chart and the
    # nursing record are one workflow, and splitting them across four apps buys
    # a circular import and four migration graphs to keep in step.
    "inpatient",
    # One app for the supply chain: items, stores, stock, movements, and the
    # procurement that lands goods in them. A purchase order that cannot name
    # the store the goods arrive at is a form that does nothing, so they belong
    # together.
    "inventory",
    "notifications",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Sends the X-Frame-Options header. `X_FRAME_OPTIONS = "DENY"` below does
    # nothing without it — the setting was configured and the header was never
    # sent, which is the worst of both: it looks handled and is not.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestContextMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ]
        },
    }
]

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default="postgres://localhost:5432/hms_dev"
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.EmailBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# The frontend is deployed on a different domain, so the browser never calls Django
# directly: Next.js proxies server-side and re-issues Set-Cookie on its own host. That
# keeps the session cookie first-party (Safari and Chrome block third-party cookies, so
# a cross-site session would fail on iPads) and means Django needs no CORS.
# Django still validates CSRF, so the frontend origin must be trusted here.
# Must list the *frontend* origins, because that is the Origin the browser
# sends and the proxy forwards verbatim. Deliberately not laundered by the
# proxy: rewriting Origin to Django's own host would make every request look
# same-origin and defeat CSRF protection entirely.
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost:3100", "http://127.0.0.1:3100",
        "http://localhost:3000", "http://127.0.0.1:3000",
    ],
)

# Guarantee 9: no authentication credential readable by JavaScript. Sessions, not tokens.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 12  # a shift
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to echo it back in the header
CSRF_COOKIE_SAMESITE = "Lax"

# Secure unless a deployment says otherwise, and the only legitimate otherwise is
# a connection that never leaves the machine — the benchmark talking to gunicorn
# on the loopback. Overriding this on anything a browser reaches sends session
# cookies in clear text, so it is named after what it costs rather than after
# what it enables.
COOKIES_MAY_TRAVEL_IN_CLEAR = env.bool("COOKIES_MAY_TRAVEL_IN_CLEAR", default=False)
SESSION_COOKIE_SECURE = not (DEBUG or COOKIES_MAY_TRAVEL_IN_CLEAR)
CSRF_COOKIE_SECURE = not (DEBUG or COOKIES_MAY_TRAVEL_IN_CLEAR)

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# TLS is terminated in front of Django in every shape this system deploys in:
# the browser talks to Next.js, Next.js proxies server-side to Django over the
# internal network, and a reverse proxy sits in front of Next.js. Django
# therefore receives plain HTTP and, without being told what the browser
# actually used, SECURE_SSL_REDIRECT redirects a request that was already HTTPS
# — forever. That is not a subtle degradation; it is the whole application
# returning 301 to itself.
#
# The header is only trusted when the deployment says a proxy sets it. If Django
# were ever reachable directly, a client could send `X-Forwarded-Proto: https`
# itself and walk straight past the redirect, so this must not default to on
# for a directly-exposed install.
TRUST_PROXY_TLS_HEADER = env.bool("TRUST_PROXY_TLS_HEADER", default=not DEBUG)
if TRUST_PROXY_TLS_HEADER:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Switchable because the LAN-first install (server in the hospital, browsers on
# the local network) may legitimately terminate TLS at the proxy and speak plain
# HTTP behind it, and because the benchmark talks to gunicorn directly.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
if not DEBUG:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Off by default and deliberately opt-in: preloading is close to
    # irreversible — a hospital that later needs a plain-HTTP subdomain cannot
    # simply undo it — so the deployment decides rather than the code.
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

REST_FRAMEWORK = {
    # Session auth only. No JWT, no token in browser storage.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Hospital Management System API",
    "DESCRIPTION": "Internal API. Not a stable public contract.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    # Without these, two models both having a `status` field generate types called
    # StatusA97Enum in the TypeScript client. The generated client is read by people.
    "ENUM_NAME_OVERRIDES": {
        "PatientStatusEnum": "patients.models.Patient.STATUS_CHOICES",
        "VisitStatusEnum": "visits.models.Visit.STATUS_CHOICES",
        "VisitTypeEnum": "visits.models.Visit.TYPE_CHOICES",
        "SexEnum": "patients.models.Patient.SEX_CHOICES",
        "BloodGroupEnum": "patients.models.Patient.BLOOD_GROUPS",
        "GenotypeEnum": "patients.models.Patient.GENOTYPES",
        "AllergySeverityEnum": "patients.models.PatientAllergy.SEVERITIES",
        "AuditOutcomeEnum": "audit.models.AuditEvent.OUTCOME_CHOICES",
        # Three unrelated things are called "route": how a drug is given, and
        # how a fluid went in or came out. Named explicitly so the generated
        # client does not end up with "Route98fEnum".
        "MedicationRouteEnum": "pharmacy.models.Medication.ROUTE_CHOICES",
        "FluidRouteEnum": "inpatient.models.FluidBalanceEntry.ROUTES",
        "AdmissionStatusEnum": "inpatient.models.Admission.STATUS_CHOICES",
        "BedServiceStateEnum": "inpatient.models.Bed.SERVICE_STATES",
        "DoseStateEnum": "inpatient.models.MedicationAdministration.STATE_CHOICES",
        "ShiftEnum": "inpatient.models.nursing.SHIFT_CHOICES",
    },
}

# Demo mode: surfaces sample logins on the sign-in screen so an evaluator can
# get in. Defaults to DEBUG and must be explicitly enabled otherwise — printing
# working credentials on a live hospital's login page is not a small mistake.
DEMO_MODE = env.bool("DEMO_MODE", default=DEBUG)
DEMO_PASSWORD = env("DEMO_PASSWORD", default="demo-password-not-for-real-use")

# Brute-force protection (AC-6)
FAILED_LOGIN_LIMIT = env("FAILED_LOGIN_LIMIT")
FAILED_LOGIN_WINDOW = env("FAILED_LOGIN_WINDOW_MINUTES")
FAILED_LOGIN_LOCKOUT = env("FAILED_LOGIN_LOCKOUT_MINUTES")

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"  # stored in UTC; rendered in each facility's configured zone
USE_I18N = True
USE_TZ = True

# Where the emergency per-ward snapshots are written. Holds patient names,
# allergies and diagnoses outside the database, so a deployment should point it
# at an encrypted volume on the server itself — never a network share.
WARD_SNAPSHOT_ROOT = env("WARD_SNAPSHOT_ROOT", default=str(BASE_DIR / "snapshots"))

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"
