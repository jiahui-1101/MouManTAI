"""Explicit disposable-PG runtime, not production identity or approval fixtures.

Production still needs P5 authenticated principals and a P1 trusted Directory.
This adapter reads real P3/P5 records; it never creates an approval or identity.
"""
import os
from secrets import compare_digest
from datetime import timedelta

from sqlalchemy import select
from app.core.dependencies import ACTOR_ROLES
from app.core.manager_approval import ManagerApprovalRecord
from app.core.models import AuditEventRecord, OutboxEventRecord
from app.feasibility.persisted_sources import read_snapshot
from app.recovery.durable_plans import RecoveryPlanRecord
from app.recovery.persistence import RecoveryCaseRecord
from .demo_policy import SyntheticScope, deny
from .preferences import PreferenceService, PURPOSE, utc, stored_time
from .models import MessageDraftRecord, RecipientPreferenceRecord
from .schemas import RequestAuthorization, ReviewAuthorization, SendAuthorization
from .followup_schemas import ReminderAuthorization
from .service import CommunicationRequestService
from .schemas import CreateCommunicationRequest
from .templates import fingerprint


def enabled():
    return os.getenv("P4_TRUSTED_ISOLATED") == "1"


class IsolatedPrincipal:
    def __init__(self, db, key=None, *, processor_key=None, worker_key=None):
        self.db, self.key = db, key
        self.processor_key, self.worker_key = processor_key, worker_key
        self.scope = SyntheticScope.from_environment()

    def require(self, context, action):
        from .isolated_app import private_inbound_surface
        if not private_inbound_surface.get() and self.worker_key is None:
            deny("PRIVATE_INBOUND_GATEWAY_REQUIRED", "Use the isolated private evidence application entrypoint", 503)
        url = self.db.get_bind().engine.url
        if (not enabled() or os.getenv("MOUMANTAI_ISOLATED_E2E") != "1" or not self.scope.enabled or
            not url.drivername.startswith("postgresql") or not (url.database or "").startswith("p4_test_")):
            deny("TRUSTED_ISOLATED_RUNTIME_UNAVAILABLE", "Explicit disposable PostgreSQL runtime is required", 503)
        if context.tenant_id not in self.scope.tenants or ACTOR_ROLES.get(context.actor_id) != context.actor_role:
            deny("TRUSTED_PRINCIPAL_FORBIDDEN", "Principal is outside server scope", 403)
        if context.actor_role in {"OWNER", "MANAGER"}:
            secret = os.getenv("MOUMANTAI_ISOLATED_E2E_KEY", "")
            valid = (context.actor_id == os.getenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID") and
                     len(secret) >= 32 and self.key is not None and compare_digest(secret, self.key))
            permitted = {"CREATE_COMMUNICATION", "PREPARE_DRAFT", "READ_DRAFT", "READ_REVIEW", "APPROVE_DRAFT",
                "REJECT_DRAFT", "SEND_MESSAGE", "CREATE_CONFIRMATION", "READ_CONFIRMATION", "REVOKE_CONFIRMATION",
                "READ_FOLLOWUP", "SCHEDULE_FOLLOWUP", "CANCEL_FOLLOWUP", "DISPATCH_REMINDER"}
            if valid and action in permitted:
                return "MANAGER"
        if context.actor_id == "service_core" and context.actor_role == "SERVICE":
            read = {"READ_DRAFT", "READ_REVIEW", "READ_CONFIRMATION", "READ_FOLLOWUP"}
            for supplied, name, actions, kind in [
                (self.processor_key, "P4_ISOLATED_PROCESSOR_KEY", read | {"PROCESS_CONFIRMATION_RESPONSE"}, "PROCESSOR"),
                (self.worker_key, "P4_ISOLATED_WORKER_KEY", read | {"DISPATCH_REMINDER", "SEND_MESSAGE"}, "WORKER"),
            ]:
                secret = os.getenv(name, "")
                if len(secret) >= 32 and supplied and action in actions and compare_digest(secret, supplied):
                    # Sharing the manager key must never turn headers into a processor.
                    other = "P4_ISOLATED_WORKER_KEY" if kind == "PROCESSOR" else "P4_ISOLATED_PROCESSOR_KEY"
                    if secret in {os.getenv("MOUMANTAI_ISOLATED_E2E_KEY"), os.getenv(other)}:
                        deny("ISOLATED_KEYS_NOT_SEPARATED", "Service credentials must be distinct", 503)
                    return kind
        deny("TRUSTED_PRINCIPAL_FORBIDDEN", "Authenticated server action permission is required", 403)


