from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render

from catalog.models import Package, Question, Questionnaire, Tier
from cases.models import Lead

from .forms import ContactForm

# Everything the quiz needs between requests lives in the session under this key.
SESSION_KEY = "quiz"
LEAD_KEY = "quiz_lead"


def _active_questionnaire():
    return (
        Questionnaire.objects
        .filter(application_type__code="N-400", is_active=True)
        .order_by("-version")
        .first()
    )


def _fresh_state():
    return {
        "answers": {},        # {question_id: value}
        "flag_score": 0,      # sum of flag_strength for flagged answers
        "base_level": None,   # tier level from the preference question
        "disqualified": False,
        "stop_reason": "",
        "current_id": None,
    }


def start(request):
    """Reset state and jump to the first question."""
    questionnaire = _active_questionnaire()
    if not questionnaire:
        return HttpResponse("The eligibility check isn't available yet. (Run seed_questionnaire.)")

    first = questionnaire.questions.first()
    state = _fresh_state()
    state["current_id"] = first.id if first else None
    request.session[SESSION_KEY] = state
    request.session.pop(LEAD_KEY, None)

    return redirect("quiz:question") if first else redirect("quiz:contact")


def question(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        return redirect("quiz:start")
    if not state.get("current_id"):
        return redirect("quiz:contact")

    current = Question.objects.filter(id=state["current_id"]).first()
    if not current:
        return redirect("quiz:contact")

    if request.method == "POST":
        next_q = _handle_answer(request, current, state)
        # A disqualifying answer sends us straight to contact.
        if state["disqualified"]:
            state["current_id"] = None
            request.session[SESSION_KEY] = state
            return redirect("quiz:contact")

        state["current_id"] = next_q.id if next_q else None
        request.session[SESSION_KEY] = state
        return redirect("quiz:question") if next_q else redirect("quiz:contact")

    return render(request, "quiz/question.html", {
        "question": current,
        "progress": _progress(current),
    })


def _handle_answer(request, current, state):
    """Record the answer, apply its effects, and return the next Question (or None)."""
    if current.kind == Question.Kind.TEXT:
        state["answers"][str(current.id)] = request.POST.get("answer", "").strip()
        return _next_in_order(current)

    option = current.options.filter(id=request.POST.get("option")).first()
    if not option:
        return current  # no/invalid choice — stay on this question

    state["answers"][str(current.id)] = option.value

    if option.is_flag:
        state["flag_score"] += option.flag_strength
    if option.recommends_tier_id:
        state["base_level"] = max(state["base_level"] or 0, option.recommends_tier.level)
    if option.is_disqualifying:
        state["disqualified"] = True
        state["stop_reason"] = option.label
        return None

    return option.skip_to or _next_in_order(current)


def _next_in_order(current):
    return (
        Question.objects
        .filter(questionnaire=current.questionnaire, order__gt=current.order)
        .order_by("order")
        .first()
    )


def _progress(current):
    total = current.questionnaire.questions.count()
    return {
        "current": current.order,
        "total": total,
        "pct": int(current.order / total * 100) if total else 0,
    }


def contact(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        return redirect("quiz:start")

    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            lead = _create_lead(form.cleaned_data, state)
            request.session[LEAD_KEY] = lead.id
            return redirect("quiz:result")
    else:
        form = ContactForm()

    return render(request, "quiz/contact.html", {"form": form})


def _recommended_package(state):
    if state.get("disqualified"):
        return None
    base = state.get("base_level") or Tier.Level.DIY
    flags = state.get("flag_score", 0)
    if flags >= 2:
        escalation = Tier.Level.FULL_SERVICE
    elif flags == 1:
        escalation = Tier.Level.ENHANCED
    else:
        escalation = Tier.Level.DIY
    final_level = max(base, escalation)
    return (
        Package.objects
        .filter(application_type__code="N-400", tier__level=final_level, is_active=True)
        .select_related("tier")
        .first()
    )


def _create_lead(cleaned, state):
    lead = Lead.objects.create(
        first_name=cleaned["first_name"],
        last_name=cleaned["last_name"],
        email=cleaned["email"],
        phone=cleaned.get("phone", ""),
        questionnaire=_active_questionnaire(),
        answers=state.get("answers", {}),
        likely_eligible=not state.get("disqualified", False),
        recommended_package=_recommended_package(state),
    )
    _notify_firm(lead)
    return lead


def _notify_firm(lead):
    to = getattr(settings, "FIRM_NOTIFICATION_EMAIL", None)
    if not to:
        return
    verdict = "Likely eligible" if lead.likely_eligible else "Not eligible yet"
    rec = lead.recommended_package.tier.name if lead.recommended_package else "—"
    send_mail(
        subject=f"New LexImmigrate lead: {lead.first_name} {lead.last_name}",
        message=(
            f"{lead.first_name} {lead.last_name}\n"
            f"{lead.email} · {lead.phone}\n\n"
            f"Result: {verdict}\n"
            f"Recommended package: {rec}\n"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@leximmigrate.com"),
        recipient_list=[to],
        fail_silently=True,
    )


def result(request):
    state = request.session.get(SESSION_KEY)
    lead_id = request.session.get(LEAD_KEY)
    if not state or not lead_id:
        return redirect("quiz:start")

    lead = (
        Lead.objects
        .select_related("recommended_package__tier")
        .filter(id=lead_id)
        .first()
    )
    return render(request, "quiz/result.html", {
        "lead": lead,
        "disqualified": state.get("disqualified", False),
        "stop_reason": state.get("stop_reason", ""),
    })