from django.shortcuts import render

from .models import Package


def home(request):
    packages = (
        Package.objects
        .filter(application_type__code="N-400", is_active=True)
        .select_related("tier")
        .order_by("tier__level")
    )
    return render(request, "home.html", {"packages": packages})