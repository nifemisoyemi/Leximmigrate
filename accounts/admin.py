from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Extends Django's built-in user admin to show our custom fields."""
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    # Append our fields to the default edit form.
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("LexImmigrate", {"fields": ("role", "phone")}),
    )