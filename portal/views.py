"""
portal: the authenticated client experience, in an app-shell layout
(sidebar + topbar) modeled on the Hello Divorce reference.

Access rule: portal requires an active Case; a Case only exists because a
payment confirmed — so "has a case" IS the privilege check.
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.template import Context, Template
from django.contrib import messages
from django.conf import settings
from cases import services
from cases.models import Case, CaseStep, Document, Lead
from cases.monday import REASON_PACKAGE_QUESTION, push_lead
from catalog.models import DocumentCategory, Question

SECTIONS = {
    
}
## view functions: resources, help_center
## near any the other portal views

def _client_case(request):
    return (
        Case.objects
        .select_related("package__tier", "application_type", "current_step")
        .filter(client=request.user)
        .order_by("-created_at")
        .first()
    )


@login_required
def dashboard(request):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")

    steps = list(case.steps.select_related("template").order_by("template__order"))
    done = sum(1 for s in steps if s.status == CaseStep.Status.COMPLETE)
    current_case_step = next(
        (s for s in steps if s.status in (CaseStep.Status.AVAILABLE, CaseStep.Status.IN_PROGRESS)),
        None,
    )

    return render(request, "portal/dashboard.html", {
        "case": case,
        "steps": steps,
        "current_case_step": current_case_step,
        "done_count": done,
        "total_count": len(steps),
        "pct": int(done / len(steps) * 100) if steps else 0,
        "active": "case",
    })


@login_required
def section(request, key):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")
    if key not in SECTIONS:
        raise Http404
    return render(request, "portal/section.html", {
        "case": case,
        "section": SECTIONS[key],
        "active": key,
    })


@login_required
def step_detail(request, step_id):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")
 
    step = get_object_or_404(
        CaseStep.objects.select_related("template"), id=step_id, case=case,
    )
    if step.status == CaseStep.Status.LOCKED:
        return redirect("portal:dashboard")
    if step.template.is_document_gate:
        return redirect("portal:documents")
 
    if request.method == "POST" and request.POST.get("action") == "complete":
        _complete_step(case, step)
        return redirect("portal:dashboard")
    
    if request.method == "POST" and request.POST.get("action") == "uncomplete":
        _uncomplete_step(case, step)
        return redirect("portal:step", step_id=step.id)

    body_source = step.template.body.replace(
        "{{ meetings_note }}", case.package.tier.meetings_note or ""
    )
    rendered_body = Template(body_source).render(Context({"case": case}))
 
    return render(request, "portal/step_detail.html", {
        "case": case,
        "step": step,
        "active": "case",
        "rendered_body": rendered_body,
        "can_self_complete": (
            step.status in (CaseStep.Status.AVAILABLE, CaseStep.Status.IN_PROGRESS)
            and not step.template.is_document_gate
        ),
        "can_uncomplete": step.status == CaseStep.Status.COMPLETE and not step.template.is_document_gate,
    })


def _complete_step(case, step):
    if step.template.is_document_gate:
        return
    if step.status not in (CaseStep.Status.AVAILABLE, CaseStep.Status.IN_PROGRESS):
        return

    step.status = CaseStep.Status.COMPLETE
    step.completed_at = timezone.now()
    step.save(update_fields=["status", "completed_at"])

    next_step = (
        case.steps
        .select_related("template")
        .filter(template__order__gt=step.template.order)
        .order_by("template__order")
        .first()
    )
    if next_step:
        blocked = (
            next_step.template.requires_review_to_unlock
            and case.package.tier.includes_document_review
            and case.status != Case.Status.ACTIVE
        )
        if next_step.status == CaseStep.Status.LOCKED and not blocked:
            next_step.status = CaseStep.Status.AVAILABLE
            next_step.save(update_fields=["status"])
        case.current_step = next_step.template
        case.save(update_fields=["current_step"])

def _uncomplete_step(case, step):
    if step.status != CaseStep.Status.COMPLETE:
        return
    step.status = CaseStep.Status.AVAILABLE
    step.completed_at = None
    step.save(update_fields=["status", "completed_at"])

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024   # 15 MB

# Quiz question keyword -> the M-477 category orders that answer implies.
INFERENCE_RULES = [
    ("married to", {"yes"}, [3, 4, 5, 6]),
    ("trip outside", {"yes", "unsure"}, [8]),
    ("arrested", {"yes"}, [10, 11, 12, 13]),
    ("income tax", {"no", "unsure"}, [14]),
    ("basic english", {"no", "unsure"}, [15]),
]


def _infer_applicable(case):
    """Pre-toggle conditional categories from the client's quiz answers.
    Runs only on a case's very first visit to the checklist."""
    lead = (
        Lead.objects.filter(converted_user=case.client, likely_eligible=True)
        .order_by("-created_at").first()
    )
    if not lead or not lead.answers:
        return []
    questions = {str(q.id): q.text.lower() for q in
                Question.objects.filter(questionnaire=lead.questionnaire)}
    orders = set()
    for qid, value in lead.answers.items():
        text = questions.get(str(qid), "")
        for keyword, values, category_orders in INFERENCE_RULES:
            if keyword in text and str(value).lower() in values:
                orders.update(category_orders)
    return list(
        DocumentCategory.objects.filter(
            application_type=case.application_type, order__in=orders
        )
    )


