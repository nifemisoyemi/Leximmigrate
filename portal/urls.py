from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("step/<int:step_id>/", views.step_detail, name="step"),
    path("s/<slug:key>/", views.section, name="section"),
]