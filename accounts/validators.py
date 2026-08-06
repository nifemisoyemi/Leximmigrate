import re

from django.core.exceptions import ValidationError


class ComplexityValidator:
    """Requires an uppercase letter, a lowercase letter, a number, and a
    special character. (Length is enforced by MinimumLengthValidator.)"""

    RULES = [
        (r"[A-Z]", "an uppercase letter"),
        (r"[a-z]", "a lowercase letter"),
        (r"\d", "a number"),
        (r"[^A-Za-z0-9]", "a special character"),
    ]

    def validate(self, password, user=None):
        missing = [label for pattern, label in self.RULES if not re.search(pattern, password)]
        if missing:
            raise ValidationError(
                "Your password must contain " + ", ".join(missing) + ".",
                code="password_complexity",
            )

    def get_help_text(self):
        return "Your password must contain an uppercase letter, a lowercase letter, a number, and a special character."