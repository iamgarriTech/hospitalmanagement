"""AC-57: Django admin is absent, not merely restricted.

It writes straight through the ORM, so it bypasses the DRF permission classes and
produces none of the audit rows the system guarantees.
"""
from django.conf import settings
from django.urls import URLResolver, get_resolver


def test_django_admin_is_not_installed():
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_no_admin_urls_are_mounted():
    def module_names(resolver):
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                yield getattr(pattern, "app_name", None) or ""
                yield from module_names(pattern)

    assert "admin" not in set(module_names(get_resolver()))


def test_no_app_registers_an_admin_module():
    import importlib.util

    for app in ("core", "accounts", "facilities", "audit"):
        assert importlib.util.find_spec(f"{app}.admin") is None, (
            f"{app}/admin.py exists — admin registration must not creep back in"
        )
