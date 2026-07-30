from django.urls import path

from . import views

app_name = "checkout"

urlpatterns = [
    path("", views.packages, name="packages"),
    path("confirm/<int:package_id>/", views.confirm, name="confirm"),
    path("help/", views.help_me, name="help"),
    path("next/", views.next_step, name="next"),
]