@login_required
def documents(request):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")

    can_edit = case.status == Case.Status.GATHERING
    frozen = case.status == Case.Status.PENDING_REVIEW

    all_categories = list(
        DocumentCategory.objects.filter(application_type=case.application_type)
        .order_by("order")
    )

    # First visit: pre-toggle from quiz answers.
    if (can_edit and not case.applicable_categories.exists()
            and not case.documents.exists() and case.documents_submitted_at is None):
        inferred = _infer_applicable(case)
        if inferred:
            case.applicable_categories.set(inferred)

    toggled_ids = set(case.applicable_categories.values_list("id", flat=True))

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "toggles" and can_edit:
            ids = request.POST.getlist("applies")
            case.applicable_categories.set(
                DocumentCategory.objects.filter(
                    application_type=case.application_type, id__in=ids,
                    is_required=False,
                )
            )
            messages.success(request, "Your checklist has been updated.")
            return redirect("portal:documents")

        if action == "upload" and can_edit:
            category = next((c for c in all_categories
                            if str(c.id) == request.POST.get("category_id")), None)
            upload = request.FILES.get("file")
            error = _validate_upload(category, upload, toggled_ids)
            if error:
                messages.error(request, error)
            else:
                Document.objects.create(
                    case=case, category=category, file=upload,
                    original_filename=upload.name,
                    content_type=upload.content_type or "",
                    size_bytes=upload.size,
                )
                messages.success(request, f"Uploaded to “{category.name}”.")
            return redirect("portal:documents")

        if action == "delete" and can_edit:
            case.documents.filter(
                id=request.POST.get("document_id"),
                status__in=[Document.Status.UPLOADED, Document.Status.NEEDS_REVISION],
            ).delete()
            return redirect("portal:documents")

        if action == "submit":
            if _checklist_ready(case, all_categories, toggled_ids):
                if case.package.tier.includes_document_review:
                    services.submit_for_review(case)
                    messages.success(request, "Submitted — your attorney will review your documents. You can keep working on your next steps in the meantime.")
                else:
                    services.self_certify(case)
                    messages.success(request, "Checklist complete — your next step is unlocked.")
            else:
                messages.error(request, "Every section that applies to you needs at least one document first.")
            return redirect("portal:documents")

        if action == "withdraw" and frozen:
            services.withdraw_review(case)
            messages.success(request, "Submission withdrawn — you can edit your documents again.")
            return redirect("portal:documents")

        return redirect("portal:documents")

    # ---- build display structure -------------------------------------------
    docs_by_category = {}
    for doc in case.documents.select_related("category").order_by("uploaded_at"):
        docs_by_category.setdefault(doc.category_id, []).append(doc)

    required, optional = [], []
    for c in all_categories:
        entry = {
            "category": c,
            "docs": docs_by_category.get(c.id, []),
            "applies": c.is_required or c.id in toggled_ids,
        }
        (required if c.is_required else optional).append(entry)

    applicable = [e for e in required + optional if e["applies"]]
    with_docs = sum(1 for e in applicable if e["docs"])
    needs_fixes = case.documents.filter(status=Document.Status.NEEDS_REVISION).exists()

    return render(request, "portal/documents.html", {
        "case": case,
        "active": "documents",
        "required": required,
        "optional": optional,
        "can_edit": can_edit,
        "frozen": frozen,
        "review_tier": case.package.tier.includes_document_review,
        "applicable_count": len(applicable),
        "with_docs_count": with_docs,
        "ready": with_docs == len(applicable) and len(applicable) > 0,
        "needs_fixes": needs_fixes,
    })


def _validate_upload(category, upload, toggled_ids):
    if category is None:
        return "Choose a document section to upload into."
    if not (category.is_required or category.id in toggled_ids):
        return "That section isn't marked as applying to you."
    if upload is None:
        return "Choose a file to upload."
    name = upload.name.lower()
    if not any(name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return "Please upload a PDF, JPG, or PNG file."
    if upload.size > MAX_UPLOAD_BYTES:
        return "That file is larger than 15 MB — please compress or rescan it."
    return ""


def _checklist_ready(case, all_categories, toggled_ids):
    doc_cat_ids = set(case.documents.values_list("category_id", flat=True))
    for c in all_categories:
        if (c.is_required or c.id in toggled_ids) and c.id not in doc_cat_ids:
            return False
    return any(c.is_required or c.id in toggled_ids for c in all_categories)

@login_required
def appointments(request):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")
 
    tier = case.package.tier
    can_book = tier.included_meetings > 0 or tier.includes_representation
 
    return render(request, "portal/appointments.html", {
        "case": case,
        "active": "appointments",
        "can_book": can_book,
        "acuity_owner_id": settings.ACUITY_OWNER_ID,
    })

@login_required
def resources(request):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")
 
    has_access = case.package.tier.includes_interview_coaching
 
    return render(request, "portal/resources.html", {
        "case": case,
        "active": "resources",
        "has_access": has_access,
    })

@login_required
def help_center(request):
    case = _client_case(request)
    if not case:
        return redirect("accounts:home")
 
    if request.method == "POST":
        message = request.POST.get("message", "").strip()
        if message:
            lead = Lead.objects.filter(converted_user=request.user).order_by("-created_at").first()
            details = f"Portal help request (Case #{case.pk}, {case.package.tier.name}): {message[:1500]}"
            if lead:
                push_lead(lead, REASON_PACKAGE_QUESTION, details=details)
            from cases.notifications import send_help_request_received
            send_help_request_received(request.user, message)
            messages.success(request, "Your message has been sent — someone will get back to you within 1–3 business days.")
        return redirect("portal:help")
 
    return render(request, "portal/help.html", {
        "case": case,
        "active": "help",
    })