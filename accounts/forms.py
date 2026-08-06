from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegistrationForm(UserCreationForm):
    """Email-first registration. Username is set to the email behind the scenes;
    clients never see or choose a username."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone = forms.CharField(max_length=32)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists. Try logging in instead."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = self.cleaned_data["email"]     # email IS the username
        user.role = User.Role.CLIENT
        if commit:
            user.save()
        return user