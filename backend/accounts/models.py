from datetime import timedelta

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, full_name, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), full_name=full_name, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra):
        extra.setdefault("is_superuser", True)
        if not extra["is_superuser"]:
            raise ValueError("Superuser must have is_superuser=True")
        return self.create_user(email, full_name, password, **extra)


class User(AbstractBaseUser):
    """Staff and patient-portal accounts.

    Deliberately without PermissionsMixin: Django's Group/user_permissions plumbing
    would sit alongside the Role system below as a second, unscoped way to grant
    permissions. One mechanism is safer than two.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    staff_id = models.CharField(max_length=40, blank=True, null=True, unique=True)
    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(
        default=False, help_text="Bypasses permission checks. Emergency use only."
    )
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def has_permission(self, perm, facility=None):
        """Resolve ``app_label.codename`` against this user's role assignments.

        ``facility`` restricts the check to roles granted at that facility or granted
        organization-wide. Passing None accepts a grant at any facility, so views that
        act on facility-scoped data must pass it.
        """
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        app_label, _, codename = perm.partition(".")
        assignments = RoleAssignment.objects.filter(
            user=self,
            role__permissions__content_type__app_label=app_label,
            role__permissions__codename=codename,
        )
        if facility is not None:
            assignments = assignments.filter(
                Q(facility=facility) | Q(facility__isnull=True)
            )
        return assignments.exists()

    @property
    def discount_limit(self):
        """The most generous limit any of this user's roles allows."""
        from decimal import Decimal

        limits = [
            assignment.role.discount_limit
            for assignment in self.role_assignments.select_related("role")
        ]
        return max(limits) if limits else Decimal("0.00")

    def facilities_for(self, perm):
        """Facilities where this user holds ``perm``. None means organization-wide."""
        app_label, _, codename = perm.partition(".")
        return RoleAssignment.objects.filter(
            user=self,
            role__permissions__content_type__app_label=app_label,
            role__permissions__codename=codename,
        ).values_list("facility_id", flat=True)


class Role(models.Model):
    """A named permission set created by hospital administrators at runtime.

    Nothing in the codebase branches on a role's name.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    permissions = models.ManyToManyField(
        "auth.Permission", related_name="roles", blank=True
    )
    discount_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Largest discount this role may apply without approval.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoleAssignment(models.Model):
    """Grants a role to a user, optionally scoped to one facility."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    facility = models.ForeignKey(
        "facilities.Facility",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
        help_text="Null grants the role across the organization.",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roles_granted",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "facility"], name="role_assignment_unique"
            ),
            models.UniqueConstraint(
                fields=["user", "role"],
                condition=Q(facility__isnull=True),
                name="role_assignment_unique_org_wide",
            ),
        ]

    def __str__(self):
        where = self.facility.code if self.facility else "organization-wide"
        return f"{self.user.email}: {self.role.name} @ {where}"


class FailedLoginAttempt(models.Model):
    """Drives lockout (AC-6). Rows are evidence, so they are not deleted on success."""

    email = models.EmailField(db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.email} from {self.ip_address or 'unknown'} at {self.occurred_at:%Y-%m-%d %H:%M}"

    @classmethod
    def is_locked(cls, email):
        window_start = timezone.now() - timedelta(minutes=settings.FAILED_LOGIN_WINDOW)
        recent = cls.objects.filter(
            email__iexact=email, occurred_at__gte=window_start
        ).count()
        return recent >= settings.FAILED_LOGIN_LIMIT
