"""Settings that are guarantees rather than preferences.

Each of these has a failure mode that is invisible in development and total in
production, which is exactly the kind that ships.
"""
from django.conf import settings


def test_a_production_install_does_not_redirect_itself_in_a_loop():
    """The proxy has to tell Django what the browser used.

    `SECURE_SSL_REDIRECT` without `SECURE_PROXY_SSL_HEADER` is a 301 loop for
    every request in a deployment where TLS terminates in front of Django —
    which is every deployment this system supports: the browser talks to
    Next.js, Next.js proxies server-side to Django over the internal network.
    Django sees plain HTTP, decides the request needs upgrading, and redirects a
    request that was already HTTPS. Forever.

    Found by pointing the inpatient benchmark at gunicorn with DEBUG off and
    getting a 301 on `/api/meta/`.
    """
    if not settings.SECURE_SSL_REDIRECT:
        return
    assert getattr(settings, "SECURE_PROXY_SSL_HEADER", None) == (
        "HTTP_X_FORWARDED_PROTO", "https"
    ), (
        "SECURE_SSL_REDIRECT is on with no proxy header: Django will see http "
        "for requests the browser made over https, and redirect forever."
    )


def test_the_proxy_tls_header_is_only_set_when_the_deployment_asks_for_it():
    """And is not trusted where it should not be.

    A client can set `X-Forwarded-Proto: https` itself. Trusting it on an
    install Django serves directly would let anyone walk straight past the TLS
    redirect, so the header is only honoured when the deployment says a proxy
    sets it.

    Asserted as the invariant between the two settings rather than against
    DEBUG: pytest-django rewrites DEBUG to False after settings load, so a test
    comparing to it is comparing to a value it cannot see.
    """
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) is not None:
        assert settings.TRUST_PROXY_TLS_HEADER is True, (
            "the proxy header is set without the deployment opting in"
        )


def test_no_authentication_credential_is_readable_by_javascript():
    """Guarantee 9. Session cookie only, and the session cookie is HttpOnly.

    The CSRF cookie is deliberately readable — the client has to echo it back
    in a header — and it is not a credential: on its own it authenticates
    nothing.
    """
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.CSRF_COOKIE_HTTPONLY is False
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == [
        "rest_framework.authentication.SessionAuthentication"
    ], "session authentication only — no JWT, no token in browser storage"


def test_django_needs_no_cors_because_the_browser_never_calls_it():
    """The BFF proxy is the whole point: no CORS surface on the API at all."""
    assert not any(
        "cors" in app.lower() for app in settings.INSTALLED_APPS
    ), "the browser talks to Next.js, which proxies server-side"
    assert settings.CSRF_TRUSTED_ORIGINS, (
        "the proxy forwards the browser's Origin verbatim, so the frontend "
        "origins have to be trusted here"
    )


def test_session_cookies_are_secure_unless_a_deployment_explicitly_gives_that_up():
    """The override exists for a loopback benchmark, not for a hospital.

    Named `COOKIES_MAY_TRAVEL_IN_CLEAR` rather than something neutral so that
    turning it on in a deployment reads like what it is.
    """
    if settings.DEPLOYMENT_DEBUG or settings.COOKIES_MAY_TRAVEL_IN_CLEAR:
        return
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True
