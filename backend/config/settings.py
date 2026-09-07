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
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=["http://localhost:3000"]
)

# Guarantee 9: no authentication credential readable by JavaScript. Sessions, not tokens.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 12  # a shift
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to echo it back in the header
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

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
    },
}

# Brute-force protection (AC-6)
FAILED_LOGIN_LIMIT = env("FAILED_LOGIN_LIMIT")
FAILED_LOGIN_WINDOW = env("FAILED_LOGIN_WINDOW_MINUTES")
FAILED_LOGIN_LOCKOUT = env("FAILED_LOGIN_LOCKOUT_MINUTES")

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"  # stored in UTC; rendered in each facility's configured zone
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"