class PersistedCommunicationAuthority:
    def __init__(self, principal, directory):
        self.principal, self.directory = principal, directory

    def _approval(self, db, context, ref, terms):
        now = utc()
        # Caller already holds the Core lock through read_current_basis.
        plan = db.get(RecoveryPlanRecord, (context.tenant_id, ref.plan_id, ref.plan_version), populate_existing=True)
        if plan is None or plan.commitment_id != ref.commitment_id:
            deny("RECOVERY_PLAN_NOT_FOUND", "Exact persisted plan is required", 409)
        # PR #34 is not merged on this baseline. Never derive successor
        # proposal identity from a plan ID or naming convention. V1 legacy
        # payloads may omit both fields; any explicit binding must be complete.
        payload = plan.payload if isinstance(plan.payload, dict) else {}
        has_binding = any(key in payload for key in ("proposal_id", "proposal_version"))
        if plan.plan_version > 1 or has_binding:
            proposal_id = payload.get("proposal_id")
            proposal_version = payload.get("proposal_version")
            if (not isinstance(proposal_id, str) or not proposal_id.strip()
                or type(proposal_version) is not int or proposal_version < 1
                or (proposal_id, proposal_version) != (ref.proposal_id, ref.proposal_version)):
                deny("PROPOSAL_PLAN_IDENTITY_CONFLICT",
                     "Exact persisted proposal identity is required; PR #34 integration is pending", 409)
        latest = db.scalar(select(RecoveryPlanRecord.plan_version).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id, RecoveryPlanRecord.plan_id == ref.plan_id,
        ).order_by(RecoveryPlanRecord.plan_version.desc()))
        case = db.get(RecoveryCaseRecord, (context.tenant_id, plan.case_id), populate_existing=True)
        snapshot = read_snapshot(db, context.tenant_id)
        if (latest != ref.plan_version or plan.status != "PENDING_APPROVAL" or case is None or
            case.status in {"COMPLETED", "NEEDS_REPLAN", "NO_SAFE_PLAN"} or
            (plan.snapshot_id, plan.snapshot_version) != (snapshot.operational.snapshot_id, snapshot.operational.snapshot_version)):
            deny("RECOVERY_BASIS_CHANGED", "Recovery context or operational snapshot changed", 409)
        decisions = db.scalars(select(ManagerApprovalRecord).where(
            ManagerApprovalRecord.tenant_id == context.tenant_id, ManagerApprovalRecord.plan_id == ref.plan_id,
            ManagerApprovalRecord.plan_version == ref.plan_version,
        ).order_by(ManagerApprovalRecord.decided_at, ManagerApprovalRecord.approval_id)
          .execution_options(populate_existing=True)).all()
        source = db.get(OutboxEventRecord, ref.source_event_id, populate_existing=True)
        if not decisions or source is None:
            deny("APPROVAL_NOT_ACTIVE", "Durable approval/source is missing", 409)
        approval = decisions[-1]
        if approval.decision != "APPROVED" or approval.expires_at is None or stored_time(approval.expires_at) <= now:
            deny("APPROVAL_NOT_ACTIVE", "Approval expired or was revoked", 409)
        audit = db.get(AuditEventRecord, approval.audit_id, populate_existing=True)
        if ((approval.commitment_id, approval.proposal_id, approval.proposal_version, approval.snapshot_id,
             approval.snapshot_version, approval.commitment_version) !=
            (ref.commitment_id, ref.proposal_id, ref.proposal_version, plan.snapshot_id, plan.snapshot_version, plan.core_commitment_version)
            or "CREATE_DELIVERY_CHANGE_PROPOSAL" not in approval.action_scope
            or approval.approved_terms != terms.model_dump(mode="json")
            or source.tenant_id != context.tenant_id or source.event_type != "recovery.communication_requested"
            or source.causation_id != approval.approval_id or source.payload.get("approval_id") != approval.approval_id
            or source.payload.get("approval_evidence_ref") != approval.audit_id
            or source.payload.get("approved_terms") != approval.approved_terms
            or audit is None or audit.tenant_id != context.tenant_id or audit.actor_id != approval.actor_id
            or audit.new_state.get("approval_id") != approval.approval_id or approval.actor_role != "MANAGER"
            or ACTOR_ROLES.get(approval.actor_id) != "MANAGER"):
            deny("APPROVAL_SCOPE_CONFLICT", "Approval/proposal/terms/audit binding differs", 409)
        return approval

    def _grant(self, db, context, ref, terms, action):
        self.principal.require(context, action)
        current = CommunicationRequestService(db).read_current_basis(context,
            CreateCommunicationRequest(source_event_id=ref.source_event_id), utc())
        if current.reference != ref or current.terms != terms:
            deny("AUTHORIZATION_SCOPE_MISMATCH", "Current source/terms differ", 409)
        approval = self._approval(db, context, ref, terms)
        choices = db.scalars(select(RecipientPreferenceRecord).where(
            RecipientPreferenceRecord.tenant_id == context.tenant_id,
            RecipientPreferenceRecord.customer_id == current.customer_id,
            RecipientPreferenceRecord.consent_purpose == PURPOSE,
            RecipientPreferenceRecord.consent_status == "OPTED_IN",
        )).all()
        if len(choices) != 1:
            deny("RECIPIENT_CHANNEL_UNRESOLVED", "One independently permitted channel is required", 409)
        candidate = choices[0]
        pref = PreferenceService(db, IsolatedPreferenceScope(self.principal), self.directory)
        # The service principal is authenticated above; existing preference scope
        # only knows human roles. Read with a dedicated checked port below.
        permission = pref.check(context, current.customer_id, candidate.channel, candidate.recipient_identity_id)
        return RequestAuthorization(reference=ref, approved_terms=terms,
            approval_evidence_refs=[approval.audit_id], approval_expires_at=min(stored_time(approval.expires_at), permission.consent_expires_at),
            proposal_expires_at=stored_time(approval.expires_at), recipient_identity_id=permission.recipient_identity_id,
            recipient_customer_id=current.customer_id, recipient_evidence_refs=["p1:typed-verified-contact"],
            channel=candidate.channel, channel_evidence_refs=[permission.last_audit_id, permission.consent_evidence_ref])

    def authorize_request(self, db, context, reference, terms):
        return self._grant(db, context, reference, terms, "CREATE_COMMUNICATION")

    def revalidate_draft(self, db, context, reference, terms, *, communication_id, action):
        return self._grant(db, context, reference, terms, action)

    def authorize_review(self, db, context, *, communication_id, draft_id, action, existing_review):
        self.principal.require(context, action)
        record = db.get(MessageDraftRecord, (context.tenant_id, draft_id))
        if record is None or record.communication_id != communication_id:
            deny("DRAFT_NOT_FOUND", "Draft not in current scope", 404)
        from .schemas import MessageDraftView
        draft = MessageDraftView.model_validate(record.snapshot)
        grant = self._grant(db, context, draft.reference, draft.approved_terms, "READ_DRAFT")
        valid = existing_review is not None and (
            existing_review.reviewer_id == os.getenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID") and
            ACTOR_ROLES.get(existing_review.reviewer_id) == existing_review.reviewer_role == "MANAGER")
        return ReviewAuthorization(tenant_id=context.tenant_id, actor_id=context.actor_id, actor_role=context.actor_role,
            communication_id=communication_id, draft_id=draft_id, action=action,
            evidence_refs=grant.approval_evidence_refs, expires_at=grant.approval_expires_at,
            allowed_actions=["APPROVE_DRAFT", "REJECT_DRAFT"] if context.actor_role == "MANAGER" else [],
            existing_review_status="VALID" if valid else "REVOKED" if existing_review else "UNKNOWN",
            existing_review_evidence_refs=grant.approval_evidence_refs if existing_review else [])

    def authorize_send(self, db, context, *, draft, review):
        self.principal.require(context, "SEND_MESSAGE")
        grant = self._grant(db, context, draft.reference, draft.approved_terms, "READ_DRAFT")
        return SendAuthorization(tenant_id=context.tenant_id, actor_id=context.actor_id, actor_role=context.actor_role,
            communication_id=draft.communication_id, draft_id=draft.draft_id, review_id=review.review_id,
            content_hash=draft.content_hash, validation_hash=draft.validation_hash, action="SEND_MESSAGE",
            evidence_refs=grant.approval_evidence_refs + grant.channel_evidence_refs,
            expires_at=grant.approval_expires_at)


