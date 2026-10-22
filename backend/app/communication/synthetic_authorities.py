"""Synthetic-only adapters. Missing producer contracts remain hard blockers.

There is deliberately NO grant constructor for Core recovery approval here.
Generic audit JSON and plan:... strings do not establish provenance or expiry.
"""
from datetime import datetime, timedelta, timezone

from app.core.dependencies import ACTOR_ROLES
from .demo_policy import deny
from .preferences import PreferenceService
from .schemas import CreateCommunicationRequest, ReviewAuthorization, SendAuthorization
from .service import CommunicationRequestService


class SyntheticRequestAuthority:
    def __init__(self, scope):
        self.scope = scope

    def authorize_request(self, db, context, reference, terms):
        self.scope.require(context, manager=True)
        basis = CommunicationRequestService(db).read_current_basis(context,
            CreateCommunicationRequest(source_event_id=reference.source_event_id), datetime.now(timezone.utc))
        if basis.reference != reference:
            deny("AUTHORIZATION_SCOPE_MISMATCH", "Current source/Core versions do not match", 409)
        if basis.terms != terms:
            deny("APPROVED_TERMS_MISMATCH", "Current Core proposal terms differ", 409)
        if f"plan:{reference.plan_id}:v{reference.plan_version}" not in basis.proposal_evidence_refs:
            deny("CORE_PLAN_BINDING_UNAVAILABLE", "Core proposal has no exact persisted plan binding", 503)
        # Current ProposalCreateRequest/Record have no approved plan binding,
        # approval expiry/revocation/currentness contract. P3 has no producer.
        # Even a matching text marker or hand-inserted audit cannot close this gap.
        deny("CORE_APPROVAL_PRODUCER_UNAVAILABLE", "Durable current plan approval provenance and expiry contract are not implemented", 503)


class ConsentBoundDraftAuthority:
    """Compose trusted upstream authority with P4's current durable consent.

    This cannot grant upstream authority. Fixture upstreams are injected in tests
    only. The runtime upstream below still rejects the absent Core contract.
    """
    def __init__(self, upstream, scope, directory):
        self.upstream, self.scope, self.directory = upstream, scope, directory

    def revalidate_draft(self, db, context, reference, terms, *, communication_id, action):
        self.scope.require(context)
        grant = self.upstream.revalidate_draft(db, context, reference, terms,
            communication_id=communication_id, action=action)
        if grant is None:
            return None
        preference = PreferenceService(db, self.scope, self.directory).check(context,
            grant.recipient_customer_id, grant.channel, grant.recipient_identity_id)
        refs = [f"consent:{preference.last_audit_id}:v{preference.version}",
                f"policy:{preference.policy_version}", preference.consent_evidence_ref]
        return grant.model_copy(update={"channel_evidence_refs": [*grant.channel_evidence_refs, *refs],
            "approval_expires_at": min(grant.approval_expires_at, preference.consent_expires_at)})


class SyntheticDraftAuthority:
    def __init__(self, scope):
        self.request = SyntheticRequestAuthority(scope)

    def revalidate_draft(self, db, context, reference, terms, *, communication_id, action):
        # No fallback to a previously saved Request/Approval snapshot.
        return self.request.authorize_request(db, context, reference, terms)


class SyntheticReviewAuthority:
    def __init__(self, scope):
        self.scope = scope

    def authorize_review(self, db, context, *, communication_id, draft_id, action, existing_review):
        policy_action = "APPROVE_DRAFT" if action == "READ_REVIEW" else action
        self.scope.authorize(context, policy_action)
        status = "UNKNOWN"
        original_refs = []
        if existing_review:
            current = ACTOR_ROLES.get(existing_review.reviewer_id)
            valid = (existing_review.tenant_id == context.tenant_id and
                existing_review.communication_id == communication_id and existing_review.draft_id == draft_id and
                current == existing_review.reviewer_role and current in {"OWNER", "MANAGER"})
            status = "VALID" if valid else "REVOKED"
            original_refs = [f"synthetic:actor:{existing_review.reviewer_id}:{current or 'REVOKED'}"]
        allowed = [name for name in ("APPROVE_DRAFT", "REJECT_DRAFT") if self._allowed(context, name)]
        return ReviewAuthorization(tenant_id=context.tenant_id, actor_id=context.actor_id, actor_role=context.actor_role,
            communication_id=communication_id, draft_id=draft_id, action=action,
            evidence_refs=[f"synthetic:policy:{policy_action}:{context.actor_id}:{context.actor_role}"],
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15), allowed_actions=allowed,
            existing_review_status=status, existing_review_evidence_refs=original_refs)

    def _allowed(self, context, action):
        from app.core.errors import DomainError
        try:
            self.scope.authorize(context, action)
            return True
        except DomainError:
            return False


class SyntheticSendAuthority:
    def __init__(self, scope):
        self.scope = scope

    def authorize_send(self, db, context, *, draft, review):
        self.scope.authorize(context, "SEND_MESSAGE")
        if (draft.tenant_id != context.tenant_id or review.tenant_id != context.tenant_id or
            review.draft_id != draft.draft_id or review.communication_id != draft.communication_id or
            review.action != "APPROVE_DRAFT" or review.content_hash != draft.content_hash or
            review.validation_hash != draft.validation_hash):
            deny("SEND_AUTHORIZATION_SCOPE_MISMATCH", "Review does not authorize this exact draft", 409)
        role = ACTOR_ROLES.get(review.reviewer_id)
        if role != review.reviewer_role or role not in {"OWNER", "MANAGER"}:
            deny("REVIEW_AUTHORIZATION_REVOKED", "Original reviewer's role is no longer valid")
        return SendAuthorization(tenant_id=context.tenant_id, actor_id=context.actor_id, actor_role=context.actor_role,
            communication_id=draft.communication_id, draft_id=draft.draft_id, review_id=review.review_id,
            content_hash=draft.content_hash, validation_hash=draft.validation_hash, action="SEND_MESSAGE",
            evidence_refs=[f"synthetic:policy:SEND_MESSAGE:{context.actor_id}:{context.actor_role}"],
            expires_at=min(draft.expires_at, review.expires_at, datetime.now(timezone.utc) + timedelta(minutes=5)))
