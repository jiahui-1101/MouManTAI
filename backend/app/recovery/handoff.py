"""P3 proposal/communication handoff and P4 confirmation outcome contracts.

This module prepares handoffs only. It does not send customer messages, mutate a
Commitment, or claim that P4/P5 integrations are connected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Protocol

from pydantic import ConfigDict, Field

from app.core.errors import DomainError
from app.core.schemas import ApprovalState, CommitmentTerms, ContractModel, OffsetAwareDatetime

from .eventing import (
    CommunicationRequestedPayload,
    EventPublicationReceipt,
    RecoveryEventCoordinator,
    RecoveryEventType,
)
from .models import (
    ApprovalDecision,
    ApprovalDecisionState,
    RecoveryCase,
    RecoveryPlanVersion,
)


class ProposalHandoffStatus(StrEnum):
    CREATED = "CREATED"
    INTEGRATION_PENDING = "INTEGRATION_PENDING"


class ProposalHandoffCommand(ContractModel):
    """Command for P5; confirmed terms are supplied as an invariant, not a mutation."""

    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    expected_commitment_version: int = Field(ge=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    snapshot_version: int = Field(ge=1)
    confirmed_terms: CommitmentTerms
    revised_terms: CommitmentTerms
    reason: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None


class ProposalHandoffResult(ContractModel):
    model_config = ConfigDict(frozen=True)

    status: ProposalHandoffStatus
    tenant_id: str
    commitment_id: str
    proposal_id: str | None = None
    proposal_version: int | None = Field(default=None, ge=1)
    commitment_version: int | None = Field(default=None, ge=1)
    confirmed_terms_preserved: bool = False
    detail_code: str | None = None


class P5VersionedProposalPort(Protocol):
    """Must be implemented by P5 with transactional, versioned proposal storage.

    Creating an offer must not replace authoritative confirmed Commitment terms.
    """

    def create_recovery_proposal(self, command: ProposalHandoffCommand) -> ProposalHandoffResult: ...


class UnavailableP5ProposalPort:
    def create_recovery_proposal(self, command: ProposalHandoffCommand) -> ProposalHandoffResult:
        return ProposalHandoffResult(
            status=ProposalHandoffStatus.INTEGRATION_PENDING,
            tenant_id=command.tenant_id,
            commitment_id=command.commitment_id,
            detail_code="P5_VERSIONED_PROPOSAL_BOUNDARY_UNAVAILABLE",
        )


class CommunicationHandoffResult(ContractModel):
    model_config = ConfigDict(frozen=True)

    proposal: ProposalHandoffResult
    communication_event: EventPublicationReceipt | None = None
    communication_request_id: str | None = None
    status: ProposalHandoffStatus


class RecoveryCommunicationHandoff:
    def __init__(
        self,
        *,
        proposal_port: P5VersionedProposalPort | None = None,
        events: RecoveryEventCoordinator | None = None,
    ) -> None:
        self.proposal_port = proposal_port or UnavailableP5ProposalPort()
        self.events = events or RecoveryEventCoordinator()

    @staticmethod
    def _revised_terms(plan: RecoveryPlanVersion, case: RecoveryCase) -> CommitmentTerms:
        if not plan.customer_confirmation_required:
            raise DomainError("CUSTOMER_CONFIRMATION_NOT_REQUIRED", "Plan does not revise customer terms", status_code=409)
        action = next((item for item in plan.actions if item.type == "CREATE_DELIVERY_CHANGE_PROPOSAL"), None)
        if action is None:
            raise DomainError("UNSUPPORTED_PROPOSAL_ACTION", "Plan has no allowlisted customer-term proposal action", status_code=422)
        try:
            quantity = action.parameters["partial_quantity"]
            deadline = action.parameters["new_deadline"]
            terms = case.commitment.terms.model_dump(mode="python")
            terms.update({"quantity": quantity, "deadline": deadline})
            return CommitmentTerms.model_validate(terms)
        except (KeyError, TypeError, ValueError) as exc:
            raise DomainError("INVALID_PROPOSAL_TERMS", "Plan proposal terms are invalid", status_code=422) from exc

    def prepare(
        self,
        *,
        case: RecoveryCase,
        plan: RecoveryPlanVersion,
        approval: ApprovalDecision,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> CommunicationHandoffResult:
        if (plan.tenant_id, plan.commitment_id, plan.recovery_case_id) != (
            case.tenant_id, case.commitment_id, case.case_id
        ):
            raise DomainError("RECOVERY_SCOPE_MISMATCH", "Plan is not part of this tenant commitment case", status_code=409)
        stored_approval = next((item for item in case.approval_decisions
                                if item.approval_id == approval.approval_id), None)
        if (plan.approval_state != ApprovalState.APPROVED or stored_approval is None
                or stored_approval.model_dump(mode="json") != approval.model_dump(mode="json")):
            raise DomainError("PERSISTED_APPROVAL_REQUIRED", "A stored approval for the current plan is required", status_code=409)
        if (approval.tenant_id, approval.commitment_id, approval.recovery_case_id,
            approval.plan_id, approval.plan_version, approval.commitment_version,
            approval.snapshot_version, approval.decision) != (
            case.tenant_id, case.commitment_id, case.case_id, plan.plan_id, plan.plan_version,
            case.commitment_version, plan.snapshot_version, ApprovalDecisionState.APPROVED
        ):
            raise DomainError("APPROVAL_BINDING_MISMATCH", "Approval does not cover this current plan and case", status_code=409)
        if approval.expires_at is None or approval.expires_at <= datetime.now(UTC):
            raise DomainError("APPROVAL_EXPIRED", "Plan approval is expired", status_code=409)
        action_types = sorted({action.type for action in plan.actions})
        if sorted(set(approval.action_scope)) != action_types:
            raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval does not cover all plan actions", status_code=409)
        if approval.approved_cost_limit is None or approval.approved_cost_limit < plan.estimated_extra_cost:
            raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Plan exceeds the approved cost limit", status_code=409)

        command = ProposalHandoffCommand(
            tenant_id=case.tenant_id,
            commitment_id=case.commitment_id,
            expected_commitment_version=case.commitment_version,
            recovery_case_id=case.case_id,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            snapshot_version=plan.snapshot_version,
            confirmed_terms=case.commitment.terms,
            revised_terms=self._revised_terms(plan, case),
            reason=f"Approved recovery plan {plan.plan_id} v{plan.plan_version}",
            evidence_refs=tuple(dict.fromkeys([*plan.evidence_refs, *approval.evidence_refs])),
            correlation_id=correlation_id,
            causation_id=causation_id or approval.approval_id,
        )
        proposal = self.proposal_port.create_recovery_proposal(command)
        if proposal.status != ProposalHandoffStatus.CREATED or not proposal.proposal_id or not proposal.proposal_version:
            return CommunicationHandoffResult(proposal=proposal, status=ProposalHandoffStatus.INTEGRATION_PENDING)
        if (proposal.tenant_id, proposal.commitment_id) != (case.tenant_id, case.commitment_id):
            raise DomainError("PROPOSAL_SCOPE_MISMATCH", "P5 proposal response has mismatched tenant/commitment", status_code=409)
        if not proposal.confirmed_terms_preserved or proposal.commitment_version != case.commitment_version:
            raise DomainError("CONFIRMED_TERMS_NOT_PRESERVED", "P5 did not confirm current terms remain unchanged", status_code=409)

        request_id = f"commreq_{proposal.proposal_id}_v{proposal.proposal_version}"
        event = self.events.prepare(
            event_type=RecoveryEventType.COMMUNICATION_REQUESTED,
            tenant_id=case.tenant_id,
            commitment_id=case.commitment_id,
            commitment_version=case.commitment_version,
            recovery_case_id=case.case_id,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            snapshot_version=plan.snapshot_version,
            correlation_id=correlation_id,
            causation_id=causation_id or proposal.proposal_id,
            evidence_refs=tuple(dict.fromkeys([*plan.evidence_refs, *approval.evidence_refs])),
            payload=CommunicationRequestedPayload(
                communication_request_id=request_id,
                proposal_id=proposal.proposal_id,
                proposal_version=proposal.proposal_version,
            ),
        )
        receipt = self.events.publish(event)
        return CommunicationHandoffResult(
            proposal=proposal,
            communication_event=receipt,
            communication_request_id=request_id,
            status=ProposalHandoffStatus.CREATED,
        )


class ConfirmationOutcomeType(StrEnum):
    ACCEPTED = "confirmation.accepted"
    REJECTED = "confirmation.rejected"
    COUNTEROFFER_RECEIVED = "confirmation.counteroffer_received"


class VerifiedConfirmationOutcome(ContractModel):
    """P4 outbox-consumer delivery; never construct from a public client request."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1)
    event_type: ConfirmationOutcomeType
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    occurred_at: OffsetAwareDatetime
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class VersionedProposalSnapshot(ContractModel):
    tenant_id: str
    commitment_id: str
    commitment_version: int = Field(ge=1)
    proposal_id: str
    proposal_version: int = Field(ge=1)
    status: str
    accepted_terms_match: bool = False


