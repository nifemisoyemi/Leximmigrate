"""
checkout: the conversion flow — package selection, non-refundable confirmation,
account handoff (accounts app), and Stripe payment.

Money truth lives in the webhook: a Payment is only marked PAID (and a Case only
created) when Stripe's signed checkout.session.completed event arrives. The
success page merely reads that state.
"""

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from cases.models import Case, CaseStep, Lead, Payment
from cases.monday import REASON_PACKAGE_QUESTION, push_lead
from catalog.models import Package, WorkflowStepTemplate
from quiz.views import LEAD_KEY

stripe.api_key = settings.STRIPE_SECRET_KEY

CHECKOUT_KEY = "checkout"          # {"package_id": int, "acknowledged": True}
HELP_SENT_KEY = "checkout_help_sent"


# --- helpers -----------------------------------------------------------------

def _eligible_lead(request):
    """The session's Lead — or, for a logged-in user with no session (new
    device, later visit), their most recent eligible converted lead, restored
    into the session so the rest of the flow works unchanged."""
    lead_id = request.session.get(LEAD_KEY)
    lead = None
    if lead_id:
        lead = (
            Lead.objects
            .select_related("recommended_package__tier")
            .filter(id=lead_id, likely_eligible=True)
            .first()
        )
    if lead is None and request.user.is_authenticated:
        lead = (
            Lead.objects
            .select_related("recommended_package__tier")
            .filter(converted_user=request.user, likely_eligible=True)
            .order_by("-created_at")
            .first()
        )
        if lead:
            request.session[LEAD_KEY] = lead.id
    return lead


# --- package selection -------------------------------------------------------

def packages(request):
    lead = _eligible_lead(request)
    if not lead:
        return redirect("quiz:start")

    package_list = (
        Package.objects
        .filter(application_type__code="N-400", is_active=True)
        .select_related("tier")
        .order_by("tier__level")
    )
    return render(request, "checkout/packages.html", {
        "lead": lead,
        "packages": package_list,
        "recommended_id": lead.recommended_package_id,
        "help_sent": request.session.get(HELP_SENT_KEY, False),
    })


def confirm(request, package_id):
    lead = _eligible_lead(request)
    if not lead:
        return redirect("quiz:start")

    package = get_object_or_404(
        Package.objects.select_related("tier"),
        id=package_id, application_type__code="N-400", is_active=True,
    )

    if request.method == "POST":
        if request.POST.get("acknowledge") != "on":
            return render(request, "checkout/confirm.html", {
                "package": package,
                "error": "Please confirm you understand that packages are non-refundable.",
            })
        request.session[CHECKOUT_KEY] = {"package_id": package.id, "acknowledged": True}
        if request.user.is_authenticated:
            return redirect("checkout:pay")
        return redirect("accounts:register")

    return render(request, "checkout/confirm.html", {"package": package})


def help_me(request):
    if request.method != "POST":
        return redirect("checkout:packages")
    lead = _eligible_lead(request)
    if not lead:
        return redirect("quiz:start")

    if not request.session.get(HELP_SENT_KEY):
        rec = lead.recommended_package.tier.name if lead.recommended_package else "none"
        push_lead(lead, REASON_PACKAGE_QUESTION, details=f"Recommended: {rec}. Wants help choosing a package.")
        request.session[HELP_SENT_KEY] = True
        messages.success(request, "Got it — someone will get in touch to help you choose.")
    return redirect("checkout:packages")


# --- payment -----------------------------------------------------------------

@login_required
def pay(request):
    """Order summary + the button that starts Stripe Checkout."""
    if request.user.cases.exists():
        return redirect("checkout:done")            # Phase 1: one case per client
    state = request.session.get(CHECKOUT_KEY)
    if not state:
        return redirect("checkout:packages")

    package = get_object_or_404(
        Package.objects.select_related("tier", "application_type"),
        id=state["package_id"], is_active=True,
    )

    if request.method == "POST":
        payment = Payment.objects.create(
            user=request.user,
            package=package,
            amount_cents=package.price_cents,
            currency=package.currency,
        )
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": package.currency.lower(),
                    "unit_amount": package.price_cents,
                    "product_data": {
                        "name": f"LexImmigrate {package.tier.name} — {package.application_type.name}",
                    },
                },
                "quantity": 1,
            }],
            customer_email=request.user.email,
            client_reference_id=str(payment.id),
            metadata={"payment_id": str(payment.id)},
            success_url=request.build_absolute_uri(reverse("checkout:success"))
                        + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("checkout:pay")),
        )
        payment.stripe_checkout_session_id = session.id
        payment.save(update_fields=["stripe_checkout_session_id"])
        return redirect(session.url, permanent=False)

    return render(request, "checkout/pay.html", {"package": package})


@login_required
def success(request):
    """Post-Stripe landing. Reads (never writes) payment state — the webhook is
    the source of truth, and may land a second or two after the redirect."""
    session_id = request.GET.get("session_id", "")
    payment = (
        Payment.objects
        .select_related("package__tier", "case")
        .filter(user=request.user, stripe_checkout_session_id=session_id)
        .first()
    )
    if not payment:
        return redirect("checkout:packages")

    paid = payment.status == Payment.Status.PAID
    if paid:
        # Funnel complete: downstream session state is no longer needed.
        for key in (CHECKOUT_KEY, HELP_SENT_KEY):
            request.session.pop(key, None)

    return render(request, "checkout/success.html", {"payment": payment, "paid": paid})


@login_required
def done(request):
    """Landing for clients with an active case — the portal grows from here."""
    case = request.user.cases.select_related("package__tier").order_by("-created_at").first()
    if not case:
        return redirect("checkout:packages")
    return render(request, "checkout/done.html", {"case": case})


# --- webhook (source of truth) ----------------------------------------------

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return HttpResponse(status=400)                 # malformed payload
    except stripe.SignatureVerificationError:
        return HttpResponse(status=400)                 # bad/missing signature

    if event["type"] == "checkout.session.completed":
        _fulfill(event["data"]["object"])

    return HttpResponse(status=200)


def _fulfill(session):
    """Mark the Payment paid and create the Case + its steps. Idempotent:
    Stripe retries webhooks, so a second delivery must change nothing."""
    if session["payment_status"] != "paid":
        return
    payment = (
        Payment.objects
        .select_related("user", "package__application_type")
        .filter(stripe_checkout_session_id=session["id"])
        .first()
    )
    if payment is None or payment.status == Payment.Status.PAID:
        return

    with transaction.atomic():
        step_templates = list(
            WorkflowStepTemplate.objects
            .filter(application_type=payment.package.application_type)
            .order_by("order")
        )
        case = Case.objects.create(
            client=payment.user,
            package=payment.package,
            application_type=payment.package.application_type,
            current_step=step_templates[0] if step_templates else None,
        )
        CaseStep.objects.bulk_create([
            CaseStep(
                case=case,
                template=t,
                status=CaseStep.Status.AVAILABLE if i == 0 else CaseStep.Status.LOCKED,
            )
            for i, t in enumerate(step_templates)
        ])
        payment.status = Payment.Status.PAID
        payment.paid_at = timezone.now()
        payment.stripe_payment_intent_id = session["payment_intent"] or ""
        payment.case = case
        payment.save()