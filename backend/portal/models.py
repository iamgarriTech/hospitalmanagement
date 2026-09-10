"""The patient portal's own accounts and sessions.

**Why this is not a flag on `accounts.User`.** AC-184 requires portal
authentication to be separate from staff authentication, with no shared
session and no staff permission reachable from a portal account. A boolean on
the staff user model would satisfy the letter of that and none of its point:
one mistaken role assignment, one view that forgets to check the flag, and a
patient is inside the hospital's records.

So a portal account is a different model, in a different table, authenticated
by a different cookie, through an authentication class that never touches
`User` or `RoleAssignment` at all. There is no code path from a portal request
to `has_permission`, which makes "no staff permission is reachable" a property
of the shape rather than a rule somebody has to remember.

This is the only externally reachable surface in the system. It is the one
place where a mistake is a public data breach rather than an internal one, and
the design is correspondingly boring: opaque tokens, hashed at rest, short
lifetimes, and one patient per account with no parameter anywhere that can
name a different one.
"""

import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

# How long a portal session lasts. Deliberately far shorter than a staff
# shift: a patient checking a result on a shared phone should not leave a live
# session behind them.
SESSION_HOURS = 2

# Lockout, separate from the staff counter so an attacker cannot lock a
# clinician out by guessing at a patient's account.
FAILED_LIMIT = 5
FAILED_WINDOW_MINUTES = 15
LOCKOUT_MINUTES = 30


class PortalAccount(models.Model):
    """One patient's own login. Never a member of staff."""

    patient = models.OneToOneField(
        "patients.Patient", on_delete=models.PROTECT, related_name="portal_account"
    )
    # Not an email: many patients here have a phone and no email address, and
    # a portal that requires one excludes them. Unique across the deployment.
    login_identifier = models.CharField(
        max_length=120, unique=True,
        help_text="What the patient types: their phone number or email.",
    )
    password_hash = models.CharField(max_length=255)

    is_active = models.BooleanField(default=True)
    deactivated_reason = models.CharField(max_length=255, blank=True)

    # A patient who has never signed in has an account somebody set up for
    # them; until they do, it is worth being able to tell the two apart.
    must_change_password = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True,
        related_name="portal_accounts_created",
    )

    class Meta:
        ordering = ["login_identifier"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(login_identifier=""),
                name="portal_account_has_an_identifier",
            ),
        ]
        permissions = [
            ("manage_portal_accounts", "Can create and suspend patient portal logins"),
        ]

    def __str__(self):
        return f"portal: {self.login_identifier}"

    def set_password(self, raw):
        self.password_hash = make_password(raw)

    def check_password(self, raw):
        return check_password(raw, self.password_hash)


class PortalSession(models.Model):
    """A live portal session, keyed by a token the browser never exposes.

    The token is stored hashed. A leaked database backup therefore does not
    hand somebody a working session, which a plaintext token would.

    Deliberately not Django's session framework: that uses one cookie name for
    the whole deployment, and sharing it would mean a staff session and a
    portal session are the same kind of thing to the browser and to any code
    that reads it. They are not, and AC-184 says so.
    """

    account = models.ForeignKey(
        PortalAccount, on_delete=models.CASCADE, related_name="sessions"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"portal session for {self.account.login_identifier}"

    @property
    def is_live(self):
        return self.ended_at is None and self.expires_at > timezone.now()

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def start(cls, account, *, ip_address=None, user_agent=""):
        """Returns (session, raw_token). The raw token is never stored."""
        token = secrets.token_urlsafe(48)
        session = cls.objects.create(
            account=account,
            token_hash=cls.hash_token(token),
            expires_at=timezone.now() + timedelta(hours=SESSION_HOURS),
            ip_address=ip_address,
            user_agent=user_agent[:255],
        )
        return session, token

    @classmethod
    def resolve(cls, token):
        """The live session for this token, or None. Never raises."""
        if not token:
            return None
        session = cls.objects.select_related(
            "account__patient"
        ).filter(token_hash=cls.hash_token(token), ended_at__isnull=True).first()
        if session is None or not session.is_live:
            return None
        if not session.account.is_active:
            return None
        return session

    def end(self):
        self.ended_at = timezone.now()
        self.save(update_fields=["ended_at"])

    def touch(self):
        # Sliding expiry, so a patient reading a long result list is not
        # signed out mid-page — but capped by the same two hours from now, not
        # extended indefinitely.
        self.last_seen_at = timezone.now()
        self.expires_at = timezone.now() + timedelta(hours=SESSION_HOURS)
        self.save(update_fields=["last_seen_at", "expires_at"])


class PortalLoginAttempt(models.Model):
    """Failed portal sign-ins, counted separately from staff ones.

    Separate so somebody guessing at a patient's password cannot lock out a
    clinician who happens to share an identifier, and so the portal's own
    lockout can be shorter or longer than the hospital's without arguing about
    it.
    """

    login_identifier = models.CharField(max_length=120, db_index=True)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-attempted_at"]

    def __str__(self):
        return f"failed portal login: {self.login_identifier}"

    @classmethod
    def is_locked(cls, login_identifier):
        window = timezone.now() - timedelta(minutes=FAILED_WINDOW_MINUTES)
        recent = cls.objects.filter(
            login_identifier=login_identifier, attempted_at__gte=window
        ).count()
        if recent < FAILED_LIMIT:
            return False
        latest = cls.objects.filter(
            login_identifier=login_identifier
        ).values_list("attempted_at", flat=True).first()
        return latest is not None and latest > timezone.now() - timedelta(
            minutes=LOCKOUT_MINUTES
        )

    @classmethod
    def record(cls, login_identifier, ip_address=None):
        return cls.objects.create(
            login_identifier=login_identifier, ip_address=ip_address
        )
