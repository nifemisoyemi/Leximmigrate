"""
checkout: the conversion flow — package selection now; account handoff and
Stripe Checkout in the next stages.

Entry requires an eligible Lead in the session (set by the quiz). The chosen
package + non-refundable acknowledgment are stored in the session and consumed
by registration/payment in later stages.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from cases.models import Lead
from cases.monday import REASON_PACKAGE_QUESTION, push_lead
from catalog.models import Package
from quiz.views import LEAD_KEY

CHECKOUT_KEY = "checkout"          # {"package_id": int, "acknowledged": True}
HELP_SENT_KEY = "checkout_help_sent"


def _eligible_lead(request):
    """The session's Lead, but only if the quiz marked them likely eligible."""
    lead_id = request.session.get(LEAD_KEY)
    if not lead_id:
        return None
    return (
        Lead.objects
        .select_related("recommended_package__tier")
        .filter(id=lead_id, likely_eligible=True)
        .first()
    )


def packages(request):
    """All purchasable N-400 packages; the recommended one is highlighted, but
    any can be chosen (firm decision: free choice)."""
    lead = _eligible_lead(request)
    if not lead:
        return redirect("quiz:start")

    package_list = (
        Package.objects
        .filter(application_type__code="N-400", is_active=True)
        .select_related("tier")
        .order_by("tier__level")
    )
    recommended_id = lead.recommended_package_id

    return render(request, "checkout/packages.html", {
        "lead": lead,
        "packages": package_list,
        "recommended_id": recommended_id,
        "help_sent": request.session.get(HELP_SENT_KEY, False),
    })


def confirm(request, package_id):
    """Show the chosen package; require explicit non-refundable acknowledgment
    before moving on to account creation."""
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
        return redirect("checkout:next")

    return render(request, "checkout/confirm.html", {"package": package})


def help_me(request):
    """One click: 'not sure which package — have someone contact me'. The lead
    already has full contact info, so no form: push straight to the Monday CRM."""
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


def next_step(request):
    """Stage-2 placeholder: account creation replaces this view."""
    state = request.session.get(CHECKOUT_KEY)
    if not state:
        return redirect("checkout:packages")
    package = Package.objects.select_related("tier").filter(id=state["package_id"]).first()
    return render(request, "checkout/next.html", {"package": package})