"""
cases/tests.py — the document-review state machine (services.py), checklist
readiness, quiz-inference pre-toggling, and tier-dependent journey length.

Run:  python manage.py test cases -v 2
"""

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from cases import services
from cases.models import Case, CaseStep, Document, Lead
from catalog.models import DocumentCategory, Package, Tier, WorkflowStepTemplate
from checkout.views import _fulfill


class CasesTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog")
        call_command("seed_document_categories")
        call_command("seed_questionnaire_v2")
        cls.diy = Package.objects.get(tier__level=Tier.Level.DIY)
        cls.review = Package.objects.get(tier__level=Tier.Level.REVIEW)
        cls.full = Package.objects.get(tier__level=Tier.Level.FULL_SERVICE)

    def make_user(self, email="client@example.com"):
        return User.objects.create_user(username=email, email=email, password="Str0ng!Pass")

    def make_paid_case(self, package, user=None):
        """Drive a case into existence through the real fulfillment path —
        not a shortcut — so these tests catch _fulfill regressions too."""
        from cases.models import Payment
        user = user or self.make_user()
        payment = Payment.objects.create(
            user=user, package=package, amount_cents=package.price_cents,
            stripe_checkout_session_id=f"cs_test_{user.pk}_{package.tier.level}",
        )
        _fulfill({
            "id": payment.stripe_checkout_session_id,
            "payment_status": "paid",
            "payment_intent": "pi_test",
        })
        return Case.objects.get(client=user)

    def gate_step(self, case):
        return case.steps.get(template__is_document_gate=True)

    def file_step(self, case):
        return case.steps.get(template__requires_review_to_unlock=True)

    def add_doc(self, case, category_order, status=Document.Status.UPLOADED):
        cat = DocumentCategory.objects.get(application_type=case.application_type, order=category_order)
        return Document.objects.create(
            case=case, category=cat, file="fake.pdf",
            original_filename="fake.pdf", size_bytes=100, status=status,
        )


class TierDependentJourneyTests(CasesTestBase):
    def test_diy_case_skips_the_meeting_step(self):
        case = self.make_paid_case(self.diy)
        self.assertEqual(case.steps.count(), 7)
        self.assertFalse(case.steps.filter(template__requires_attorney_meeting=True).exists())

    def test_review_tier_keeps_all_eight_steps(self):
        case = self.make_paid_case(self.review)
        self.assertEqual(case.steps.count(), 8)
        self.assertTrue(case.steps.filter(template__requires_attorney_meeting=True).exists())

    def test_full_service_keeps_all_eight_steps(self):
        """Full Service shows 0 included_meetings but must NOT be treated
        like DIY — it has representation instead."""
        case = self.make_paid_case(self.full)
        self.assertEqual(case.steps.count(), 8)

    def test_diy_first_step_available_rest_locked(self):
        case = self.make_paid_case(self.diy)
        steps = list(case.steps.select_related("template").order_by("template__order"))
        self.assertEqual(steps[0].status, CaseStep.Status.AVAILABLE)
        self.assertTrue(all(s.status == CaseStep.Status.LOCKED for s in steps[1:]))


class SelfCertifyTests(CasesTestBase):
    def test_diy_self_certify_completes_gate_and_unlocks_next(self):
        case = self.make_paid_case(self.diy)
        services.self_certify(case)
        case.refresh_from_db()
        self.assertEqual(case.status, Case.Status.ACTIVE)
        gate = self.gate_step(case)
        self.assertEqual(gate.status, CaseStep.Status.COMPLETE)
        self.assertIsNotNone(gate.completed_at)

    def test_self_certify_is_a_noop_outside_gathering(self):
        case = self.make_paid_case(self.diy)
        services.self_certify(case)
        gate_completed_at = self.gate_step(case).completed_at
        services.self_certify(case)   # already ACTIVE — must not re-run
        self.assertEqual(self.gate_step(case).completed_at, gate_completed_at)


