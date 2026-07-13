from django.contrib import admin

from .models import (
    Lead, Case, CaseStep, Document, Consultation,
    InternalNote, StatusUpdate, ProceduralEvent, Payment,
)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "status", "likely_eligible", "created_at")
    list_filter = ("status", "likely_eligible")
    search_fields = ("first_name", "last_name", "email")


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "application_type", "package", "status",
                    "current_step", "last_activity_at")
    list_filter = ("status", "application_type")
    search_fields = ("client__username", "client__email")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "package", "status", "amount_cents", "created_at")
    list_filter = ("status",)


# Basic registration for the rest — we'll build the real staff case-detail view
# (documents, notes, status updates inline on the case) in Milestone 3.
admin.site.register([CaseStep, Document, Consultation, InternalNote, StatusUpdate, ProceduralEvent])