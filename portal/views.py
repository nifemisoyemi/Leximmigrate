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

from cases.models import Case, CaseStep

SECTIONS = {
    "documents": {
        "eyebrow": "Documents", "title": "Your document checklist",
        "body": "Every document your application needs, in one place — you'll upload each item here and track its review by your attorney.",
        "note": "This area unlocks in the next phase of the build, once the firm's official N-400 checklist is loaded.",
    },
    "appointments": {
        "eyebrow": "Appointments", "title": "Schedule attorney time",
        "body": "Book the one-on-one meetings included in your package, right from your portal.",
        "note": "Online scheduling is being connected now — until then, the firm will reach out to arrange your meetings.",
    },
    "resources": {
        "eyebrow": "Study resources", "title": "Prepare for your tests",
        "body": "Civics test questions, English practice, and interview preparation materials for your package.",
        "note": "Study materials are being loaded for Enhanced and Full Service packages.",
    },
    "help": {
        "eyebrow": "Get help", "title": "We're here for you",
        "body": "Questions about your case, your package, or the process — reach out and a member of the team will get back to you within 1–3 business days.",
        "note": "A direct contact option is coming here. For now, use the phone number on your receipt or the main site.",
    },
}


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

    if request.method == "POST" and request.POST.get("action") == "complete":
        _complete_step(case, step)
        return redirect("portal:dashboard")

    return render(request, "portal/step_detail.html", {
        "case": case,
        "step": step,
        "active": "case",
        "can_self_complete": (
            step.status in (CaseStep.Status.AVAILABLE, CaseStep.Status.IN_PROGRESS)
            and not step.template.is_document_gate
        ),
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
        if next_step.status == CaseStep.Status.LOCKED:
            next_step.status = CaseStep.Status.AVAILABLE
            next_step.save(update_fields=["status"])
        case.current_step = next_step.template
        case.save(update_fields=["current_step"])