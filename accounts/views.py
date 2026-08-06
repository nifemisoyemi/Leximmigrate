from django.shortcuts import render

# Create your views here.
from django.contrib.auth import login
from django.shortcuts import redirect, render

from cases.models import Lead
from checkout.views import CHECKOUT_KEY
from quiz.views import LEAD_KEY

from .forms import RegistrationForm
from django.contrib.auth.decorators import login_required

def register(request):
    """Create the client account mid-checkout. Requires a confirmed package in
    the session (set by checkout confirm). Converts the quiz Lead on success."""
    if not request.session.get(CHECKOUT_KEY):
        return redirect("checkout:packages")

    # Already logged in (e.g. buying after a previous visit): skip creation.
    if request.user.is_authenticated:
        _convert_lead(request, request.user)
        return redirect("checkout:pay")

    lead = Lead.objects.filter(id=request.session.get(LEAD_KEY)).first()

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            _convert_lead(request, user)
            login(request, user)          # sessions survive login via cycle, keys kept
            return redirect("checkout:pay")
    else:
        initial = {}
        if lead:
            initial = {
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "email": lead.email,
                "phone": lead.phone,
            }
        form = RegistrationForm(initial=initial)

    return render(request, "accounts/register.html", {"form": form})


def _convert_lead(request, user):
    lead_id = request.session.get(LEAD_KEY)
    if not lead_id:
        return
    Lead.objects.filter(id=lead_id, converted_user__isnull=True).update(
        converted_user=user, status=Lead.Status.CONVERTED
    )

@login_required
def account_home(request):
    """Post-login router: paid clients -> portal (later); unpaid-but-eligible ->
    resume at packages; everyone else -> home."""
    if request.user.cases.exists():
        return redirect("checkout:done")   # placeholder; becomes the portal
    lead = (
        Lead.objects
        .filter(converted_user=request.user, likely_eligible=True)
        .order_by("-created_at")
        .first()
    )
    if lead:
        return redirect("checkout:packages")
    return redirect("home")