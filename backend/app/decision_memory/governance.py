"""Proposal previews are data only; this module has no write or execution port."""

from hashlib import sha256

from .lessons import OutcomeInsight
from .models import Domain, FrozenModel


class ReviewProposal(FrozenModel):
    proposal_id: str
    tenant_id: str
    proposal_type: str
    source_case_ids: tuple[str, ...]
    outcome_refs: tuple[str, ...]
    analysis_version: int = 1
    reason_codes: tuple[str, ...]
    uncertainties: tuple[str, ...]
    affected_policy_ref: str | None = None
    human_review_required: bool = True
    execution_authorized: bool = False


def propose_review(tenant_id: str, domain: Domain, insight: OutcomeInsight) -> ReviewProposal:
    kind = (
        {
            Domain.SUPPLIER: "REVIEW_SUPPLIER_PERFORMANCE",
            Domain.CAPACITY: "REVIEW_CAPACITY_ASSUMPTION",
            Domain.RECOVERY: "REVIEW_RECOVERY_POLICY",
            Domain.ORDER: "REVIEW_INCOMPLETE_EVIDENCE",
        }[domain]
        if insight.verified_count
        else "REVIEW_INCOMPLETE_EVIDENCE"
    )
    fingerprint = sha256(
        (tenant_id + domain + "|".join(insight.source_case_ids)).encode()
    ).hexdigest()[:16]
    return ReviewProposal(
        proposal_id=f"dm-review-{fingerprint}",
        tenant_id=tenant_id,
        proposal_type=kind,
        source_case_ids=insight.source_case_ids,
        outcome_refs=insight.outcome_refs,
        reason_codes=("VERIFIED_OUTCOME_REVIEW",)
        if insight.verified_count
        else ("MISSING_VERIFIED_HISTORY",),
        uncertainties=insight.limitations,
    )
