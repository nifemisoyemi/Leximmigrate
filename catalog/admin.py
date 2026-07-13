from django.contrib import admin

from .models import (
    ApplicationType, Tier, Package, WorkflowStepTemplate,
    DocumentCategory, Questionnaire, Question, QuestionOption,
)


@admin.register(ApplicationType)
class ApplicationTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "order")
    list_editable = ("is_active", "order")


@admin.register(Tier)
class TierAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "attorney_minutes", "includes_document_review",
                    "includes_interview_coaching", "includes_representation")


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("application_type", "tier", "price_display", "is_active", "stripe_price_id")
    list_filter = ("application_type", "tier", "is_active")


@admin.register(WorkflowStepTemplate)
class WorkflowStepTemplateAdmin(admin.ModelAdmin):
    list_display = ("application_type", "order", "title",
                    "is_document_gate", "firm_performed_for_full_service")
    list_filter = ("application_type",)
    ordering = ("application_type", "order")


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ("application_type", "name", "is_required", "allows_multiple", "order")
    list_filter = ("application_type", "is_required")


# --- Questionnaire authoring: edit options inside questions, questions inside the questionnaire ---
class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    fk_name = "question"
    extra = 2


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("questionnaire", "order", "text", "kind")
    list_filter = ("questionnaire", "kind")
    inlines = [QuestionOptionInline]


@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ("application_type", "version", "is_active", "created_at")
    list_filter = ("application_type", "is_active")