from django.contrib import admin
from django.utils.html import format_html

from . import services
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
                    "documents_submitted_at", "current_step", "last_activity_at")
    list_filter = ("status", "application_type")
    search_fields = ("client__username", "client__email")
    actions = ["approve_document_review", "return_to_client"]
    filter_horizontal = ("applicable_categories",)

    @admin.action(description="Approve document review (opens the filing step)")
    def approve_document_review(self, request, queryset):
        for case in queryset:
            services.pass_review(case, reviewer=request.user)
        self.message_user(request, f"Review approved for {queryset.count()} case(s).")

    @admin.action(description="Return to client for changes (mark documents 'needs revision' first)")
    def return_to_client(self, request, queryset):
        for case in queryset:
            services.return_for_changes(case)
        self.message_user(request, f"Returned {queryset.count()} case(s) to the client.")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """The review queue. Filter status = 'Under review' for today's work."""
    list_display = ("id", "case", "category", "original_filename", "file_link",
                    "status", "uploaded_at", "reviewed_by")
    list_filter = ("status", "category")
    search_fields = ("case__client__email", "original_filename")
    readonly_fields = ("case", "category", "file", "original_filename",
                       "content_type", "size_bytes", "uploaded_at")
    fields = ("case", "category", "file", "original_filename", "status",
              "review_note", "reviewed_by", "reviewed_at")
    actions = ["approve_selected", "needs_revision_selected"]

    @admin.display(description="File")
    def file_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" target="_blank">open</a>', obj.file.url)
        return "—"

    @admin.action(description="Approve selected documents")
    def approve_selected(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=Document.Status.APPROVED,
                        reviewed_by=request.user, reviewed_at=timezone.now())

    @admin.action(description="Mark selected 'needs revision' (add notes on each doc first)")
    def needs_revision_selected(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=Document.Status.NEEDS_REVISION,
                        reviewed_by=request.user, reviewed_at=timezone.now())


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "package", "status", "amount_cents", "created_at")
    list_filter = ("status",)


admin.site.register([CaseStep, Consultation, InternalNote, StatusUpdate, ProceduralEvent])