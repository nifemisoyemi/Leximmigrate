"""
cases/notifications.py — every outbound client email the app sends, in one
place. Same design as cases/monday.py: never raises, logs failures, and the
app's behavior never depends on an email actually sending.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _send(to_email, subject, template_name, context):
    if not to_email:
        return
    try:
        body = render_to_string(f"emails/{template_name}.txt", context)
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Email failed to send: %s to %s", template_name, to_email)


def send_receipt(payment):
    _send(
        payment.user.email,
        f"Your LexImmigrate receipt — {payment.package.tier.name}",
        "receipt",
        {"payment": payment, "user": payment.user},
    )


def send_case_started(case):
    _send(
        case.client.email,
        "Your LexImmigrate case is ready",
        "case_started",
        {"case": case, "user": case.client},
    )


def send_documents_submitted(case):
    _send(
        case.client.email,
        "We've received your documents for review",
        "documents_submitted",
        {"case": case, "user": case.client},
    )


def send_review_passed(case):
    _send(
        case.client.email,
        "Your documents have been approved",
        "review_passed",
        {"case": case, "user": case.client},
    )


def send_needs_revision(document):
    _send(
        document.case.client.email,
        "A document needs your attention",
        "needs_revision",
        {"document": document, "case": document.case, "user": document.case.client},
    )


def send_help_request_received(user, message):
    _send(
        user.email,
        "We've got your message",
        "help_received",
        {"user": user, "message": message},
    )