"""
Seed N-400 document categories from the official USCIS M-477 Document Checklist
(Rev. 11/21/2016), restructured for the personalized portal checklist.

Run with:  python manage.py seed_document_categories

Universal categories are is_required=True. Conditional ("If...") categories are
is_required=False — the portal presents them as "applies to me" groups, and the
quiz answers let us pre-highlight the relevant ones.

Idempotent via update_or_create on (application_type, order): safe to re-run;
edits made here win over admin edits for these rows.
"""

from django.core.management.base import BaseCommand

from catalog.models import ApplicationType, DocumentCategory


CATEGORIES = [
    # (order, name, required, allows_multiple, description, is_form, form_url, form_code)
    (1, "Permanent Resident Card (Green Card)", True, True,
     "A copy of both sides of your Permanent Resident Card. Lost your card? "
     "Upload the receipt of your Form I-90 replacement application instead.", 
     False, "", ""),

    (2, "Legal name change documents", False, True,
     "Only if your current legal name is different from the name on your Green "
     "Card: the document that changed it — marriage certificate, divorce "
     "decree, or court order.", False, "", ""),

    # --- Marriage-based (3-year path) ---------------------------------------
    (3, "Proof your spouse is a U.S. citizen", False, True,
     "Marriage-based applicants only. One of: your spouse's birth certificate, "
     "Certificate of Naturalization, Certificate of Citizenship, the inside "
     "front cover and signature page of their current U.S. passport, or Form "
     "FS-240.", False, "", ""),

    (4, "Your current marriage certificate", False, False,
     "Marriage-based applicants only.", False, "", ""),

    (5, "End of your spouse's earlier marriages", False, True,
     "Marriage-based applicants only, and only if your spouse was married "
     "before: divorce decrees, annulments, or death certificates for each "
     "earlier marriage.", False, "", ""),

    (6, "Evidence of your life together", False, True,
     "Marriage-based applicants only. Documents that refer to both of you: "
     "joint tax returns or IRS tax transcripts for the last 3 years, joint "
     "bank accounts, leases or mortgages, or birth certificates of your "
     "children.", False, "", ""),

    (7, "End of your own earlier marriages", False, True,
     "Only if you were married before: divorce decrees, annulments, or death "
     "certificates for each earlier marriage.", False, "", ""),

    # --- Absences ------------------------------------------------------------
    (8, "Proof of U.S. ties during long trips", False, True,
     "Only if you took a trip of 6 months or longer since getting your Green "
     "Card: evidence you kept living and working in the U.S. — an IRS tax "
     "return transcript for the last 5 years (3 if marriage-based), rent or "
     "mortgage payments, or pay stubs.", False, "", ""),

    # --- Dependents ----------------------------------------------------------
    (9, "Support for family living apart from you", False, True,
     "Only if you have a dependent spouse or children who don't live with "
     "you: any court or government support order, plus proof you've paid — "
     "cancelled checks, payment printouts, wage garnishment records, or a "
     "letter from the parent or guardian caring for your children.", 
     False, "", ""),

    # --- Criminal history ----------------------------------------------------
    (10, "Arrest records (no charges filed)", False, True,
     "Only if you were ever arrested or detained and no charges were filed: "
     "an original official statement from the arresting agency or court "
     "confirming no charges were filed.", False, "", ""),

    (11, "Court records (charges filed)", False, True,
     "Only if charges were ever filed: an original or court-certified copy of "
     "the complete arrest record and outcome for each incident — dismissal "
     "order, conviction record, or acquittal order.", False, "", ""),

    (12, "Sentencing and completion records", False, True,
     "Only if you were ever convicted or placed in an alternative sentencing "
     "or rehabilitative program: the sentencing record for each incident, "
     "plus proof you completed your sentence, probation, parole, or program.", 
     False, "", ""),

    (13, "Expunged or vacated record orders", False, True,
     "Only if an arrest or conviction was ever vacated, set aside, sealed, or "
     "expunged: the court order removing it, or a court statement that no "
     "record exists.", False, "", ""),

    # --- Taxes ---------------------------------------------------------------
    (14, "IRS correspondence and payment plans", False, True,
     "Only if you ever failed to file a required tax return, or owe overdue "
     "taxes: all correspondence with the IRS about the missed filing, and/or "
     "a signed repayment agreement with the IRS or state/local tax office "
     "plus its current status.", False, "", ""),

    # --- Exceptions & special cases -----------------------------------------
    (15, "Form N-648 disability certification", False, False,
     "Only if you're requesting a disability exception to the English or "
     "civics testing requirement: Form N-648, completed by a licensed doctor "
     "or clinical psychologist within the last 6 months.", False, "", ""),

    (16, "Selective Service status letter", False, False,
     "Only for men 26 or older who lived in the U.S. between ages 18 and 26 "
     "and did not register with the Selective Service: a Status Information "
     "Letter from the Selective Service System.", False, "", ""),

    (17, "Form N-426 military certification", False, False,
     "Only if you're applying based on current U.S. military service: a "
     "completed original Form N-426.", False, "", ""),

    (18, "Photos (applicants living outside the U.S.)", False, False,
     "Only if you live outside the United States: 2 identical color "
     "photographs with your name and A-Number written lightly in pencil on "
     "the back.", False, "", ""),

     # --- Forms (live on the Application step, not the Documents page) ------
    (19, "Completed Form N-400 (your application draft)", True, False,
     "Your filled-out N-400, saved as a PDF — not yet submitted to USCIS. "
     "Download the official form from the link on this step, fill it out "
     "completely, and upload the draft here.",
     True, "https://www.uscis.gov/n-400", "N-400"),
 
    (20, "Form N-648 — medical certification for a test exception", False, False,
     "Only if you're asking to be excused from the English or civics test "
     "because of a disability: this form must be completed by a licensed "
     "doctor or clinical psychologist within the last 6 months.",
     True, "https://www.uscis.gov/n-648", "N-648"),
 
    (21, "Form I-912 — request for a fee waiver", False, False,
     "Only if you're asking USCIS to waive the filing fee because of low "
     "income or public benefits. Note: filing with a fee waiver must be done "
     "by mail, not online.",
     True, "https://www.uscis.gov/i-912", "I-912"),
]


class Command(BaseCommand):
    help = "Seed N-400 document categories from the USCIS M-477 checklist."

    def handle(self, *args, **options):
        app = ApplicationType.objects.filter(code="N-400").first()
        if not app:
            self.stderr.write("N-400 application type not found — run seed_catalog first.")
            return

        for order, name, required, multiple, desc, is_form, form_url, form_code in CATEGORIES:
            obj, created = DocumentCategory.objects.update_or_create(
                application_type=app, order=order,
                defaults=dict(name=name, description=desc,
                              is_required=required, allows_multiple=multiple,
                              is_form=is_form, form_url=form_url, form_code=form_code),
            )
            self.stdout.write(("Created " if created else "Updated ") + f"{order}. {name}")

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(CATEGORIES)} document categories from M-477."
        ))