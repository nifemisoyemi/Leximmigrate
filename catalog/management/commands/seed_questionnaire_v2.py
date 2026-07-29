"""
Seed the N-400 eligibility questionnaire VERSION 2 (post 11-12:30 meeting).

Run with:  python manage.py seed_questionnaire_v2

REQUIRES the `stop_message` field on QuestionOption (makemigrations + migrate
first — the command checks and refuses to run without it).

What it does:
  - Deactivates v1 (leaves its data intact; existing Leads reference it).
  - Creates Questionnaire v2 as the active one.
  - Seeds the full branching flow: Q3 forks into a 3-year chain (orders 4-6)
    and a 5-year chain (orders 7-9) via skip_to, converging at order 10.

Safe to inspect before running; will NOT overwrite if v2 already has questions.
"""

from django.core.management.base import BaseCommand

from catalog.models import ApplicationType, Question, QuestionOption, Questionnaire, Tier


class Command(BaseCommand):
    help = "Seed N-400 questionnaire v2 (branching paths, stop messages, meeting changes)."

    def handle(self, *args, **options):
        # Refuse to run if the model change hasn't been migrated yet.
        if not hasattr(QuestionOption, "stop_message"):
            self.stderr.write(
                "QuestionOption has no `stop_message` field. Add it to catalog/models.py, "
                "run makemigrations + migrate, then re-run this command."
            )
            return

        app = ApplicationType.objects.filter(code="N-400").first()
        if not app:
            self.stderr.write("N-400 application type not found — run `seed_catalog` first.")
            return

        v2, _ = Questionnaire.objects.get_or_create(
            application_type=app, version=2, defaults={"is_active": False}
        )
        if v2.questions.exists():
            self.stdout.write(
                "Questionnaire v2 already has questions — edit in the admin, or delete "
                "them there first to re-seed."
            )
            return

        tiers = {t.level: t for t in Tier.objects.all()}
        SINGLE, BOOLEAN = Question.Kind.SINGLE, Question.Kind.BOOLEAN

        def add_q(order, text, kind=SINGLE, help_text=""):
            return Question.objects.create(
                questionnaire=v2, order=order, text=text, kind=kind, help_text=help_text
            )

        def add_opt(question, label, value, order=0, *, disq=False, stop="",
                    flag=False, strength=1, tier=None, skip_to=None):
            return QuestionOption.objects.create(
                question=question, label=label, value=value, order=order,
                is_disqualifying=disq, stop_message=stop,
                is_flag=flag, flag_strength=strength,
                recommends_tier=tiers.get(tier) if tier else None,
                skip_to=skip_to,
            )

        # ---- Create all questions first (so skip_to targets exist) ----------

        q1 = add_q(1, "Are you 18 or older?", BOOLEAN)
        q2 = add_q(2, "Are you a lawful permanent resident (green card holder)?", BOOLEAN)
        q3 = add_q(3, "Are you married to, and living with, a U.S. citizen who has been a citizen for at least the last 3 years?", BOOLEAN)

        # 3-year chain (orders 4-6)
        q4a = add_q(4, "How long have you had your green card?")
        q5a = add_q(5, "In the last 3 years, have you taken any single trip outside the U.S. of 6 months or longer?")
        q6a = add_q(6, "During the last 3 years, have you spent at least a year and a half in the U.S.?")

        # 5-year chain (orders 7-9)
        q4b = add_q(7, "How long have you had your green card?")
        q5b = add_q(8, "In the last 5 years, have you taken any single trip outside the U.S. of 6 months or longer?")
        q6b = add_q(9, "During the last 5 years, have you spent at least 2 and a half years in the U.S.?")

        # Converged (orders 10-14)
        q7 = add_q(10, "Have you ever been arrested, cited, charged, or convicted of any crime — even if it was dismissed or expunged?", BOOLEAN)
        q8 = add_q(11, "Have you filed federal income tax returns?")
        q10 = add_q(13, "Can you read, write, and speak basic English, and are you prepared to study for the civics test?")
        q11 = add_q(14, "How much help would you like?")

        # ---- Options ---------------------------------------------------------

        add_opt(q1, "Yes", "yes", 0)
        add_opt(q1, "No", "no", 1, disq=True,
                stop="You must be 18 or older to apply for naturalization.")

        add_opt(q2, "Yes", "yes", 0)
        add_opt(q2, "No", "no", 1, disq=True,
                stop="Naturalization requires a green card first. There may be another path that fits your situation.")

        add_opt(q3, "Yes", "yes", 0)                      # falls through to q4a (next in order)
        add_opt(q3, "No", "no", 1, skip_to=q4b)           # jump to 5-year chain

        # 3-year chain
        add_opt(q4a, "3 years or more", "3_plus", 0)
        add_opt(q4a, "Less than 3 years", "under_3", 1, disq=True,
                stop="Not quite yet — you can file as early as 90 days before your 3-year mark as a permanent resident.")
        add_opt(q4a, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q5a, "No", "no", 0)
        add_opt(q5a, "Yes", "yes", 1, flag=True)
        add_opt(q5a, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q6a, "Yes", "yes", 0, skip_to=q7)         # converge past the 5-year chain
        add_opt(q6a, "No", "no", 1, flag=True, skip_to=q7)
        add_opt(q6a, "I'm not sure", "unsure", 2, flag=True, skip_to=q7)

        # 5-year chain
        add_opt(q4b, "5 years or more", "5_plus", 0)
        add_opt(q4b, "Less than 5 years", "under_5", 1, disq=True,
                stop="Not quite yet — you can file as early as 90 days before your 5-year mark as a permanent resident.")
        add_opt(q4b, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q5b, "No", "no", 0)
        add_opt(q5b, "Yes", "yes", 1, flag=True)
        add_opt(q5b, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q6b, "Yes", "yes", 0)                     # q7 is next in order anyway
        add_opt(q6b, "No", "no", 1, flag=True)
        add_opt(q6b, "I'm not sure", "unsure", 2, flag=True)

        # Converged
        add_opt(q7, "No", "no", 0)
        add_opt(q7, "Yes", "yes", 1, flag=True, strength=2)   # moral character alone -> Full Service

        add_opt(q8, "Yes", "yes", 0)
        add_opt(q8, "No", "no", 1, flag=True)
        add_opt(q8, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q10, "Yes", "yes", 0)
        add_opt(q10, "No", "no", 1, flag=True)
        add_opt(q10, "I'm not sure", "unsure", 2, flag=True)

        add_opt(q11, "I'm confident doing it myself", "diy", 0, tier=Tier.Level.DIY)
        add_opt(q11, "I'd like an attorney to review everything before I file", "enhanced", 1, tier=Tier.Level.ENHANCED)
        add_opt(q11, "I want an attorney to handle it and represent me start to finish", "full", 2, tier=Tier.Level.FULL_SERVICE)
        add_opt(q11, "I'm not sure", "unsure", 3)              # no tier: flags alone decide

        # ---- Flip active version --------------------------------------------
        Questionnaire.objects.filter(application_type=app, version=1).update(is_active=False)
        v2.is_active = True
        v2.save()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded questionnaire v2 with {v2.questions.count()} questions "
            f"(13 total; visitors see 10 — one 3-question chain is skipped per path). "
            f"v1 deactivated."
        ))