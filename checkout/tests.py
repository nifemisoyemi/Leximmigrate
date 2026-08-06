"""
checkout/tests.py — behavioral tests for the conversion flow and payment.

Stripe is fully mocked: no test ever contacts Stripe. The webhook tests
exercise _fulfill directly (the money-truth function) plus the endpoint's
signature handling, including the idempotency guarantee (a re-delivered
event must change nothing).

Run:  python manage.py test checkout -v 2
"""

from types import SimpleNamespace
from unittest.mock import patch

import stripe
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from cases.models import Case, Lead, Payment
from catalog.models import Package, Tier
from checkout.views import CHECKOUT_KEY, HELP_SENT_KEY, _fulfill
from quiz.views import LEAD_KEY


class CheckoutTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog")   # tiers, N-400, 8 workflow steps, packages
        cls.diy = Package.objects.get(tier__level=Tier.Level.DIY)
        cls.enhanced = Package.objects.get(tier__level=Tier.Level.ENHANCED)

    # -- helpers --------------------------------------------------------------

    def make_lead(self, eligible=True, package=None, user=None, email="lead@example.com"):
        return Lead.objects.create(
            first_name="Test", last_name="Lead", email=email, phone="5125550100",
            likely_eligible=eligible,
            recommended_package=package or self.enhanced,
            converted_user=user,
        )

    def make_user(self, email="client@example.com"):
        return User.objects.create_user(
            username=email, email=email, password="Str0ng!Pass",
            first_name="Cli", last_name="Ent", phone="5125550101",
        )

    def set_session(self, **kv):
        s = self.client.session
        s.update(kv)
        s.save()

    def make_paid_setup(self, user=None):
        """User + lead + checkout state + pending Payment with a session id."""
        user = user or self.make_user()
        lead = self.make_lead(user=user)
        payment = Payment.objects.create(
            user=user, package=self.enhanced,
            amount_cents=self.enhanced.price_cents,
            stripe_checkout_session_id="cs_test_abc123",
        )
        return user, lead, payment

    def stripe_session_dict(self, payment, status="paid"):
        return {
            "id": payment.stripe_checkout_session_id,
            "payment_status": status,
            "payment_intent": "pi_test_123",
        }


