from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("step/<int:step_id>/", views.step_detail, name="step"),
    path("s/<slug:key>/", views.section, name="section"),
    path("documents/", views.documents, name="documents"),
    path("appointments/", views.appointments, name="appointments"),
    path("resources/", views.resources, name="resources"),
    path("help/", views.help_center, name="help"),
]