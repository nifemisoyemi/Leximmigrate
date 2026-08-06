from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render

from catalog.models import Package, Question, QuestionOption, Questionnaire, Tier
from cases.models import Lead

from .forms import ContactForm
from cases.monday import REASON_NOT_ELIGIBLE, push_lead

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
        "history": [],
    }

def start(request):
    """Informational landing before the quiz. The actual reset lives in begin()."""
    return render(request, "quiz/intro.html")

def begin(request):
    """Reset state and jump to the first question."""
    # Reset the funnel FIRST — retaking invalidates everything downstream,
    # unconditionally, even if the questionnaire is temporarily unavailable.
    request.session.pop(LEAD_KEY, None)
    request.session.pop(SESSION_KEY + "_followup_done", None)
    request.session.pop("checkout", None)
    request.session.pop("checkout_help_sent", None)

    questionnaire = _active_questionnaire()
    if not questionnaire:
        request.session.pop(SESSION_KEY, None)   # no stale quiz state either
        return HttpResponse("The eligibility check isn't available yet. (Run seed_questionnaire.)")

    first = questionnaire.questions.first()
    state = _fresh_state()
    state["current_id"] = first.id if first else None
    request.session[SESSION_KEY] = state

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
            return redirect("quiz:result")

        if next_q is None or next_q.id != current.id:      # don't log invalid re-renders
            state.setdefault("history", []).append(current.id)
        state["current_id"] = next_q.id if next_q else None
        request.session[SESSION_KEY] = state
        return redirect("quiz:question") if next_q else redirect("quiz:contact")

    return render(request, "quiz/question.html", {
        "question": current,
        "progress": _progress(current),
        "has_back": bool(state.get("history")),
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
        state["stop_reason"] = option.stop_message or "Based on your answers, you don't meet one of the requirements yet."
        return None

    return option.skip_to or _next_in_order(current)

def _recompute(state):
    """Rebuild flag/tier state from surviving answers (after a Back)."""
    state["flag_score"] = 0
    state["base_level"] = None
    for qid, value in state["answers"].items():
        opt = QuestionOption.objects.filter(question_id=qid, value=value).select_related("recommends_tier").first()
        if not opt:
            continue
        if opt.is_flag:
            state["flag_score"] += opt.flag_strength
        if opt.recommends_tier_id:
            state["base_level"] = max(state["base_level"] or 0, opt.recommends_tier.level)


def back(request):
    state = request.session.get(SESSION_KEY)
    if not state or not state.get("history"):
        return redirect("quiz:question")
    prev_id = state["history"].pop()
    state["answers"].pop(str(prev_id), None)
    state["current_id"] = prev_id
    _recompute(state)
    request.session[SESSION_KEY] = state
    return redirect("quiz:question")

def _next_in_order(current):
    return (
        Question.objects
        .filter(questionnaire=current.questionnaire, order__gt=current.order)
        .order_by("order")
        .first()
    )


def _progress(current):
    """Path-aware:count questions actually shown, not raw table order."""
    total_visible = 10 # 3 shared + 3 in one path + 4 converged
    ORDER_TO_STEP = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 4, 8: 5, 9: 6, 10: 7, 11: 8, 13: 9, 14: 10}
    step = ORDER_TO_STEP.get(current.order, current.order)
    return {
        "current": step,
        "total": total_visible,
        "pct": int(step / total_visible * 100),
    }


def contact(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        return redirect("quiz:start")

    if state.get("disqualified"):
        return redirect("quiz:result")

    if request.user.is_authenticated:
        lead = _create_lead({
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "email": request.user.email,
            "phone": request.user.phone,
        }, state)
        lead.converted_user = request.user
        lead.status = Lead.Status.CONVERTED
        lead.save(update_fields=["converted_user", "status"])
        request.session[LEAD_KEY] = lead.id
        return redirect("quiz:result")

    if state.get("current_id"):
        return redirect("quiz:question")

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

def followup(request):
    """Optional 'still want to talk?' form on the STOP result page."""
    state = request.session.get(SESSION_KEY)
    if not state or not state.get("disqualified"):
        return redirect("quiz:start")

    if request.method != "POST":
        return redirect("quiz:result")

    form = ContactForm(request.POST)
    if not form.is_valid():
        return render(request, "quiz/result.html", {
            "lead": None,
            "disqualified": True,
            "stop_reason": state.get("stop_reason", ""),
            "followup_form": form,   # re-render with errors
        })

    lead = _create_lead(form.cleaned_data, state)
    push_lead(lead, REASON_NOT_ELIGIBLE, details=state.get("stop_reason", ""))
    request.session[SESSION_KEY + "_followup_done"] = True
    return redirect("quiz:result")

def result(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        return redirect("quiz:start")

    disqualified = state.get("disqualified", False)

    lead = None
    if not disqualified:
        lead_id = request.session.get(LEAD_KEY)
        if not lead_id:
            return redirect("quiz:start")
        lead = (
            Lead.objects
            .select_related("recommended_package__tier")
            .filter(id=lead_id)
            .first()
        )

    return render(request, "quiz/result.html", {
        "lead": lead,
        "disqualified": disqualified,
        "stop_reason": state.get("stop_reason", ""),
        "followup_form": ContactForm(),
        "followup_done": request.session.get(SESSION_KEY + "_followup_done", False),
    })