class SelectionGuardTests(CheckoutTestBase):
    def test_packages_requires_eligible_lead(self):
        resp = self.client.get(reverse("checkout:packages"))
        self.assertRedirects(resp, reverse("quiz:start"))

    def test_ineligible_lead_is_bounced(self):
        lead = self.make_lead(eligible=False)
        self.set_session(**{LEAD_KEY: lead.id})
        resp = self.client.get(reverse("checkout:packages"))
        self.assertRedirects(resp, reverse("quiz:start"))

    def test_eligible_lead_sees_packages_with_recommendation(self):
        lead = self.make_lead()
        self.set_session(**{LEAD_KEY: lead.id})
        resp = self.client.get(reverse("checkout:packages"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["recommended_id"], self.enhanced.id)

    @patch("checkout.views.push_lead")
    def test_help_pushes_to_monday_once(self, mock_push):
        lead = self.make_lead()
        self.set_session(**{LEAD_KEY: lead.id})
        self.client.post(reverse("checkout:help"))
        self.client.post(reverse("checkout:help"))     # second click
        mock_push.assert_called_once()

    def test_quiz_restart_clears_checkout_state(self):
        """Regression for the edge-case audit: retaking the quiz invalidates
        everything downstream."""
        lead = self.make_lead()
        self.set_session(**{
            LEAD_KEY: lead.id,
            CHECKOUT_KEY: {"package_id": self.diy.id, "acknowledged": True},
            HELP_SENT_KEY: True,
        })
        self.client.get(reverse("quiz:begin"))
        self.assertNotIn(CHECKOUT_KEY, self.client.session)
        self.assertNotIn(HELP_SENT_KEY, self.client.session)
        self.assertNotIn(LEAD_KEY, self.client.session)


class ConfirmTests(CheckoutTestBase):
    def setUp(self):
        self.lead = self.make_lead()
        self.set_session(**{LEAD_KEY: self.lead.id})
        self.url = reverse("checkout:confirm", args=[self.enhanced.id])

    def test_both_checkboxes_required(self):
        for data in ({}, {"acknowledge": "on"}, {"agree_terms": "on"}):
            resp = self.client.post(self.url, data)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("error", resp.context)
            self.assertNotIn(CHECKOUT_KEY, self.client.session)

    def test_anonymous_confirm_goes_to_register(self):
        resp = self.client.post(self.url, {"acknowledge": "on", "agree_terms": "on"})
        self.assertRedirects(resp, reverse("accounts:register"))
        self.assertEqual(self.client.session[CHECKOUT_KEY]["package_id"], self.enhanced.id)

    def test_authenticated_confirm_goes_straight_to_pay(self):
        user = self.make_user()
        self.client.force_login(user)
        self.set_session(**{LEAD_KEY: self.lead.id})
        resp = self.client.post(self.url, {"acknowledge": "on", "agree_terms": "on"})
        self.assertRedirects(resp, reverse("checkout:pay"), target_status_code=200)


class ResumeFlowTests(CheckoutTestBase):
    def test_logged_in_user_with_no_session_resumes_from_converted_lead(self):
        user = self.make_user()
        self.make_lead(user=user)
        self.client.force_login(user)      # fresh session, no LEAD_KEY
        resp = self.client.get(reverse("checkout:packages"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(LEAD_KEY, self.client.session)   # restored

    def test_login_routes_paid_client_to_done(self):
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment))    # make them a paid client
        self.client.force_login(user)
        resp = self.client.get(reverse("accounts:home"))
        self.assertRedirects(resp, reverse("checkout:done"))

    def test_login_routes_unpaid_eligible_user_to_packages(self):
        user = self.make_user()
        self.make_lead(user=user)
        self.client.force_login(user)
        resp = self.client.get(reverse("accounts:home"))
        self.assertRedirects(resp, reverse("checkout:packages"))


class PayTests(CheckoutTestBase):
    def login_with_checkout(self):
        user = self.make_user()
        self.client.force_login(user)
        self.set_session(**{CHECKOUT_KEY: {"package_id": self.enhanced.id, "acknowledged": True}})
        return user

    def test_pay_requires_login(self):
        resp = self.client.get(reverse("checkout:pay"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_pay_without_checkout_state_bounces_to_packages(self):
        self.client.force_login(self.make_user())
        resp = self.client.get(reverse("checkout:pay"))
        self.assertRedirects(resp, reverse("checkout:packages"), target_status_code=302)

    def test_existing_client_cannot_pay_again(self):
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment))
        self.client.force_login(user)
        self.set_session(**{CHECKOUT_KEY: {"package_id": self.diy.id, "acknowledged": True}})
        resp = self.client.get(reverse("checkout:pay"))
        self.assertRedirects(resp, reverse("checkout:done"))

    @patch("checkout.views.stripe.checkout.Session.create")
    def test_post_creates_pending_payment_and_redirects_to_stripe(self, mock_create):
        mock_create.return_value = SimpleNamespace(id="cs_test_new", url="https://checkout.stripe.test/s")
        self.login_with_checkout()
        resp = self.client.post(reverse("checkout:pay"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://checkout.stripe.test/s")
        payment = Payment.objects.get()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.stripe_checkout_session_id, "cs_test_new")
        self.assertEqual(payment.amount_cents, self.enhanced.price_cents)
        # amount charged comes from OUR database, not the client
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["line_items"][0]["price_data"]["unit_amount"],
                         self.enhanced.price_cents)


class WebhookTests(CheckoutTestBase):
    def test_bad_signature_is_rejected(self):
        with patch("checkout.views.stripe.Webhook.construct_event",
                   side_effect=stripe.SignatureVerificationError("bad", "sig")):
            resp = self.client.post(reverse("stripe_webhook"), data=b"{}",
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Case.objects.count(), 0)

    def test_completed_event_fulfills_payment(self):
        user, lead, payment = self.make_paid_setup()
        event = {"type": "checkout.session.completed",
                 "data": {"object": self.stripe_session_dict(payment)}}
        with patch("checkout.views.stripe.Webhook.construct_event", return_value=event):
            resp = self.client.post(reverse("stripe_webhook"), data=b"{}",
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertIsNotNone(payment.paid_at)

    def test_fulfill_creates_case_with_steps(self):
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment))
        case = Case.objects.get()
        self.assertEqual(case.client, user)
        self.assertEqual(case.package, self.enhanced)
        self.assertEqual(case.steps.count(), 8)
        self.assertEqual(case.steps.filter(status="available").count(), 1)
        self.assertEqual(case.steps.first().template.order, 1)
        self.assertEqual(case.current_step.order, 1)
        payment.refresh_from_db()
        self.assertEqual(payment.case, case)

    def test_fulfill_is_idempotent(self):
        """Stripe retries webhooks: a second delivery must change nothing."""
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment))
        _fulfill(self.stripe_session_dict(payment))
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PAID).count(), 1)

    def test_unpaid_session_is_ignored(self):
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment, status="unpaid"))
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(Case.objects.count(), 0)

    def test_unknown_session_is_ignored(self):
        _fulfill({"id": "cs_never_seen", "payment_status": "paid", "payment_intent": "pi_x"})
        self.assertEqual(Case.objects.count(), 0)


class SuccessPageTests(CheckoutTestBase):
    def test_paid_shows_confirmation_and_clears_checkout_session(self):
        user, lead, payment = self.make_paid_setup()
        _fulfill(self.stripe_session_dict(payment))
        self.client.force_login(user)
        self.set_session(**{CHECKOUT_KEY: {"package_id": self.enhanced.id}, HELP_SENT_KEY: True})
        resp = self.client.get(reverse("checkout:success"),
                               {"session_id": payment.stripe_checkout_session_id})
        self.assertContains(resp, "Payment confirmed")
        self.assertNotIn(CHECKOUT_KEY, self.client.session)
        self.assertNotIn(HELP_SENT_KEY, self.client.session)

    def test_pending_shows_confirming_state(self):
        user, lead, payment = self.make_paid_setup()
        self.client.force_login(user)
        resp = self.client.get(reverse("checkout:success"),
                               {"session_id": payment.stripe_checkout_session_id})
        self.assertContains(resp, "Confirming your payment")

    def test_other_users_session_id_is_rejected(self):
        user, lead, payment = self.make_paid_setup()
        other = self.make_user(email="other@example.com")
        self.client.force_login(other)
        resp = self.client.get(reverse("checkout:success"),
                               {"session_id": payment.stripe_checkout_session_id})
        self.assertRedirects(resp, reverse("checkout:packages"), target_status_code=302)