"""Explicit runtime authority boundaries for the CURRENT upstream capabilities.

Core exposes demo headers, current proposal facts and generic audit/outbox rows.
It does NOT expose authenticated membership, P4 action grants or a persisted,
revocable approval/expiry contract. P1's default directory is synthetic and lacks
typed verified outbound identity/consent. No production adapter can honestly
issue a positive grant from those sources. These boundaries report the missing
capabilities and reject; they never silently use test fixtures or demo policies.

Current Core facts are independently read by CommunicationRequestService's
read_current_basis, shared by intake and draft revalidation. Such facts are NOT
permission. Implement a positive adapter only after upstream authority exists;
changing an environment flag or supplying an actor_role cannot enable one here.
"""

from typing import NoReturn
from datetime import datetime, timezone
import os

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import CommitmentTerms
from app.core.manager_approval import ManagerApprovalRecord, trusted_isolated_manager
from app.core.models import OutboxEventRecord
from app.recovery.durable_plans import RecoveryPlanRecord
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


class IsolatedRecoveryRequestAuthority:
    """Server-keyed synthetic P3 approval reader for P4 intake only.

    It deliberately supplies no recipient/channel grant; P4 persists a BLOCKED
    request until independent verified P1 identity and consent are available.
    """

    def __init__(self, key: str | None) -> None:
        self.key = key

    def check_availability(self) -> None:
        if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
            RuntimeRequestAuthority().check_availability()

    def authorize_request(self, db: Session, context: RequestContext,
                          reference: RecoveryCommunicationReference,
                          terms: CommitmentTerms) -> RequestAuthorization | None:
        trusted_isolated_manager(context, self.key)
        source = db.get(OutboxEventRecord, reference.source_event_id)
        if source is None or source.tenant_id != context.tenant_id or source.event_type != "recovery.communication_requested":
            raise DomainError("COMMUNICATION_SOURCE_UNVERIFIED", "Exact P3 source event is required", status_code=409)
        plan = db.get(RecoveryPlanRecord, (context.tenant_id, reference.plan_id, reference.plan_version))
        if plan is None or plan.commitment_id != reference.commitment_id:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Exact approved plan is required", status_code=409)
        approval_id = source.payload.get("approval_id")
        decisions = db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id,
            ManagerApprovalRecord.plan_id == plan.plan_id,
            ManagerApprovalRecord.plan_version == plan.plan_version,
        ).order_by(ManagerApprovalRecord.decided_at, ManagerApprovalRecord.approval_id)).all()
        if not decisions or decisions[-1].decision != "APPROVED" or decisions[-1].approval_id != approval_id:
            raise DomainError("APPROVAL_NOT_ACTIVE", "Current Manager approval is absent or revoked", status_code=409)
        approval = decisions[-1]
        expires = approval.expires_at
        if expires is None:
            raise DomainError("APPROVAL_EXPIRED", "Manager approval has no expiry", status_code=409)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise DomainError("APPROVAL_EXPIRED", "Manager approval expired", status_code=409)
        if (approval.commitment_id, approval.snapshot_id, approval.snapshot_version,
            approval.commitment_version) != (
            plan.commitment_id, plan.snapshot_id, plan.snapshot_version,
            plan.core_commitment_version,
        ) or "CREATE_DELIVERY_CHANGE_PROPOSAL" not in approval.action_scope:
            raise DomainError("APPROVAL_SCOPE_CONFLICT", "Approval does not cover this proposal", status_code=409)
        if (approval.approved_terms != terms.model_dump(mode="json")
            or source.causation_id != approval.approval_id
            or source.payload.get("approval_evidence_ref") != approval.audit_id
            or source.payload.get("approved_terms") != approval.approved_terms):
            raise DomainError("APPROVED_TERMS_MISMATCH", "Source terms or evidence differ", status_code=409)
        return RequestAuthorization(
            reference=reference, approved_terms=terms,
            approval_evidence_refs=[approval.audit_id], approval_expires_at=expires,
            proposal_expires_at=expires,
        )


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
                "P1_OUTBOUND_CHANNEL_CONSENT_CURRENTNESS_AND_REVOCATION",
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
