"""
quiz/tests.py — behavioral tests for the eligibility quiz engine.

Strategy: seed the REAL v2 questionnaire (via the actual management command) and
drive the quiz through the HTTP layer like a visitor would. This tests the
engine AND the seeded data together — a wrong flag_strength in the seed fails
these tests just as loudly as a bug in views.py.

The walker answers by matching keywords in question text, so it survives
questions being added/removed (e.g. it passes whether or not the Selective
Service question exists).

Run:  python manage.py test quiz -v 2
"""

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from catalog.models import ApplicationType, Package, Question, Tier
from cases.models import Lead
from quiz.views import SESSION_KEY


def make_catalog():
    """Minimal catalog the quiz needs: N-400, three tiers, three packages."""
    app = ApplicationType.objects.create(code="N-400", name="Naturalization")
    tiers = {}
    for level, name, minutes in [(1, "DIY", 60), (2, "Enhanced", 120), (3, "Full Service", 120)]:
        tiers[level] = Tier.objects.create(level=level, name=name, attorney_minutes=minutes)
    prices = {1: 142000, 2: 192000, 3: 350000}
    for level, tier in tiers.items():
        Package.objects.create(application_type=app, tier=tier, price_cents=prices[level])
    return app, tiers


# Ordered keyword → answer-value map. First keyword found in the current
# question's text decides the answer posted. Override per-test via dict merge.
BASE_ANSWERS = [
    ("18 or older", "yes"),
    ("lawful permanent", "yes"),
    ("married to", "no"),                # default: 5-year path
    ("green card", "5_plus"),
    ("trip outside", "no"),
    ("spent at least", "yes"),
    ("arrested", "no"),
    ("income tax", "yes"),
    ("Selective Service", "na"),         # answered only if the question exists
    ("basic English", "yes"),
    ("How much help", "diy"),
]


class QuizTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_catalog()
        call_command("seed_questionnaire_v2")

    # -- driving helpers ------------------------------------------------------

    def start(self):
        return self.client.get(reverse("quiz:begin"), follow=False)

    def current_question(self):
        state = self.client.session.get(SESSION_KEY)
        if not state or not state.get("current_id"):
            return None
        return Question.objects.get(id=state["current_id"])

    def answer_current(self, value):
        q = self.current_question()
        opt = q.options.get(value=value)
        return self.client.post(reverse("quiz:question"), {"option": opt.id})

    def walk(self, overrides=None):
        """Answer every question using BASE_ANSWERS (+ overrides). Returns the
        final redirect response. Stops early on disqualification."""
        answers = dict(BASE_ANSWERS)
        answers.update(overrides or {})
        self.start()
        resp = None
        for _ in range(30):  # hard stop against infinite loops
            q = self.current_question()
            if q is None:
                break
            for keyword, value in answers.items():
                if keyword.lower() in q.text.lower():
                    resp = self.answer_current(value)
                    break
            else:
                self.fail(f"No test answer matches question: {q.text!r}")
            if self.client.session[SESSION_KEY].get("disqualified"):
                break
        return resp

    def submit_contact(self, **kw):
        data = {"first_name": "Test", "last_name": "Person",
                "email": "test@example.com", "phone": "5125550100"}
        data.update(kw)
        return self.client.post(reverse("quiz:contact"), data)

    def finish_and_get_lead(self, overrides=None):
        self.walk(overrides)
        self.submit_contact()
        self.client.get(reverse("quiz:result"))
        return Lead.objects.latest("created_at")


# -- the tests ----------------------------------------------------------------

class ActiveQuestionnaireTests(QuizTestBase):
    def test_v2_is_the_active_questionnaire(self):
        self.start()
        q = self.current_question()
        self.assertEqual(q.questionnaire.version, 2)


class BranchingTests(QuizTestBase):
    def test_married_yes_takes_three_year_chain(self):
        self.walk_until_after_marriage("yes")
        q = self.current_question()
        values = set(q.options.values_list("value", flat=True))
        self.assertIn("3_plus", values, "expected the 3-year green-card question")

    def test_married_no_takes_five_year_chain(self):
        self.walk_until_after_marriage("no")
        q = self.current_question()
        values = set(q.options.values_list("value", flat=True))
        self.assertIn("5_plus", values, "expected the 5-year green-card question")

    def test_three_year_chain_converges_skipping_five_year_chain(self):
        self.walk_until_after_marriage("yes")
        self.answer_current("3_plus")
        self.answer_current("no")        # trips question
        self.answer_current("yes")       # presence question -> skip_to converge
        q = self.current_question()
        self.assertIn("arrested", q.text.lower(),
                      "3-year chain should land on the arrests question, not the 5-year chain")

    def walk_until_after_marriage(self, married_value):
        self.start()
        self.answer_current("yes")       # 18+
        self.answer_current("yes")       # LPR
        self.answer_current(married_value)