class IsolatedPreferenceScope:
    """Delegate principal checks without changing P4's existing consent validation."""
    def __init__(self, principal): self.principal = principal
    def require(self, context, *, manager=False):
        self.principal.require(context, "SCHEDULE_FOLLOWUP" if manager else "READ_DRAFT")


class IsolatedConfirmationAccess:
    def __init__(self, principal): self.principal = principal
    def authorize(self, context, action):
        self.principal.require(context, action)
        if action == "CREATE_CONFIRMATION":
            deny("CHALLENGE_ISSUED_BY_OUTBOUND", "Bound challenges are issued atomically by authorized sending", 409)


class IsolatedReminderAuthority:
    def __init__(self, principal): self.principal = principal
    def authorize(self, db, context, *, action, confirmation_id, policy_digest, now):
        self.principal.require(context, action)
        if action != "READ_FOLLOWUP" and os.getenv("P4_ISOLATED_REMINDER_POLICY_DIGEST") != policy_digest:
            deny("REMINDER_POLICY_NOT_AUTHORIZED", "Server has not authorized this exact SLA policy", 403)
        if action == "DISPATCH_REMINDER" and context.actor_role == "SERVICE":
            records = db.scalars(select(AuditEventRecord).where(AuditEventRecord.tenant_id == context.tenant_id,
                AuditEventRecord.event_type == "communication.followup_scheduled")).all()
            if not any(record.new_state.get("confirmation_id") == confirmation_id and
                record.actor_id == os.getenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID") and
                "isolated:reminder-policy:" + policy_digest in record.evidence_refs for record in records):
                deny("REMINDER_POLICY_EVIDENCE_MISSING", "Persisted manager schedule authorization is required", 403)
        return ReminderAuthorization(tenant_id=context.tenant_id, actor_id=context.actor_id, action=action,
            confirmation_id=confirmation_id, policy_digest=policy_digest,
            evidence_refs=["isolated:reminder-policy:" + (policy_digest or "read")], expires_at=now + timedelta(minutes=5))
