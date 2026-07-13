"""
cases: everything about a client's journey through the platform.

Cross-app foreign keys use string references ("catalog.Package") so Django can
resolve them without import-order problems. User references use
settings.AUTH_USER_MODEL, never a direct import of the User class.
"""

from django.conf import settings
from django.db import models


# --- Leads (questionnaire result BEFORE an account exists) -------------------
class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        CONVERTED = "converted", "Converted"
        CLOSED = "closed", "Closed"

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)

    questionnaire = models.ForeignKey("catalog.Questionnaire", on_delete=models.SET_NULL, null=True, related_name="leads")
    answers = models.JSONField(default=dict)   # snapshot, keyed by question id

    likely_eligible = models.BooleanField(null=True)
    recommended_package = models.ForeignKey("catalog.Package", null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    converted_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"


# --- Case (one active case per client in Phase 1) ----------------------------
class Case(models.Model):
    class Status(models.TextChoices):
        GATHERING = "gathering", "Gathering documents"
        PENDING_REVIEW = "pending_review", "Pending attorney review"
        ACTIVE = "active", "Active (review passed)"
        DECISION = "decision", "Decision"
        CLOSED = "closed", "Closed"

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cases")
    package = models.ForeignKey("catalog.Package", on_delete=models.PROTECT, related_name="cases")
    application_type = models.ForeignKey("catalog.ApplicationType", on_delete=models.PROTECT, related_name="cases")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.GATHERING)
    current_step = models.ForeignKey("catalog.WorkflowStepTemplate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    # Full Service representation fields (used only when tier.includes_representation).
    notice_of_representation_filed = models.BooleanField(default=False)
    filed_with_uscis_at = models.DateTimeField(null=True, blank=True)
    receipt_number = models.CharField(max_length=40, blank=True)   # USCIS receipt (Phase 4)

    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_activity_at"]

    @property
    def tier(self):
        return self.package.tier

    def __str__(self):
        return f"Case #{self.pk} — {self.client} — {self.package}"


class CaseStep(models.Model):
    """Per-case instance of a WorkflowStepTemplate. Carries unlock + completion state."""
    class Status(models.TextChoices):
        LOCKED = "locked", "Locked"            # visible as preview, not actionable
        AVAILABLE = "available", "Available"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETE = "complete", "Complete"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="steps")
    template = models.ForeignKey("catalog.WorkflowStepTemplate", on_delete=models.PROTECT, related_name="case_steps")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.LOCKED)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["case", "template__order"]
        constraints = [
            models.UniqueConstraint(fields=["case", "template"], name="unique_case_step")
        ]

    def __str__(self):
        return f"{self.case} · {self.template.title} [{self.status}]"


class Document(models.Model):
    """Uploaded file in a document category, with the review state machine. A file
    is never made visible until the virus scan clears (scan runs in a background job)."""
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        NEEDS_REVISION = "needs_revision", "Needs revision"

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending scan"
        CLEAN = "clean", "Clean"
        INFECTED = "infected", "Infected"
        ERROR = "error", "Scan error"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="documents")
    category = models.ForeignKey("catalog.DocumentCategory", on_delete=models.PROTECT, related_name="documents")

    file = models.FileField(upload_to="case_documents/")   # DO Spaces via django-storages later
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADED)
    scan_status = models.CharField(max_length=10, choices=ScanStatus.choices, default=ScanStatus.PENDING)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_documents")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)   # shown to client on rejection / needs-revision

    @property
    def is_visible(self):
        return self.scan_status == self.ScanStatus.CLEAN

    def __str__(self):
        return f"{self.case} · {self.category.name} · {self.original_filename}"


class Consultation(models.Model):
    """A booked attorney touchpoint. Booking mechanics live in Cal.com; this is the
    synced record. On create/update we also push an item to the firm's Monday.com board."""
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="consultations")
    staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="consultations")
    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)

    external_ref = models.CharField(max_length=100, blank=True)    # Cal.com booking id
    monday_item_id = models.CharField(max_length=100, blank=True)  # Monday.com item id

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scheduled_at"]

    def __str__(self):
        return f"{self.case} · {self.scheduled_at:%Y-%m-%d %H:%M}"


class InternalNote(models.Model):
    """Staff-only note on a case. NOT visible to the client."""
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="internal_notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note on {self.case} by {self.author}"


class StatusUpdate(models.Model):
    """Full Service only: a status update posted by staff that the CLIENT reads."""
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="status_updates")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Status update on {self.case}"


class ProceduralEvent(models.Model):
    """Full Service only: staff record key procedural events (filed, notice recorded, etc.)."""
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="procedural_events")
    label = models.CharField(max_length=200)
    note = models.TextField(blank=True)
    occurred_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.case} · {self.label}"


# --- Payments ----------------------------------------------------------------
class Payment(models.Model):
    """A Stripe Checkout payment. Created when Checkout starts; confirmed by webhook.
    Account exists before payment; the Case is created once payment is confirmed."""
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    package = models.ForeignKey("catalog.Package", on_delete=models.PROTECT, related_name="payments")
    case = models.OneToOneField(Case, null=True, blank=True, on_delete=models.SET_NULL, related_name="payment")

    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    stripe_checkout_session_id = models.CharField(max_length=200, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment {self.pk} — {self.user} — {self.get_status_display()}"