class StopFlowTests(QuizTestBase):
    def test_under_18_stops_immediately_and_skips_contact(self):
        self.start()
        resp = self.answer_current("no")
        self.assertRedirects(resp, reverse("quiz:result"))
        self.assertTrue(self.client.session[SESSION_KEY]["disqualified"])
        self.assertEqual(Lead.objects.count(), 0)

    def test_stop_page_shows_real_message_not_option_label(self):
        self.start()
        self.answer_current("no")
        resp = self.client.get(reverse("quiz:result"))
        self.assertContains(resp, "18 or older to apply")
        # the old bug: the bare option label rendered as the reason
        self.assertNotContains(resp, "<p>No</p>", html=True)

    def test_under_3_years_green_card_stops_with_90_day_message(self):
        self.start()
        self.answer_current("yes")
        self.answer_current("yes")
        self.answer_current("yes")               # 3-year path
        self.answer_current("under_3")
        resp = self.client.get(reverse("quiz:result"))
        self.assertContains(resp, "90 days")
        self.assertContains(resp, "3-year")

    def test_contact_page_is_blocked_after_disqualification(self):
        self.start()
        self.answer_current("no")
        resp = self.client.get(reverse("quiz:contact"))
        self.assertRedirects(resp, reverse("quiz:result"))

    @patch("quiz.views.push_lead")
    def test_followup_creates_lead_and_pushes_to_monday(self, mock_push):
        self.start()
        self.answer_current("no")
        resp = self.client.post(reverse("quiz:followup"), {
            "first_name": "Maria", "last_name": "Lopez",
            "email": "maria@example.com", "phone": "5125550111",
        })
        self.assertRedirects(resp, reverse("quiz:result"))
        lead = Lead.objects.get()
        self.assertFalse(lead.likely_eligible)
        self.assertIsNone(lead.recommended_package)
        mock_push.assert_called_once()
        # confirmation state renders, form is gone
        resp = self.client.get(reverse("quiz:result"))
        self.assertContains(resp, "someone will follow up")

    def test_followup_rejected_without_active_disqualified_session(self):
        resp = self.client.post(reverse("quiz:followup"), {
            "first_name": "X", "last_name": "Y",
            "email": "x@example.com", "phone": "5125550122",
        })
        self.assertRedirects(resp, reverse("quiz:start"))
        self.assertEqual(Lead.objects.count(), 0)


class RecommendationMatrixTests(QuizTestBase):
    def test_no_flags_diy_preference_recommends_diy(self):
        lead = self.finish_and_get_lead()
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.DIY)
        self.assertTrue(lead.likely_eligible)

    def test_no_flags_unsure_preference_defaults_to_diy(self):
        lead = self.finish_and_get_lead({"How much help": "unsure"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.DIY)

    def test_single_flag_escalates_to_enhanced(self):
        lead = self.finish_and_get_lead({"trip outside": "yes"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.ENHANCED)

    def test_moral_character_flag_alone_forces_full_service(self):
        lead = self.finish_and_get_lead({"arrested": "yes"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.FULL_SERVICE)

    def test_two_ordinary_flags_force_full_service(self):
        lead = self.finish_and_get_lead({"trip outside": "yes", "income tax": "unsure"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.FULL_SERVICE)

    def test_higher_preference_wins_over_clean_answers(self):
        lead = self.finish_and_get_lead({"How much help": "full"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.FULL_SERVICE)

    def test_flag_never_downgrades_a_high_preference(self):
        lead = self.finish_and_get_lead({"trip outside": "yes", "How much help": "full"})
        self.assertEqual(lead.recommended_package.tier.level, Tier.Level.FULL_SERVICE)


class GuardTests(QuizTestBase):
    def test_question_page_without_session_redirects_to_start(self):
        resp = self.client.get(reverse("quiz:question"))
        self.assertRedirects(resp, reverse("quiz:start"))

    def test_result_without_lead_redirects_to_start(self):
        self.walk()                       # eligible walk, but no contact submitted
        resp = self.client.get(reverse("quiz:result"))
        self.assertRedirects(resp, reverse("quiz:start"))

    def test_contact_requires_phone(self):
        self.walk()
        resp = self.submit_contact(phone="")
        self.assertEqual(resp.status_code, 200)   # re-rendered with errors
        self.assertEqual(Lead.objects.count(), 0)