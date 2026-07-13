from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model. Defined before the first migration and pinned via
    AUTH_USER_MODEL = "accounts.User" in settings.

    Client vs Staff:
      - Staff (attorneys / paralegals) have is_staff=True -> reach the Django admin.
      - Clients have is_staff=False -> reach the portal.
    `role` is a forward-compatible placeholder for Phase 5 role-based access
    control; it is not wired into permissions yet.
    """

    class Role(models.TextChoices):
        CLIENT = "client", "Client"
        ATTORNEY = "attorney", "Attorney"
        PARALEGAL = "paralegal", "Paralegal"
        ADMIN = "admin", "Administrator"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CLIENT)
    phone = models.CharField(max_length=32, blank=True)  # used for SMS in Phase 3

    def __str__(self):
        return self.get_full_name() or self.username