class P5ProposalReader(Protocol):
    def get_proposal(self, tenant_id: str, commitment_id: str, proposal_id: str) -> VersionedProposalSnapshot: ...


class RecoveryResumePrecondition(Protocol):
    def validate(self, outcome: VerifiedConfirmationOutcome, proposal: VersionedProposalSnapshot) -> bool: ...


class RecoveryWorkflowResumer(Protocol):
    def resume(self, outcome: VerifiedConfirmationOutcome) -> None: ...


class RecoveryPlanInvalidator(Protocol):
    def invalidate(self, outcome: VerifiedConfirmationOutcome) -> None: ...


class ConfirmationDisposition(StrEnum):
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    RESUMED = "RESUMED"
    INVALIDATED_REPLAN_REQUIRED = "INVALIDATED_REPLAN_REQUIRED"
    INTEGRATION_PENDING = "INTEGRATION_PENDING"


class ConfirmationOutcomeResult(ContractModel):
    event_id: str
    disposition: ConfirmationDisposition
    detail_code: str | None = None


class P4ConfirmationOutcomeHandler:
    """Idempotent in-process consumer; durable cursor/outbox processing is pending."""

    def __init__(self, *, proposal_reader: P5ProposalReader | None = None,
                 precondition: RecoveryResumePrecondition | None = None,
                 resumer: RecoveryWorkflowResumer | None = None,
                 invalidator: RecoveryPlanInvalidator | None = None) -> None:
        self.proposal_reader = proposal_reader
        self.precondition = precondition
        self.resumer = resumer
        self.invalidator = invalidator
        self._processed: dict[tuple[str, str], ConfirmationOutcomeResult] = {}
        self._latest: dict[tuple[str, str, str], tuple[int, datetime]] = {}
        self._lock = RLock()

    def handle(self, outcome: VerifiedConfirmationOutcome) -> ConfirmationOutcomeResult:
        key = (outcome.tenant_id, outcome.event_id)
        proposal_key = (outcome.tenant_id, outcome.commitment_id, outcome.proposal_id)
        with self._lock:
            if key in self._processed:
                return ConfirmationOutcomeResult(event_id=outcome.event_id, disposition=ConfirmationDisposition.DUPLICATE)
            latest = self._latest.get(proposal_key)
            if latest and (outcome.proposal_version < latest[0] or
                           (outcome.proposal_version == latest[0] and outcome.occurred_at <= latest[1])):
                result = ConfirmationOutcomeResult(event_id=outcome.event_id, disposition=ConfirmationDisposition.OUT_OF_ORDER)
                self._processed[key] = result
                return result
            if outcome.event_type == ConfirmationOutcomeType.ACCEPTED:
                if not self.proposal_reader or not self.precondition or not self.resumer:
                    result = ConfirmationOutcomeResult(event_id=outcome.event_id,
                                                       disposition=ConfirmationDisposition.INTEGRATION_PENDING,
                                                       detail_code="P5_P4_RESUME_DEPENDENCIES_UNAVAILABLE")
                else:
                    proposal = self.proposal_reader.get_proposal(
                        outcome.tenant_id, outcome.commitment_id, outcome.proposal_id
                    )
                    expected = (outcome.tenant_id, outcome.commitment_id, outcome.commitment_version,
                                outcome.proposal_id, outcome.proposal_version, "ACCEPTED")
                    actual = (proposal.tenant_id, proposal.commitment_id, proposal.commitment_version,
                              proposal.proposal_id, proposal.proposal_version, proposal.status)
                    if actual != expected or not proposal.accepted_terms_match:
                        result = ConfirmationOutcomeResult(event_id=outcome.event_id,
                                                           disposition=ConfirmationDisposition.INTEGRATION_PENDING,
                                                           detail_code="PROPOSAL_VERSION_OR_TERMS_MISMATCH")
                    elif not self.precondition.validate(outcome, proposal):
                        result = ConfirmationOutcomeResult(event_id=outcome.event_id,
                                                           disposition=ConfirmationDisposition.INTEGRATION_PENDING,
                                                           detail_code="RECOVERY_PRECONDITION_FAILED")
                    else:
                        self.resumer.resume(outcome)
                        result = ConfirmationOutcomeResult(event_id=outcome.event_id,
                                                           disposition=ConfirmationDisposition.RESUMED)
            else:
                if self.invalidator is None:
                    result = ConfirmationOutcomeResult(
                        event_id=outcome.event_id,
                        disposition=ConfirmationDisposition.INTEGRATION_PENDING,
                        detail_code="P3_INVALIDATION_HANDLER_UNAVAILABLE",
                    )
                else:
                    self.invalidator.invalidate(outcome)
                    result = ConfirmationOutcomeResult(
                        event_id=outcome.event_id,
                        disposition=ConfirmationDisposition.INVALIDATED_REPLAN_REQUIRED,
                        detail_code="CUSTOMER_REJECTED_OR_COUNTEROFFERED",
                    )
            # Pending integration outcomes are retryable and must not advance the
            # in-process cursor; only completed handling is deduplicated as done.
            if result.disposition != ConfirmationDisposition.INTEGRATION_PENDING:
                self._latest[proposal_key] = (outcome.proposal_version, outcome.occurred_at)
                self._processed[key] = result
            return result


class PlannerRecoveryInvalidator:
    """Binds P4 outcomes to P3's in-memory invalidation and replan event logic."""

    def __init__(self, planner: object) -> None:
        self.planner = planner

    def invalidate(self, outcome: VerifiedConfirmationOutcome) -> None:
        self.planner.invalidate_for_customer_response(
            tenant_id=outcome.tenant_id,
            commitment_id=outcome.commitment_id,
            plan_id=outcome.plan_id,
            plan_version=outcome.plan_version,
            commitment_version=outcome.commitment_version,
            correlation_id=f"p4:{outcome.event_id}",
            causation_id=outcome.event_id,
            evidence_refs=list(outcome.evidence_refs),
            reason=outcome.event_type.value,
        )
