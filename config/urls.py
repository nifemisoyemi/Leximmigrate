"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("eligibility/", include("quiz.urls")),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("privacy/", TemplateView.as_view(template_name="legal/privacy.html"), name="legal_privacy"),
    path("terms/", TemplateView.as_view(template_name="legal/terms.html"), name="legal_terms"),
    path("attorney-client-notice/", TemplateView.as_view(template_name="legal/attorney_client_notice.html"), name="legal_notice"),
    path("faq/", TemplateView.as_view(template_name="faq.html"), name="faq"),
]
