from django.urls import path

from . import views

app_name = "quiz"

urlpatterns = [
    path("", views.start, name="start"),
    path("question/", views.question, name="question"),
    path("contact/", views.contact, name="contact"),
    path("result/", views.result, name="result"),
    path("followup/", views.followup, name="followup"),
]