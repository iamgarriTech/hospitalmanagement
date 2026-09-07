from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password


class EmailBackend:
    """Authenticates on email + password. Authentication only — authorization lives on
    ``User.has_permission`` so there is exactly one place that resolves permissions.
    """

    def authenticate(self, request, email=None, password=None, **kwargs):
        User = get_user_model()
        if email is None or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Hash anyway so a missing account and a wrong password take similar time.
            check_password(password, "pbkdf2_sha256$1000000$x$x")
            return None
        if user.check_password(password) and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
