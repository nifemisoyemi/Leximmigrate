from django.urls import path

from . import views

app_name = "quiz"

urlpatterns = [
    path("", views.start, name="start"),
    path("begin/", views.begin, name="begin"),
    path("question/", views.question, name="question"),
    path("back/", views.back, name="back"),
    path("contact/", views.contact, name="contact"),
    path("followup/", views.followup, name="followup"),
    path("result/", views.result, name="result"),
]