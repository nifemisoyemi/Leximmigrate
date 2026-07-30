"""
Seed the fixed Phase 1 catalog data.

Run with:  python manage.py seed_catalog

Idempotent: safe to run repeatedly. Tiers and workflow steps are updated to match
this file (they're fixed configuration). Packages are only created if missing, so
re-running never wipes prices you've set in the admin.
"""

from django.core.management.base import BaseCommand

from catalog.models import ApplicationType, Tier, WorkflowStepTemplate, Package


class Command(BaseCommand):
    help = "Seed tiers, the N-400 application type, and its workflow steps."

    def handle(self, *args, **options):
        # --- Tiers (shared across every application type) ---
        tiers = {
            Tier.Level.DIY: dict(
                name="DIY", tagline="You lead the way",
                attorney_minutes=60, includes_document_review=False,
                includes_interview_coaching=False, includes_representation=False,
            ),
            Tier.Level.ENHANCED: dict(
                name="Enhanced", tagline="Attorney review and more time",
                attorney_minutes=120, includes_document_review=True,
                includes_interview_coaching=True, includes_representation=False,
            ),
            Tier.Level.FULL_SERVICE: dict(
                name="Full Service", tagline="We file and represent you",
                attorney_minutes=120, includes_document_review=True,
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
        # (order, title, description, is_document_gate, firm_performed_for_full_service)
        steps = [
            (1, "Introduction", "Orientation content explaining the process.", False, False),
            (2, "Gather your documents", "Upload the documents on your checklist for attorney review.", True, False),
            (3, "Confirm eligibility", "A 30-minute appointment with a licensed immigration attorney.", False, False),
            (4, "File your application", "File online (recommended) or by mail. Full Service: the firm files for you.", False, True),
            (5, "Check your application status", "Track your case status with USCIS.", False, False),
            (6, "Complete application requirements", "Fingerprinting and biometrics instructions.", False, False),
            (7, "Prepare for your USCIS interview", "Study resources for the civics and English test.", False, False),
            (8, "Decision", "Oath ceremony guidance if approved; appeal or reapply information if denied.", False, False),
        ]
        for order, title, desc, gate, firm in steps:
            obj, created = WorkflowStepTemplate.objects.update_or_create(
                application_type=n400, order=order,
                defaults=dict(title=title, description=desc,
                              is_document_gate=gate, firm_performed_for_full_service=firm),
            )
            self.stdout.write(("Created " if created else "Updated ") + f"step {order}: {title}")

        # --- Packages: N-400 x each tier, at launch prices (decided 11-12:30 meeting).
        # get_or_create: only sets prices on FIRST creation — re-running never
        # overwrites prices adjusted in the admin.
        prices = {
            Tier.Level.DIY: 142000,           # $1,420
            Tier.Level.ENHANCED: 192000,      # $1,920
            Tier.Level.FULL_SERVICE: 350000,  # $3,500
        }
        for level, tier in tier_objs.items():
            obj, created = Package.objects.get_or_create(
                application_type=n400, tier=tier,
                defaults=dict(price_cents=prices[level], is_active=True),
            )
            self.stdout.write(("Created " if created else "Exists ") + f"package: {n400.code} {tier.name}")
            
        self.stdout.write(self.style.SUCCESS("Catalog seed complete."))