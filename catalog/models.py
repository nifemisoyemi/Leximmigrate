"""
catalog: the generic, data-driven spine of the platform.

Everything that differs between application types (N-400 today; I-130, I-90 later)
lives here as DATA. Adding a new application type should be data entry, not code.
"""

from django.core.validators import MinValueValidator
from django.db import models


class ApplicationType(models.Model):
    """e.g. N-400 (Naturalization). Add I-130, I-90, etc. as rows later."""
    code = models.CharField(max_length=20, unique=True)      # "N-400"
    name = models.CharField(max_length=200)                  # "Naturalization"
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Tier(models.Model):
    """
    The three service levels, shared across all application types. The capability
    flags are how one workflow serves all three tiers: code checks the flag, never
    the tier's name.
    """

    class Level(models.IntegerChoices):
        DIY = 1, "DIY"
        ENHANCED = 2, "Enhanced"
        FULL_SERVICE = 3, "Full Service"

    level = models.IntegerField(choices=Level.choices, unique=True)
    name = models.CharField(max_length=100)
    tagline = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    # DIY: 60 min, no review, no representation
    # Enhanced: 120 min, review, interview coaching, no representation
    # Full Service: 120 min, review, representation + firm files on behalf
    attorney_minutes = models.PositiveIntegerField(default=0)
    includes_document_review = models.BooleanField(default=False)
    includes_interview_coaching = models.BooleanField(default=False)
    includes_representation = models.BooleanField(default=False)

    class Meta:
        ordering = ["level"]

    def __str__(self):
        return self.name


class Package(models.Model):
    """
    The purchasable thing: an ApplicationType at a Tier, with a price. Price lives
    here (not on Tier) because pricing is per application type, though the tier
    structure is shared. Money stored as integer cents.
    """
    application_type = models.ForeignKey(ApplicationType, on_delete=models.PROTECT, related_name="packages")
    tier = models.ForeignKey(Tier, on_delete=models.PROTECT, related_name="packages")

    price_cents = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default="USD")
    stripe_price_id = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["application_type", "tier"], name="unique_package")
        ]
        ordering = ["application_type", "tier"]

    @property
    def price_display(self):
        return f"${self.price_cents / 100:,.0f}"

    def __str__(self):
        return f"{self.application_type.code} — {self.tier.name}"


class WorkflowStepTemplate(models.Model):
    """
    The ordered steps of the guided workflow, per application type, as DATA.
    Same skeleton for all tiers. A Case gets one CaseStep per template.
    """
    application_type = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, related_name="step_templates")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Step 2 (Gather documents) is the gate: later steps stay locked until this
    # step's documents pass attorney review. Kept as data, not "step number 2".
    is_document_gate = models.BooleanField(default=False)
    firm_performed_for_full_service = models.BooleanField(default=False)

    class Meta:
        ordering = ["application_type", "order"]
        constraints = [
            models.UniqueConstraint(fields=["application_type", "order"], name="unique_step_order")
        ]

    def __str__(self):
        return f"{self.application_type.code} · {self.order}. {self.title}"


class DocumentCategory(models.Model):
    """A required category of documents for an application type (defined by the firm)."""
    application_type = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, related_name="document_categories")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    allows_multiple = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["application_type", "order"]
        verbose_name_plural = "document categories"

    def __str__(self):
        return f"{self.application_type.code} · {self.name}"


# --- Questionnaire (attorney-authored, version-controlled) -------------------
class Questionnaire(models.Model):
    application_type = models.ForeignKey(ApplicationType, on_delete=models.CASCADE, related_name="questionnaires")
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=False)   # exactly one active per type
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["application_type", "version"], name="unique_questionnaire_version")
        ]
        ordering = ["application_type", "-version"]

    def __str__(self):
        return f"{self.application_type.code} questionnaire v{self.version}"


class Question(models.Model):
    class Kind(models.TextChoices):
        SINGLE = "single", "Single choice"
        MULTI = "multi", "Multiple choice"
        BOOLEAN = "boolean", "Yes / No"
        TEXT = "text", "Short text"

    questionnaire = models.ForeignKey(Questionnaire, on_delete=models.CASCADE, related_name="questions")
    order = models.PositiveIntegerField()
    text = models.TextField()
    help_text = models.TextField(blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SINGLE)

    class Meta:
        ordering = ["questionnaire", "order"]

    def __str__(self):
        return f"Q{self.order}: {self.text[:60]}"


class QuestionOption(models.Model):
    """
    An answer option carrying the branching/eligibility logic:
      - is_disqualifying: choosing this flags the lead as likely NOT eligible.
      - skip_to: jump to a later question (simple branching). Null = next in order.
    Phase-1-simple; can grow into a rules table later without touching the rest.
    """
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    label = models.CharField(max_length=255)
    value = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    is_disqualifying = models.BooleanField(default=False)
    skip_to = models.ForeignKey("Question", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["question", "order"]

    def __str__(self):
        return self.label