"""Closed production authority boundaries for the CURRENT upstream capabilities.

Core exposes demo headers, current proposal facts and generic audit/outbox rows.
It does NOT expose authenticated membership, P4 action grants or a persisted,
revocable approval/expiry contract. P1's default directory is synthetic and lacks
typed verified outbound identity. P4 owns durable outbound consent in preferences.py.
No production adapter can honestly
issue a positive grant from those sources. These boundaries report the missing
capabilities and reject; they never silently use test fixtures or demo policies.

Current Core facts are independently read by CommunicationRequestService's
read_current_basis, shared by intake and draft revalidation. Such facts are NOT
permission. Implement a positive adapter only after upstream authority exists;
The separate explicitly scoped synthetic adapters never enable these production
classes, and still reject the absent Core approval producer contract.
"""

from typing import NoReturn

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import CommitmentTerms
from .schemas import (
    DraftReviewDecision, RecoveryCommunicationReference, RequestAuthorization,
    ReviewAction, ReviewAuthorization,
)


def _unavailable(code: str, message: str, missing: tuple[str, ...]) -> NoReturn:
    raise DomainError(code, message, status_code=503, details={
        "integration_status": "UNAVAILABLE",
        "missing_capabilities": list(missing),
    })


class RuntimeRequestAuthority:
    """RequestAuthority boundary; cannot grant from the present Core records."""

    def check_availability(self) -> NoReturn:
        _unavailable("COMMUNICATION_AUTHORITY_UNAVAILABLE",
            "Trusted request authorization and current approval evidence are unavailable", (
                "CORE_AUTHENTICATED_ACTOR_AND_TENANT_MEMBERSHIP",
                "CORE_COMMUNICATION_REQUEST_ACTION_POLICY",
                "CORE_P3_CURRENT_PLAN_PROPOSAL_APPROVAL_AND_REVOCATION",
                "CORE_APPROVAL_AND_PROPOSAL_EXPIRY",
                "CORE_P3_SOURCE_EVENT_PROVENANCE",
            ))

    def authorize_request(self, db: Session, context: RequestContext,
                          reference: RecoveryCommunicationReference,
                          terms: CommitmentTerms) -> RequestAuthorization | None:
        self.check_availability()


class RuntimeDraftAuthority:
    """Neither READ_DRAFT nor PREPARE_DRAFT may reuse an old snapshot as proof."""

    def check_availability(self) -> NoReturn:
        _unavailable("DRAFT_REVALIDATION_UNAVAILABLE",
            "Trusted draft approval, recipient and channel validation are unavailable", (
                "CORE_AUTHENTICATED_ACTOR_AND_TENANT_MEMBERSHIP",
                "CORE_READ_DRAFT_AND_PREPARE_DRAFT_ACTION_POLICY",
                "CORE_P3_CURRENT_PLAN_PROPOSAL_APPROVAL_AND_REVOCATION",
                "CORE_APPROVAL_AND_PROPOSAL_EXPIRY",
                "CORE_P3_SOURCE_EVENT_PROVENANCE",
                "P1_TYPED_IDENTITY_CHANNEL_CUSTOMER_BINDING_AND_VERIFICATION_EVIDENCE",
                "P4_RECIPIENT_CONSENT_CURRENTNESS_AND_REVOCATION",
            ))

    def revalidate_draft(self, db: Session, context: RequestContext,
                         reference: RecoveryCommunicationReference, terms: CommitmentTerms,
                         *, communication_id: str, action: str) -> RequestAuthorization | None:
        self.check_availability()


class RuntimeReviewAuthority:
    """Core policy authorize() does not define the P4 review actions; do not call it.

    In that policy, an unknown action returns normally. That is not permission.
    Demo actor IDs and previously saved reviews cannot prove current membership.
    """

    def check_availability(self) -> NoReturn:
        _unavailable("REVIEW_AUTHORITY_UNAVAILABLE",
            "Authenticated manager review policy and reviewer revocation checks are unavailable", (
                "CORE_AUTHENTICATED_ACTOR_AND_TENANT_MEMBERSHIP",
                "CORE_READ_REVIEW_APPROVE_DRAFT_REJECT_DRAFT_ACTION_POLICY",
                "CORE_ORIGINAL_REVIEWER_AUTHORIZATION_CURRENTNESS_AND_REVOCATION_EVIDENCE",
            ))

    def authorize_review(self, db: Session, context: RequestContext, *,
                         communication_id: str, draft_id: str, action: ReviewAction,
                         existing_review: DraftReviewDecision | None) -> ReviewAuthorization | None:
        self.check_availability()