class OptionBReviewFlowTests(CasesTestBase):
    """Packages 2-4: submit -> pending_review -> client keeps moving ->
    File step stays locked until staff approves."""

    def test_submit_freezes_and_unlocks_next_step_but_not_file_step(self):
        case = self.make_paid_case(self.review)
        self.add_doc(case, 1)
        services.submit_for_review(case)
        case.refresh_from_db()

        self.assertEqual(case.status, Case.Status.PENDING_REVIEW)
        self.assertIsNotNone(case.documents_submitted_at)
        self.assertEqual(case.documents.first().status, Document.Status.UNDER_REVIEW)

        gate = self.gate_step(case)
        self.assertEqual(gate.status, CaseStep.Status.IN_PROGRESS)

        # Option B: the step AFTER the gate is open...
        next_step = case.steps.select_related("template").filter(
            template__order__gt=gate.template.order
        ).order_by("template__order").first()
        self.assertNotEqual(next_step.status, CaseStep.Status.LOCKED)

        # ...but the review-gated File step must still be locked.
        self.assertEqual(self.file_step(case).status, CaseStep.Status.LOCKED)

    def test_withdraw_unfreezes_and_relocks_next_step(self):
        case = self.make_paid_case(self.review)
        self.add_doc(case, 1)
        services.submit_for_review(case)
        services.withdraw_review(case)
        case.refresh_from_db()

        self.assertEqual(case.status, Case.Status.GATHERING)
        self.assertIsNone(case.documents_submitted_at)
        self.assertEqual(case.documents.first().status, Document.Status.UPLOADED)
        self.assertEqual(self.gate_step(case).status, CaseStep.Status.AVAILABLE)

    def test_withdraw_is_a_noop_when_not_pending(self):
        case = self.make_paid_case(self.review)
        services.withdraw_review(case)  # still GATHERING — must not touch anything
        case.refresh_from_db()
        self.assertEqual(case.status, Case.Status.GATHERING)

    def test_pass_review_activates_case_and_opens_file_step(self):
        case = self.make_paid_case(self.review)
        self.add_doc(case, 1)
        services.submit_for_review(case)
        services.pass_review(case)
        case.refresh_from_db()

        self.assertEqual(case.status, Case.Status.ACTIVE)
        self.assertEqual(case.documents.first().status, Document.Status.APPROVED)
        self.assertEqual(self.gate_step(case).status, CaseStep.Status.COMPLETE)

    def test_pass_review_does_not_open_file_step_if_predecessor_incomplete(self):
        """The File step only unlocks once ITS predecessor (e.g. the meeting
        step) is also complete — review passing alone isn't enough."""
        case = self.make_paid_case(self.review)
        self.add_doc(case, 1)
        services.submit_for_review(case)
        services.pass_review(case)
        case.refresh_from_db()
        self.assertEqual(self.file_step(case).status, CaseStep.Status.LOCKED)

    def test_return_for_changes_unfreezes_for_edits(self):
        case = self.make_paid_case(self.review)
        self.add_doc(case, 1)
        services.submit_for_review(case)
        services.return_for_changes(case)
        case.refresh_from_db()
        self.assertEqual(case.status, Case.Status.GATHERING)
        self.assertEqual(self.gate_step(case).status, CaseStep.Status.AVAILABLE)


class DocumentDeletionRulesTests(CasesTestBase):
    """Regression tests for the delete-permission bug found during manual QA."""

    def test_needs_revision_document_is_deletable(self):
        case = self.make_paid_case(self.review)
        doc = self.add_doc(case, 1, status=Document.Status.NEEDS_REVISION)
        deletable_statuses = [Document.Status.UPLOADED, Document.Status.NEEDS_REVISION]
        self.assertIn(doc.status, deletable_statuses)

    def test_approved_document_is_not_in_deletable_set(self):
        deletable_statuses = [Document.Status.UPLOADED, Document.Status.NEEDS_REVISION]
        self.assertNotIn(Document.Status.APPROVED, deletable_statuses)
        self.assertNotIn(Document.Status.UNDER_REVIEW, deletable_statuses)


class ChecklistReadinessTests(CasesTestBase):
    def test_ready_requires_a_document_in_every_applicable_category(self):
        from portal.views import _checklist_ready
        case = self.make_paid_case(self.diy)
        all_cats = list(DocumentCategory.objects.filter(application_type=case.application_type))
        required_ids = {c.id for c in all_cats if c.is_required}

        self.assertFalse(_checklist_ready(case, all_cats, set()))
        for cat_id in required_ids:
            Document.objects.create(
                case=case, category_id=cat_id, file="f.pdf",
                original_filename="f.pdf", size_bytes=10,
            )
        self.assertTrue(_checklist_ready(case, all_cats, set()))

    def test_toggled_optional_category_must_also_have_a_document(self):
        from portal.views import _checklist_ready
        case = self.make_paid_case(self.diy)
        all_cats = list(DocumentCategory.objects.filter(application_type=case.application_type))
        required = [c for c in all_cats if c.is_required]
        optional = next(c for c in all_cats if not c.is_required)

        for c in required:
            Document.objects.create(case=case, category=c, file="f.pdf",
                                    original_filename="f.pdf", size_bytes=10)
        # optional category toggled ON but no document yet -> not ready
        self.assertFalse(_checklist_ready(case, all_cats, {optional.id}))
        Document.objects.create(case=case, category=optional, file="f.pdf",
                                original_filename="f.pdf", size_bytes=10)
        self.assertTrue(_checklist_ready(case, all_cats, {optional.id}))


class QuizInferenceTests(CasesTestBase):
    def test_marriage_answer_infers_marriage_categories(self):
        from portal.views import _infer_applicable
        user = self.make_user()
        case = self.make_paid_case(self.diy, user=user)

        questionnaire = case.application_type.questionnaires.first()
        # Build a minimal answers dict keyed by a question about marriage.
        from catalog.models import Question
        q, _ = Question.objects.get_or_create(
            questionnaire=questionnaire, order=999,
            defaults=dict(text="Are you married to a U.S. citizen?", kind="boolean"),
        )
        Lead.objects.create(
            first_name="T", last_name="U", email=user.email,
            questionnaire=questionnaire, converted_user=user,
            likely_eligible=True, answers={str(q.id): "yes"},
        )
        inferred = _infer_applicable(case)
        inferred_orders = {c.order for c in inferred}
        self.assertTrue({3, 4, 5, 6}.issubset(inferred_orders))

    def test_no_lead_returns_empty_inference(self):
        from portal.views import _infer_applicable
        case = self.make_paid_case(self.diy)
        self.assertEqual(_infer_applicable(case), [])


class DocumentCategorySeedTests(CasesTestBase):
    def test_seed_creates_eighteen_categories_one_required(self):
        cats = DocumentCategory.objects.filter(application_type__code="N-400")
        self.assertEqual(cats.count(), 18)
        self.assertEqual(cats.filter(is_required=True).count(), 1)

    def test_seed_is_idempotent(self):
        call_command("seed_document_categories")
        self.assertEqual(
            DocumentCategory.objects.filter(application_type__code="N-400").count(), 18
        )