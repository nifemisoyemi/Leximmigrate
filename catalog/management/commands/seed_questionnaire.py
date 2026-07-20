"""
Seed the DRAFT N-400 eligibility questionnaire (version 1).

Run with:  python manage.py seed_questionnaire

This is the draft logic pending Yohana's review. Once seeded, edit it freely in the
admin (add/remove/reword questions, change branching, toggle flags). Re-running this
command will NOT overwrite existing questions — if v1 already has questions, it stops.
To re-seed from scratch, delete v1's questions in the admin first.
"""

from django.core.management.base import BaseCommand

from catalog.models import ApplicationType, Question, QuestionOption, Questionnaire, Tier


class Command(BaseCommand):
    help = "Seed the draft N-400 eligibility questionnaire (v1)."

    def handle(self, *args, **options):
        app = ApplicationType.objects.filter(code="N-400").first()
        if not app:
            self.stderr.write("N-400 application type not found — run `seed_catalog` first.")
            return

        questionnaire, _ = Questionnaire.objects.get_or_create(
            application_type=app, version=1, defaults={"is_active": True}
        )
        if not questionnaire.is_active:
            questionnaire.is_active = True
            questionnaire.save()

        if questionnaire.questions.exists():
            self.stdout.write(
                "Questionnaire v1 already has questions — edit them in the admin. "
                "(Delete them there first if you want to re-seed.)"
            )
            return

        tiers = {t.level: t for t in Tier.objects.all()}
        SINGLE, BOOLEAN = Question.Kind.SINGLE, Question.Kind.BOOLEAN

        def add_q(order, text, kind=SINGLE, help_text=""):
            return Question.objects.create(
                questionnaire=questionnaire, order=order, text=text, kind=kind, help_text=help_text
            )

        def add_opt(question, label, value, order=0, *, disq=False, flag=False, strength=1, tier=None):
            QuestionOption.objects.create(
                question=question, label=label, value=value, order=order,
                is_disqualifying=disq, is_flag=flag, flag_strength=strength,
                recommends_tier=tiers.get(tier) if tier else None,
            )

        q1 = add_q(1, "Are you 18 or older?", BOOLEAN)
        add_opt(q1, "Yes", "yes", 0)
        add_opt(q1, "No", "no", 1, disq=True)

        q2 = add_q(2, "Are you a lawful permanent resident (green card holder)?", BOOLEAN)
        add_opt(q2, "Yes", "yes", 0)
        add_opt(q2, "No", "no", 1, disq=True)

        q3 = add_q(3, "Are you married to, and living with, a U.S. citizen who has been a citizen for at least the last 3 years?", BOOLEAN)
        add_opt(q3, "Yes", "yes", 0)
        add_opt(q3, "No", "no", 1)

        q4 = add_q(4, "Have you held your green card long enough to apply?", SINGLE,
                   "5 years — or 3 years if you're married to a U.S. citizen.")
        add_opt(q4, "Yes", "yes", 0)
        add_opt(q4, "No", "no", 1, disq=True)
        add_opt(q4, "I'm not sure", "unsure", 2, flag=True)

        q5 = add_q(5, "In that period, have you taken any single trip outside the U.S. of 6 months or longer?", SINGLE)
        add_opt(q5, "No", "no", 0)
        add_opt(q5, "Yes", "yes", 1, flag=True)
        add_opt(q5, "I'm not sure", "unsure", 2, flag=True)

        q6 = add_q(6, "Have you spent at least half of your required time physically inside the U.S.?", SINGLE)
        add_opt(q6, "Yes", "yes", 0)
        add_opt(q6, "No", "no", 1, flag=True)
        add_opt(q6, "I'm not sure", "unsure", 2, flag=True)

        q7 = add_q(7, "Have you lived in your current U.S. state for at least the last 3 months?", BOOLEAN)
        add_opt(q7, "Yes", "yes", 0)
        add_opt(q7, "No", "no", 1, flag=True)

        q8 = add_q(8, "Have you ever been arrested, cited, charged, or convicted of any crime — even if it was dismissed or expunged?", BOOLEAN)
        add_opt(q8, "No", "no", 0)
        add_opt(q8, "Yes", "yes", 1, flag=True, strength=2)

        q9 = add_q(9, "Have you filed federal income tax returns for every year you were required to?", SINGLE)
        add_opt(q9, "Yes", "yes", 0)
        add_opt(q9, "No", "no", 1, flag=True)
        add_opt(q9, "I'm not sure", "unsure", 2, flag=True)

        q10 = add_q(10, "Can you read, write, and speak basic English, and are you prepared to study for the civics test?", SINGLE)
        add_opt(q10, "Yes", "yes", 0)
        add_opt(q10, "I may need an accommodation", "accommodation", 1, flag=True)

        q11 = add_q(11, "How much help would you like?", SINGLE)
        add_opt(q11, "I'm confident doing it myself", "diy", 0, tier=Tier.Level.DIY)
        add_opt(q11, "I'd like an attorney to review everything before I file", "enhanced", 1, tier=Tier.Level.ENHANCED)
        add_opt(q11, "I want an attorney to handle it and represent me", "full", 2, tier=Tier.Level.FULL_SERVICE)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded draft N-400 questionnaire v1 with {questionnaire.questions.count()} questions."
        ))