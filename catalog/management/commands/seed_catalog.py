"""
Seed the fixed Phase 1 catalog data.

Run with:  python manage.py seed_catalog

Idempotent: safe to run repeatedly. Tiers and workflow steps are updated to match
this file (they're fixed configuration). Packages are only created if missing, so
re-running never wipes prices you've set in the admin.
"""

from django.core.management.base import BaseCommand
from catalog.models import ApplicationType, Tier, WorkflowStepTemplate, Package, ResourceCard


class Command(BaseCommand):
    help = "Seed tiers, the N-400 application type, and its workflow steps."

    def handle(self, *args, **options):
        # --- Tiers (shared across every application type) ---
        tiers = {
            Tier.Level.DIY: dict(
                name="DIY", tagline="You run the whole show",
                included_meetings=0, includes_document_review=False,
                includes_interview_coaching=False, includes_representation=False,
            ),
            Tier.Level.REVIEW: dict(
                name="Attorney Review", tagline="A licensed attorney checks everything before you file",
                included_meetings=1, includes_document_review=True,
                includes_interview_coaching=False, includes_representation=False,
            ),
            Tier.Level.ENHANCED: dict(
                name="Enhanced", tagline="Full preparation, side by side with your attorney",
                included_meetings=2, includes_document_review=True,
                includes_interview_coaching=True, includes_representation=False,
            ),
            Tier.Level.FULL_SERVICE: dict(
                name="Full Service", tagline="Your attorney handles it — and stands with you at your interview",
                included_meetings=0, includes_document_review=True,
                includes_interview_coaching=True, includes_representation=True,
            ),
        }
        tier_objs = {}
        for level, fields in tiers.items():
            obj, created = Tier.objects.update_or_create(level=level, defaults=fields)
            tier_objs[level] = obj
            self.stdout.write(("Created " if created else "Updated ") + f"tier: {obj.name}")

        # --- N-400 application type ---
        n400, created = ApplicationType.objects.update_or_create(
            code="N-400",
            defaults=dict(
                name="Naturalization", order=1, is_active=True,
                description="Application for U.S. citizenship (naturalization).",
            ),
        )
        self.stdout.write(("Created " if created else "Updated ") + f"application type: {n400.code}")

        # --- N-400 workflow steps (the 8 steps from the scope) ---
        # (order, title, description, is_document_gate,
        #  firm_performed_for_full_service, requires_review_to_unlock,
        #  requires_attorney_meeting, body, resource_cards)
        #
        # body uses {% if %} tags matching step_detail.html's tier-flag
        # conditionals: includes_representation, includes_document_review,
        # includes_interview_coaching, meetings_note. See STEP_CONTENT_v2.md
        # for the source document this was approved from.
        steps = [
            (1, "Introduction",
             "Here's what happens, in order — so nothing catches you by surprise.",
             False, False, False, False,
             "Becoming a U.S. citizen is a process with clear stages, and you're "
             "about to go through all of them. Here's the short version, so you "
             "always know where you are:\n\n"
             "1. <strong>Gather your documents</strong> — the paperwork that proves you qualify.\n"
             "2. <strong>File your application</strong> (Form N-400) with the U.S. government's "
             "immigration agency, USCIS.\n"
             "3. <strong>Get fingerprinted</strong> at a short in-person appointment (called "
             "\"biometrics\").\n"
             "4. <strong>Go to an interview</strong>, where an officer reviews your application "
             "and tests your English and your knowledge of U.S. history and "
             "government.\n"
             "5. <strong>Get your decision</strong> — and if approved, attend a ceremony where "
             "you officially become a citizen.\n\n"
             "Most people go from filing to becoming a citizen in about <strong>8 to 18 "
             "months</strong>. The exact time depends on which USCIS office handles your "
             "case — you'll be able to check that yourself once you've filed.\n\n"
             "You won't see a step here until it's actually time for it. Whatever "
             "your package includes, this portal will always show you exactly "
             "where you stand.",
             [("See how long this usually takes", "https://egov.uscis.gov/processing-times/")]),
 
            (2, "Gather your documents",
             "Your checklist — built just for you, not the government's one-size-fits-all list.",
             True, False, False, False,
             "The government's official checklist is the same for every applicant, "
             "and it's confusing — full of \"only if this applies to you\" "
             "instructions. We've already done that part for you: based on your "
             "answers, we've marked which sections apply to your situation. You "
             "can always change what's checked if something about your situation "
             "changes.\n\n"
             "For each section that applies to you, upload a <strong>clear copy</strong> — not "
             "the original document, just a photo or scan — of what's asked for."
             "\n\n"
             "{% if case.package.tier.includes_document_review %}"
             "When everything is uploaded, select <strong>Submit for attorney review</strong>. "
             "A licensed immigration attorney will personally look over everything "
             "before you move forward — this is one of the things you're paying "
             "for, so don't skip it."
             "{% else %}"
             "When everything is uploaded, select <strong>I've gathered everything on my "
             "checklist</strong>. That's it — you're ready for the next step."
             "{% endif %}",
             []),
 
            (3, "Confirm eligibility",
             "Meet your attorney — a quick check-in before you file anything.",
             False, False, False, True,
             "This is your first time actually talking with your attorney about "
             "your case. Think of it as a check-in: they'll go over your situation "
             "and confirm you're ready to file, and answer anything you're unsure "
             "about.\n\n"
             "Go to <strong>Appointments</strong> in the menu to pick a day and time that works "
             "for you. {{ meetings_note }}",
             [("Not sure if you should apply yet?", "https://www.uscis.gov/citizenship/should-i-consider-us-citizenship")]),
 
            (4, "File your application",
             "Time to actually submit your application to the government.",
             False, True, True, False,
             "{% if case.package.tier.includes_representation %}"
             "Your attorney takes it from here — they'll prepare and submit your "
             "application (Form N-400) using everything from the steps before "
             "this one. You'll see it marked \"Filed\" here the moment it's "
             "submitted, and you don't need to do anything else for this step."
             "{% else %}"
             "This is the step where your application actually gets submitted to "
             "USCIS.\n\n"
             "<strong>Filing online is usually the better choice</strong> — it's typically "
             "faster and costs less than mailing in a paper form. To file online, "
             "you'll need a free USCIS account (just an email address and a few "
             "minutes to set up, if you don't already have one).\n\n"
             "Paper filing by mail is only required in specific cases — mainly if "
             "you're asking for a reduced fee or a fee waiver."
             "{% endif %}"
             "\n\n"
             "One more thing: the government's filing fee is paid <strong>directly to "
             "USCIS</strong>, separately from what you paid LexImmigrate. Check the "
             "current amount before you file, since it changes from time to time.",
             [("Set up your free USCIS account", "https://myaccount.uscis.gov/"),
              ("Check the current filing fee", "https://www.uscis.gov/forms/filing-fees")]),
 
            (5, "Check your application status",
             "See exactly where your case stands, anytime — no phone calls, no waiting.",
             False, False, False, False,
             "Once you file, USCIS mails you a receipt with a 13-character code "
             "(your \"receipt number\"). Save that number — it's your key to "
             "checking your case online, anytime, for free.\n\n"
             "Cases can sit for a while without an update, and that's usually "
             "normal. But if your case is taking noticeably longer than USCIS's "
             "typical time for your situation, that's worth mentioning"
             "{% if case.package.tier.includes_representation %} to your attorney"
             "{% else %} — bringing it up during your attorney time is exactly "
             "what that time is for{% endif %}.",
             [("Check your case status", "https://egov.uscis.gov/"),
              ("See typical wait times", "https://egov.uscis.gov/processing-times/")]),
 
            (6, "Complete application requirements",
             "Biometrics — a quick visit for fingerprints and a photo.",
             False, False, False, False,
             "After you file, USCIS will mail you an appointment notice for "
             "something called \"biometrics.\" Don't worry — this isn't your "
             "interview and there's no test. It's a short visit where they take "
             "your fingerprints, a photo, and your signature for a background "
             "check.\n\n"
             "<strong>What to bring:</strong> the appointment notice you received, and a valid "
             "photo ID (like a driver's license or your Green Card).\n\n"
             "If the appointment time doesn't work for you, the notice explains "
             "how to request a new date — but try to keep the original time if "
             "you can, since rescheduling can slow down your case.",
             []),
 
            (7, "Prepare for your interview",
             "Study up — your English and citizenship test happen here too.",
             False, False, False, False,
             "Your interview does two things at once, on the same day: an officer "
             "talks with you about your application, and — unless you qualify for "
             "an exception — you take the citizenship test right then. There's no "
             "separate test day.\n\n"
             "<strong>What the test covers:</strong>\n"
             "- <strong>English</strong> — basic reading, writing, and speaking. This happens "
             "naturally as part of your conversation with the officer.\n"
             "- <strong>Civics</strong> — questions about U.S. history and government. The "
             "officer picks up to 20 questions from a list of 128 possible ones "
             "(all published in advance, so you can study them). You pass as soon "
             "as you get 12 right — so sometimes the officer stops asking before "
             "reaching 20.\n\n"
             "{% if case.package.tier.includes_interview_coaching %}"
             "Your package includes interview prep with your attorney — you'll "
             "practice the format together and go over the civics questions "
             "before your actual interview."
             "{% endif %}",
             [("128 civics questions & answers (2025 test)", "https://www.uscis.gov/sites/default/files/document/questions-and-answers/2025-Civics-Test-128-Questions-and-Answers.pdf"),
              ("Civics flash cards (printable)", "https://www.uscis.gov/sites/default/files/document/flash-cards/M-623_red.pdf"),
              ("100 civics questions with audio", "https://www.uscis.gov/citizenship/find-study-materials-and-resources/study-for-the-test/100-civics-questions-and-answers-with-mp3-audio-english-version"),
              ("What happens during the interview", "https://www.uscis.gov/citizenship/learn-about-citizenship/the-naturalization-interview-and-test")]),
            (8, "Decision",
             "What happens after your interview, whichever way it goes.",
             False, False, False, False,
             "After your interview, one of a few things happens:\n\n"
             "- <strong>Approved</strong> — congratulations. You'll be scheduled for an oath "
             "ceremony, where you officially become a U.S. citizen.\n"
             "- <strong>You need to come back</strong> — sometimes USCIS needs more "
             "information, or wants to give you another chance on part of the "
             "test. This is more common than people expect, and it doesn't mean "
             "something went wrong.\n"
             "- <strong>Not approved</strong> — you'll get a letter explaining why, along with "
             "your options going forward.\n\n"
             "Whatever happens, you don't have to figure out what it means on "
             "your own."
             "{% if case.package.tier.includes_representation %}"
             " Your attorney will walk you through it and handle the next steps."
             "{% else %}"
             " Use your remaining attorney time, or reach out through <strong>Get "
             "Help</strong> — a real person will help you understand exactly what your "
             "result means and what to do next."
             "{% endif %}",
             []),
        ]
        for order, title, desc, gate, firm, review_gate, needs_meeting, body, cards in steps:
            obj, created = WorkflowStepTemplate.objects.update_or_create(
                application_type=n400, order=order,
                defaults=dict(title=title, description=desc,
                              is_document_gate=gate, firm_performed_for_full_service=firm,
                              requires_review_to_unlock=review_gate,
                              requires_attorney_meeting=needs_meeting,
                              body=body),
            )
            self.stdout.write(("Created " if created else "Updated ") + f"step {order}: {title}")
            obj.resource_cards.all().delete()
            for i, (label, url) in enumerate(cards):
                ResourceCard.objects.create(step=obj, order=i, label=label, url=url)

        # --- Packages: N-400 x each tier, 4-package restructure (Aug meeting).
        # update_or_create ON PURPOSE this time: the restructure must overwrite
        # the old 3-tier prices. (price, installments_count, installment_amount)
        prices = {
            Tier.Level.DIY: (62000, None, None),
            Tier.Level.REVIEW: (142000, 3, 50000),
            Tier.Level.ENHANCED: (192000, 4, 50000),
            Tier.Level.FULL_SERVICE: (352000, 5, 76000),
        }
        for level, tier in tier_objs.items():
            price, n, amt = prices[level]
            obj, created = Package.objects.update_or_create(
                application_type=n400, tier=tier,
                defaults=dict(price_cents=price, installments_count=n,
                              installment_amount_cents=amt, is_active=True),
            )
            self.stdout.write(("Created " if created else "Updated ") + f"package: {n400.code} {tier.name}")
            
        self.stdout.write(self.style.SUCCESS("Catalog seed complete."))