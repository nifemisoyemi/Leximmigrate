"""
cases/services.py — the document-review state machine (Option B).

One place owns every transition, used by both the portal (client side) and the
admin (staff side), so the rules can't drift apart:

  gathering --submit (tiers 2-4)--> pending_review --pass--> active
      ^                                   |
      |<---------- withdraw / return -----|
  gathering --self-certify (DIY)--------------------> active

While pending_review the client keeps progressing (Option B), but any step
template flagged requires_review_to_unlock stays locked until `active`.
"""

from django.utils import timezone

from .models import Case, CaseStep, Document


def _step(case, *, gate=False, order=None):
    qs = case.steps.select_related("template")
    if gate:
        return qs.filter(template__is_document_gate=True).first()
    return qs.filter(template__order=order).first()


def _unlock_next_after(case, case_step):
    nxt = (
        case.steps.select_related("template")
        .filter(template__order__gt=case_step.template.order)
        .order_by("template__order")
        .first()
    )
    if not nxt:
        return
    blocked = (
        nxt.template.requires_review_to_unlock
        and case.package.tier.includes_document_review
        and case.status != Case.Status.ACTIVE
    )
    if nxt.status == CaseStep.Status.LOCKED and not blocked:
        nxt.status = CaseStep.Status.AVAILABLE
        nxt.save(update_fields=["status"])
    case.current_step = nxt.template
    case.save(update_fields=["current_step"])


def submit_for_review(case):
    """Tiers 2-4: client says the checklist is complete. Freeze uploads, queue
    for the attorney, and let the client keep moving (Option B)."""
    if case.status != Case.Status.GATHERING:
        return
    case.status = Case.Status.PENDING_REVIEW
    case.documents_submitted_at = timezone.now()
    case.save(update_fields=["status", "documents_submitted_at"])
    case.documents.filter(status=Document.Status.UPLOADED).update(
        status=Document.Status.UNDER_REVIEW
    )
    gate = _step(case, gate=True)
    if gate:
        gate.status = CaseStep.Status.IN_PROGRESS
        gate.save(update_fields=["status"])
        _unlock_next_after(case, gate)


def withdraw_review(case):
    """Client pulls the submission back to fix something — allowed only while
    still pending (no attorney decision recorded yet)."""
    if case.status != Case.Status.PENDING_REVIEW:
        return
    case.status = Case.Status.GATHERING
    case.documents_submitted_at = None
    case.save(update_fields=["status", "documents_submitted_at"])
    case.documents.filter(status=Document.Status.UNDER_REVIEW).update(
        status=Document.Status.UPLOADED
    )
    gate = _step(case, gate=True)
    if gate:
        gate.status = CaseStep.Status.AVAILABLE
        gate.save(update_fields=["status"])


def self_certify(case):
    """DIY only: the client certifies their own checklist. Fully automated —
    no staff involvement, per the firm's design."""
    if case.status != Case.Status.GATHERING:
        return
    case.status = Case.Status.ACTIVE
    case.save(update_fields=["status"])
    gate = _step(case, gate=True)
    if gate:
        gate.status = CaseStep.Status.COMPLETE
        gate.completed_at = timezone.now()
        gate.save(update_fields=["status", "completed_at"])
        _unlock_next_after(case, gate)


def pass_review(case, reviewer=None):
    """Staff: the attorney approves the document set. Opens the review-gated
    step(s) and completes the gate."""
    if case.status not in (Case.Status.PENDING_REVIEW, Case.Status.GATHERING):
        return
    now = timezone.now()
    case.documents.filter(status=Document.Status.UNDER_REVIEW).update(
        status=Document.Status.APPROVED, reviewed_by=reviewer, reviewed_at=now
    )
    case.status = Case.Status.ACTIVE
    case.save(update_fields=["status"])
    gate = _step(case, gate=True)
    if gate and gate.status != CaseStep.Status.COMPLETE:
        gate.status = CaseStep.Status.COMPLETE
        gate.completed_at = now
        gate.save(update_fields=["status", "completed_at"])
    # Unlock any review-gated step whose predecessor is already complete.
    steps = list(case.steps.select_related("template").order_by("template__order"))
    for i, s in enumerate(steps):
        if s.status == CaseStep.Status.LOCKED and s.template.requires_review_to_unlock:
            prev_done = i == 0 or steps[i - 1].status == CaseStep.Status.COMPLETE
            if prev_done:
                s.status = CaseStep.Status.AVAILABLE
                s.save(update_fields=["status"])
            break


def return_for_changes(case):
    """Staff: send the set back to the client (after marking individual
    documents needs-revision with notes). Unfreezes the checklist."""
    if case.status != Case.Status.PENDING_REVIEW:
        return
    case.status = Case.Status.GATHERING
    case.save(update_fields=["status"])
    gate = _step(case, gate=True)
    if gate:
        gate.status = CaseStep.Status.AVAILABLE
        gate.save(update_fields=["status"])