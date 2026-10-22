"""Portable checks for P2's persisted source boundary; no PostgreSQL claim."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.communication.authority_adapters import IsolatedRecoveryRequestAuthority
from app.communication.schemas import CreateCommunicationRequest
from app.communication.service import CommunicationRequestService
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
from app.core.manager_approval import ManagerApprovalRecord, ManagerApprovalService
from app.core.models import (
    AuditEventRecord,
    CommitmentProposalRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.core.schemas import ProposalCreateRequest
from app.core.service import CommitmentService
from app.feasibility.api_dependencies import require_isolated_e2e_key
from app.feasibility.api_schemas import FeasibilityEvaluateRequest
from app.feasibility.persisted_sources import (
    OperationalSnapshotRecord,
    PersistedEvaluationAuthority,
    PersistedSupplierDelayProcessor,
    SupplierDelayEventRecord,
    read_snapshot,
    stage_snapshot,
)
from app.feasibility.pipeline_fixtures import build_pipeline_example
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.recovery.durable_actions import (
    DurableActionService,
    InternalRecoveryTaskRecord,
    RecoveryActionExecutionRecord,
)
from app.recovery.durable_communication import (
    DurableCommunicationHandoff,
    RequestCommunicationInput,
)
from app.recovery.durable_plans import DurablePlanService, RecoveryPlanRecord
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.worker import configure_isolated_subscribers


def _seed(session: Session):
    snapshot, commitment = build_production_example()
    session.add(CommitmentRecord(
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        order_id=commitment.order_id, customer_id=commitment.customer_id,
        terms=commitment.terms.model_dump(mode="json"),
        agreement_state="CONFIRMED", feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL", recovery_state="NONE", fulfilment_state="NOT_STARTED",
        commitment_version=commitment.commitment_version, evidence_refs=commitment.evidence_refs,
        updated_at=datetime.now(UTC),
    ))
    stage_snapshot(session, snapshot, current=True)
    session.commit()
    context = RequestContext(
        tenant_id=commitment.tenant_id, actor_id="service_p2", actor_role="SERVICE",
        correlation_id="corr_source_test",
    )
    return snapshot, commitment, context


def test_persisted_authority_reads_exact_current_snapshot_and_core_commitment(session: Session) -> None:
    snapshot, commitment, context = _seed(session)
    stored, actual_commitment = PersistedEvaluationAuthority(session).resolve_current(
        context, commitment.commitment_id, commitment.commitment_version,
    )
    assert stored.operational.snapshot_id == snapshot.operational.snapshot_id
    assert stored.operational.snapshot_version == snapshot.operational.snapshot_version
    assert stored.model_dump(mode="json", exclude_computed_fields=True) == snapshot.model_dump(
        mode="json", exclude_computed_fields=True,
    )
    assert actual_commitment.commitment_id == commitment.commitment_id
    assert session.get(OperationalSnapshotRecord, (
        commitment.tenant_id, snapshot.operational.snapshot_version,
    )) is not None


def test_persisted_authority_rejects_tampered_snapshot_and_wrong_tenant(session: Session) -> None:
    snapshot, commitment, context = _seed(session)
    changed = EvaluationSnapshot.model_validate({
        **snapshot.model_dump(mode="json", exclude_computed_fields=True),
        "as_of": "2026-10-23T14:00:00+08:00",
    })
    with pytest.raises(DomainError) as error:
        PersistedEvaluationAuthority(session).resolve(
            context, FeasibilityEvaluateRequest(snapshot=changed, commitment=commitment),
        )
    assert error.value.code == "EVALUATION_INPUT_VERSION_CONFLICT"
    wrong = RequestContext(
        tenant_id="tenant_other", actor_id="service_p2", actor_role="SERVICE",
        correlation_id="corr_wrong_tenant",
    )
    with pytest.raises(DomainError):
        read_snapshot(session, wrong.tenant_id)


def test_snapshot_versions_advance_and_only_one_is_current(session: Session) -> None:
    snapshot, _, _ = _seed(session)
    with pytest.raises(DomainError) as error:
        stage_snapshot(session, snapshot)
    assert error.value.code == "SNAPSHOT_VERSION_CONFLICT"
    changed = snapshot.model_copy(update={
        "operational": snapshot.operational.model_copy(update={
            "snapshot_id": "snap_p2_next", "snapshot_version": 2,
        }),
        "current_snapshot_version": 2,
    })
    stage_snapshot(session, changed)
    session.commit()
    assert read_snapshot(session, snapshot.operational.tenant_id).operational.snapshot_version == 1


def _seed_delay(session: Session, *, mode: str = "complete"):
    inputs = build_pipeline_example(mode=mode)
    for commitment in inputs.before_commitments:
        session.add(CommitmentRecord(
            tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
            order_id=commitment.order_id, customer_id=commitment.customer_id,
            terms=commitment.terms.model_dump(mode="json"),
            agreement_state="CONFIRMED", feasibility_state="NOT_ASSESSED",
            risk_state="NORMAL", recovery_state="NONE", fulfilment_state="NOT_STARTED",
            commitment_version=commitment.commitment_version,
            evidence_refs=commitment.evidence_refs, updated_at=commitment.updated_at,
        ))
    stage_snapshot(session, inputs.before, current=True)
    stage_snapshot(session, inputs.after)
    session.commit()
    context = RequestContext(
        tenant_id=inputs.request.change.tenant_id, actor_id="service_p2", actor_role="SERVICE",
        correlation_id=inputs.request.change.correlation_id,
    )
    return inputs, context


def test_supplier_delay_persists_exact_source_event_impact_and_outbox_once(session: Session) -> None:
    inputs, context = _seed_delay(session)
    processor = PersistedSupplierDelayProcessor()
    first = processor.process(session, context, inputs.request)
    second = processor.process(session, context, inputs.request)
    assert first == second
    assert first.confirmed_impacted_commitment_ids == ("com-001",)
    assert first.verified_unaffected_commitment_ids == ("com-002",)
    assert read_snapshot(session, context.tenant_id).operational.snapshot_id == inputs.after_snapshot_id
    stored = session.get(SupplierDelayEventRecord, (context.tenant_id, inputs.request.change.event_id))
    assert stored is not None
    assert stored.impact_id == first.impact_id
    assert stored.evidence_ref == inputs.request.source_evidence.evidence_ref
    event = session.get(OutboxEventRecord, inputs.request.change.event_id)
    assert event is not None
    assert event.tenant_id == context.tenant_id
    assert event.payload["impact_id"] == first.impact_id
    assert event.payload["after_snapshot_id"] == inputs.after_snapshot_id
    assert session.query(SupplierDelayEventRecord).count() == 1
    assert session.query(OutboxEventRecord).count() == 3
    risk = session.query(OutboxEventRecord).filter_by(event_type="commitment.at_risk").one()
    expected = next(row.after_assessment for row in first.impacts if row.commitment_id == "com-001")
    assert risk.payload["assessment_id"] == expected.assessment_id
    assert risk.payload["snapshot_id"] == inputs.after_snapshot_id
    assert risk.causation_id == inputs.request.change.event_id
    assert risk.commitment_version == expected.commitment_version + 1
    assert session.get(CommitmentRecord, (context.tenant_id, "com-001")).risk_state == "AT_RISK"
    history = AuthoritativeAssessmentHistoryReader().get_assessment(
        session, context, "com-001", expected.assessment_id,
    )
    assert history.commitment_version == expected.commitment_version
    assert history.snapshot_version == inputs.after.operational.snapshot_version


def test_supplier_delay_rejects_wrong_tenant_and_drift_without_partial_writes(session: Session) -> None:
    inputs, context = _seed_delay(session)
    wrong = RequestContext(
        tenant_id="tenant_other", actor_id="service_p2", actor_role="SERVICE",
        correlation_id=context.correlation_id,
    )
    with pytest.raises(DomainError) as error:
        PersistedSupplierDelayProcessor().process(session, wrong, inputs.request)
    assert error.value.code == "TENANT_SCOPE_MISMATCH"
    session.get(OperationalSnapshotRecord, (context.tenant_id, inputs.request.change.before_snapshot_version)).is_current = False
    session.commit()
    with pytest.raises(DomainError) as error:
        PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    assert error.value.code == "SNAPSHOT_DRIFT_CONFLICT"
    assert session.query(SupplierDelayEventRecord).count() == 0
    assert session.query(OutboxEventRecord).count() == 0


def test_missing_production_evidence_stays_unknown_after_persistence(session: Session) -> None:
    inputs, context = _seed_delay(session, mode="material_only")
    impact = PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    assert impact.confirmed_impacted_commitment_ids == ()
    assert impact.unknown_commitment_ids == ("com-001", "com-002")
    assert not any(intent.event.event_type == "commitment.at_risk" for intent in impact.event_intents)


def test_core_assessment_conflict_rolls_back_supplier_event_and_snapshot(session: Session) -> None:
    inputs, context = _seed_delay(session)
    session.get(CommitmentRecord, (context.tenant_id, "com-001")).commitment_version += 1
    session.commit()
    with pytest.raises(DomainError) as error:
        PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    assert error.value.code == "COMMITMENT_VERSION_CONFLICT"
    session.rollback()
    assert read_snapshot(session, context.tenant_id).operational.snapshot_id == inputs.before_snapshot_id
    assert session.query(SupplierDelayEventRecord).count() == 0
    assert session.query(OutboxEventRecord).count() == 0


def test_second_core_assessment_failure_rolls_back_all_staged_records(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, context = _seed_delay(session)
    original = CommitmentService.assess
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second assessment failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CommitmentService, "assess", fail_second)
    with pytest.raises(RuntimeError, match="injected second assessment failure"):
        PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    assert read_snapshot(session, context.tenant_id).operational.snapshot_id == inputs.before_snapshot_id
    assert session.query(SupplierDelayEventRecord).count() == 0
    assert session.query(OutboxEventRecord).count() == 0
    assert session.get(CommitmentRecord, (context.tenant_id, "com-001")).risk_state == "NORMAL"


def test_isolated_mutation_requires_server_owned_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E_KEY", raising=False)
    with pytest.raises(DomainError) as error:
        require_isolated_e2e_key("attacker")
    assert error.value.code == "ISOLATED_E2E_NOT_CONFIGURED"
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "synthetic-private-key-with-at-least-32-chars")
    with pytest.raises(DomainError) as error:
        require_isolated_e2e_key("wrong-key")
    assert error.value.code == "ISOLATED_E2E_UNAUTHORIZED"
    require_isolated_e2e_key("synthetic-private-key-with-at-least-32-chars")


def test_persisted_supplier_event_reaches_p3_through_isolated_dispatcher(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, context = _seed_delay(session)
    impact = PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    expected = next(row.after_assessment for row in impact.impacts if row.commitment_id == "com-001")
    dispatcher = OutboxDispatcher()
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "synthetic-private-key-with-at-least-32-chars")
    configure_isolated_subscribers(dispatcher)
    result = dispatcher.process_outbox_batch(session)
    assert result.failed_count == 0
    risk = session.query(OutboxEventRecord).filter_by(event_type="commitment.at_risk").one()
    assert risk.status == "PUBLISHED"
    trigger = session.get(RecoveryCaseTriggerRecord, (context.tenant_id, risk.event_id))
    assert trigger is not None
    assert trigger.assessment_id == expected.assessment_id
    assert trigger.snapshot_id == inputs.after_snapshot_id
    assert trigger.assessment_provenance_status == "VERIFIED_AUTHORITATIVE"
    assert session.get(RecoveryCaseRecord, (context.tenant_id, trigger.case_id)) is not None
    assert session.get(ProcessedEventRecord, (
        context.tenant_id, risk.event_id, "p3.recovery_trigger.v1",
    )) is not None
    assert dispatcher.process_outbox_batch(session).processed_count == 0
    assert session.query(RecoveryCaseTriggerRecord).count() == 1


def test_worker_binding_is_closed_without_isolated_key(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = OutboxDispatcher()
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E", raising=False)
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("commitment.at_risk") == []
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E_KEY", raising=False)
    with pytest.raises(RuntimeError, match="server-owned mutation key"):
        configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("commitment.at_risk") == []


def test_case_generates_two_persisted_p2_checked_plans(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, context = _seed_delay(session)
    PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    dispatcher = OutboxDispatcher()
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "synthetic-private-key-with-at-least-32-chars")
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.process_outbox_batch(session).failed_count == 0
    core = session.get(CommitmentRecord, (context.tenant_id, "com-001"))
    plans = DurablePlanService().generate(
        session, context, "com-001", expected_commitment_version=core.commitment_version,
        assessment_id=None,
    )
    assert len(plans) == 2
    assert {plan.strategy.value for plan in plans} == {
        "ALTERNATIVE_SUPPLY", "RESCHEDULE_PARTIAL_FULFILMENT",
    }
    assert all(plan.evaluation.validation_source.value == "REAL_P2_VALIDATED" for plan in plans)
    assert next(plan for plan in plans if plan.option_id == "alternative_supply").feasibility_status == "INFEASIBLE"
    assert next(plan for plan in plans if plan.option_id == "revised_schedule").feasibility_status == "CONDITIONAL"
    assert session.query(RecoveryPlanRecord).count() == 2
    assert len(DurablePlanService().list(session, context, "com-001")) == 2
    assert len(DurablePlanService().generate(
        session, context, "com-001", expected_commitment_version=core.commitment_version,
        assessment_id=plans[0].based_on_assessment_id,
    )) == 2
    assert session.query(RecoveryPlanRecord).count() == 2
    with Session(session.bind) as restarted:
        reloaded = DurablePlanService().list(restarted, context, "com-001")
        assert {plan.plan_id for plan in reloaded} == {plan.plan_id for plan in plans}
        assert reloaded[0].based_on_assessment_id == plans[0].based_on_assessment_id
        wrong = RequestContext(
            tenant_id="tenant_other", actor_id="service_p2", actor_role="SERVICE",
            correlation_id="corr_wrong_tenant",
        )
        with pytest.raises(DomainError) as error:
            DurablePlanService().list(restarted, wrong, "com-001")
        assert error.value.code == "RECOVERY_CASE_NOT_FOUND"
    with pytest.raises(DomainError) as error:
        DurablePlanService().generate(
            session, context, "com-001", expected_commitment_version=core.commitment_version + 1,
            assessment_id=None,
        )
    assert error.value.code == "COMMITMENT_VERSION_CONFLICT"


def _prepared_review(session: Session, monkeypatch: pytest.MonkeyPatch):
    inputs, context = _seed_delay(session)
    PersistedSupplierDelayProcessor().process(session, context, inputs.request)
    dispatcher = OutboxDispatcher()
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    key = "synthetic-private-key-with-at-least-32-chars"
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", key)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "trusted_manager")
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.process_outbox_batch(session).failed_count == 0
    core = session.get(CommitmentRecord, (context.tenant_id, "com-001"))
    plans = DurablePlanService().generate(
        session, context, "com-001", expected_commitment_version=core.commitment_version,
        assessment_id=None,
    )
    manager = RequestContext(
        tenant_id=context.tenant_id, actor_id="trusted_manager", actor_role="STAFF",
        correlation_id="corr_manager_review",
    )
    return next(plan for plan in plans if plan.option_id == "revised_schedule"), manager, key


def test_live_recovery_http_decision_and_verified_task(
    session: Session, client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    headers = {"X-Tenant-ID": manager.tenant_id, "X-Actor-ID": manager.actor_id,
               "X-Isolated-E2E-Key": key}
    case_response = client.get("/v1/recovery/cases/com-001", headers=headers)
    assert case_response.status_code == 200, case_response.text
    assert case_response.json()["storage_mode"] == "DURABLE_DATABASE"
    plans_response = client.get("/v1/recovery/cases/com-001/plans", headers=headers)
    assert plans_response.status_code == 200, plans_response.text
    assert any(item["plan_id"] == plan.plan_id for item in plans_response.json()["plans"])
    request = {"expected_plan_version": plan.plan_version,
               "expected_commitment_version": plan.core_commitment_version,
               "expected_snapshot_version": plan.snapshot_version,
               "idempotency_key": "http-manager-decision-1", "reason": "Review revised delivery"}
    denied = client.post(f"/v1/recovery/plans/{plan.plan_id}/approve", json=request,
                         headers={**headers, "X-Actor-ID": "untrusted_staff"})
    assert denied.status_code == 403
    approved = client.post(f"/v1/recovery/plans/{plan.plan_id}/approve", json=request, headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["decision"] == "APPROVED"
    history = client.get(f"/v1/recovery/plans/{plan.plan_id}/approvals", headers=headers)
    assert history.status_code == 200 and len(history.json()) == 1
    action_request = {"expected_plan_version": plan.plan_version,
                      "expected_commitment_version": plan.core_commitment_version,
                      "expected_snapshot_version": plan.snapshot_version,
                      "idempotency_key": "http-internal-action-1"}
    executed = client.post(f"/v1/recovery/plans/{plan.plan_id}/execute", json=action_request, headers=headers)
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "SUCCEEDED" and executed.json()["task_id"]
    assert executed.json()["receipt_ref"]
    again = client.post(f"/v1/recovery/plans/{plan.plan_id}/execute", json=action_request, headers=headers)
    assert again.status_code == 200 and again.json()["task_id"] == executed.json()["task_id"]
    actions = client.get(f"/v1/recovery/plans/{plan.plan_id}/actions", headers=headers)
    assert actions.status_code == 200 and len(actions.json()) == 1


def test_approved_revised_plan_creates_exact_core_proposal_and_p4_source(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "user_manager_01")
    manager = RequestContext(manager.tenant_id, "user_manager_01", "MANAGER", manager.correlation_id)
    approval = ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-p4-handoff", reason="Approve revised delivery proposal",
    )
    assert "CREATE_DELIVERY_CHANGE_PROPOSAL" in approval.action_scope
    original = dict(session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id)).terms)
    command = RequestCommunicationInput(
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
    )
    service = DurableCommunicationHandoff()
    with pytest.raises(DomainError) as error:
        service.request(session, manager, key, plan.recovery_case_id + "_alternative_supply", command)
    assert error.value.code == "PROPOSAL_NOT_ALLOWED"
    first = service.request(session, manager, key, plan.plan_id, command)
    assert service.request(session, manager, key, plan.plan_id, command).source_event_id == first.source_event_id
    core = session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id))
    assert core.commitment_version == 3 and core.agreement_state == "OFFERED"
    assert core.terms == original
    proposal = session.get(CommitmentProposalRecord, (manager.tenant_id, first.proposal_id))
    assert proposal is not None and proposal.status == "ACTIVE"
    assert proposal.revised_terms == approval.approved_terms == first.approved_terms.model_dump(mode="json")
    event = session.get(OutboxEventRecord, first.source_event_id)
    assert event is not None and event.causation_id == approval.approval_id
    assert event.payload["approval_evidence_ref"] == approval.audit_id
    assert event.payload["snapshot_id"] == plan.snapshot_id
    p4_context = RequestContext(manager.tenant_id, "user_manager_01", "MANAGER", "corr_p4_read")
    basis = CommunicationRequestService(session).read_current_basis(
        p4_context, CreateCommunicationRequest(source_event_id=first.source_event_id),
        datetime.now(UTC),
    )
    assert basis.reference.plan_id == plan.plan_id
    assert basis.reference.proposal_version == plan.plan_version
    assert basis.terms == first.approved_terms
    p4 = CommunicationRequestService(session, IsolatedRecoveryRequestAuthority(key))
    request = CreateCommunicationRequest(source_event_id=first.source_event_id)
    intake = p4.create(manager, request)
    assert intake.request_status == "BLOCKED"
    assert "VERIFIED_RECIPIENT_REQUIRED" in intake.blocking_reasons
    revoked = ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="REVOKED",
        expected_plan_version=1, expected_commitment_version=3,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="revoke-p4-handoff", reason="Withdraw proposed terms",
    )
    assert revoked.decision == "REVOKED"
    with pytest.raises(DomainError) as error:
        service.request(session, manager, key, plan.plan_id, command)
    assert error.value.code == "APPROVAL_NOT_ACTIVE"
    with pytest.raises(DomainError) as error:
        p4.create(manager, request)
    assert error.value.code == "APPROVAL_NOT_ACTIVE"


def test_durable_manager_approval_idempotency_restart_and_revocation(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    service = ManagerApprovalService()
    params = {
        "expected_plan_version": plan.plan_version,
        "expected_commitment_version": 2,
        "expected_snapshot_version": plan.snapshot_version,
        "idempotency_key": "approval-review-1", "reason": "Review internal reschedule task",
    }
    approved = service.decide(session, manager, key, plan.plan_id, decision="APPROVED", **params)
    assert approved.actor_role == "MANAGER"
    assert approved.approved_amount == plan.estimated_extra_cost
    assert approved.snapshot_id
    assert service.decide(session, manager, key, plan.plan_id, decision="APPROVED", **params).approval_id == approved.approval_id
    with Session(session.bind) as restarted:
        record = restarted.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
        assert ManagerApprovalService().require_active(restarted, manager, record).approval_id == approved.approval_id
    revoked = service.decide(
        session, manager, key, plan.plan_id, decision="REVOKED",
        **{**params, "idempotency_key": "approval-revoke-1", "reason": "Approval withdrawn"},
    )
    assert revoked.decision == "REVOKED"
    assert len(service.history(session, manager, plan.plan_id)) == 2
    with pytest.raises(DomainError) as error:
        service.require_active(session, manager, session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1)))
    assert error.value.code == "APPROVAL_NOT_ACTIVE"
    assert session.query(ManagerApprovalRecord).count() == 2


def test_approval_rejects_staff_infeasible_plan_and_stale_version(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    staff = RequestContext(
        tenant_id=manager.tenant_id, actor_id="staff_01", actor_role="MANAGER",
        correlation_id="corr_spoof",
    )
    service = ManagerApprovalService()
    params = {
        "decision": "APPROVED", "expected_plan_version": 1,
        "expected_commitment_version": 2, "expected_snapshot_version": plan.snapshot_version,
        "idempotency_key": "approval-denied", "reason": "Try approval",
    }
    with pytest.raises(DomainError) as error:
        service.decide(session, staff, key, plan.plan_id, **params)
    assert error.value.code == "MANAGER_APPROVAL_REQUIRED"
    with pytest.raises(DomainError) as error:
        service.decide(session, manager, key, plan.plan_id,
                       **{**params, "expected_commitment_version": 1})
    assert error.value.code == "COMMITMENT_VERSION_CONFLICT"
    alt_id = plan.recovery_case_id + "_alternative_supply"
    with pytest.raises(DomainError) as error:
        service.decide(session, manager, key, alt_id, **params)
    assert error.value.code == "PLAN_NOT_APPROVABLE"
    assert session.query(ManagerApprovalRecord).count() == 0


def test_approved_internal_task_creates_verified_business_record_once(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-task", reason="Authorize internal review task",
    )
    service = DurableActionService()
    kwargs = {
        "expected_plan_version": 1, "expected_commitment_version": 2,
        "expected_snapshot_version": plan.snapshot_version,
        "idempotency_key": "task-once",
    }
    first = service.execute(session, manager, key, plan.plan_id, **kwargs)
    assert first.status == "SUCCEEDED"
    assert first.receipt_ref and first.audit_id
    task = session.get(InternalRecoveryTaskRecord, (manager.tenant_id, first.task_id))
    assert task is not None and task.status == "OPEN"
    assert task.payload["customer_acceptance_required_for_terms_change"] is True
    assert service.execute(session, manager, key, plan.plan_id, **kwargs).execution_id == first.execution_id
    with pytest.raises(DomainError) as error:
        service.execute(session, manager, key, plan.plan_id, **{**kwargs, "idempotency_key": "task-second-key"})
    assert error.value.code == "ACTION_ALREADY_EXECUTED"
    assert session.query(InternalRecoveryTaskRecord).count() == 1
    assert session.query(RecoveryActionExecutionRecord).count() == 1
    with Session(session.bind) as restarted:
        saved = DurableActionService().history(restarted, manager, plan.plan_id)
        assert len(saved) == 1 and saved[0].receipt_ref == first.receipt_ref
    assert session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id)).risk_state == "AT_RISK"


def test_action_blocks_expired_approval_and_rolls_back_adapter_failure(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    approval = ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-failure", reason="Authorize internal review task",
    )
    kwargs = {
        "expected_plan_version": 1, "expected_commitment_version": 2,
        "expected_snapshot_version": plan.snapshot_version,
        "idempotency_key": "task-failure",
    }
    approval.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
    session.commit()
    with pytest.raises(DomainError) as error:
        DurableActionService().execute(session, manager, key, plan.plan_id, **kwargs)
    assert error.value.code == "APPROVAL_NOT_ACTIVE"
    approval.expires_at = datetime(2099, 1, 1, tzinfo=UTC)
    session.commit()

    def fail_adapter(*args, **kwargs):
        raise RuntimeError("synthetic adapter failure")

    original_adapter = DurableActionService._create_task
    monkeypatch.setattr(DurableActionService, "_create_task", staticmethod(fail_adapter))
    with pytest.raises(RuntimeError, match="synthetic adapter failure"):
        DurableActionService().execute(session, manager, key, plan.plan_id, **kwargs)
    assert session.query(InternalRecoveryTaskRecord).count() == 0
    failed = session.query(RecoveryActionExecutionRecord).one()
    assert failed.status == "FAILED" and failed.attempts == 1
    monkeypatch.setattr(DurableActionService, "_create_task", staticmethod(original_adapter))
    retried = DurableActionService().execute(session, manager, key, plan.plan_id, **kwargs)
    assert retried.status == "SUCCEEDED" and retried.attempts == 2
    assert session.query(InternalRecoveryTaskRecord).count() == 1


def test_manager_approval_binds_versioned_proposal_id_for_successor_plan(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    # 1. Version 1 binds proposal_id == plan.plan_id
    plan_v1_rec = session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
    assert plan_v1_rec is not None
    plan_v1_rec.payload = dict(plan_v1_rec.payload, proposal_id=plan.plan_id, proposal_version=1)
    session.commit()
    appr_v1 = ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-v1-proposal-id", reason="Authorize plan V1",
    )
    assert appr_v1.proposal_id == plan.plan_id
    assert appr_v1.proposal_version == 1

    # 2. Insert a V2 successor plan version in recovery_plan_versions
    plan_v2_rec = RecoveryPlanRecord(
        tenant_id=plan_v1_rec.tenant_id,
        plan_id=plan_v1_rec.plan_id,
        plan_version=2,
        case_id=plan_v1_rec.case_id,
        commitment_id=plan_v1_rec.commitment_id,
        assessment_id=plan_v1_rec.assessment_id,
        snapshot_id=plan_v1_rec.snapshot_id,
        snapshot_version=plan_v1_rec.snapshot_version,
        core_commitment_version=plan_v1_rec.core_commitment_version,
        evaluated_commitment_version=plan_v1_rec.evaluated_commitment_version,
        payload=dict(plan_v1_rec.payload, plan_version=2,
                     proposal_id=f"{plan.plan_id}_v2", proposal_version=2,
                     evaluation={**plan_v1_rec.payload["evaluation"], "plan_version": 2}),
        status=plan_v1_rec.status,
        created_at=datetime.now(UTC),
    )
    session.add(plan_v2_rec)
    session.commit()
    with pytest.raises(DomainError) as stale_approval:
        ManagerApprovalService().require_active(session, manager, plan_v2_rec)
    assert stale_approval.value.code == "APPROVAL_SCOPE_CONFLICT"

    # 3. Version 2 binds proposal_id == f"{plan_id}_v2"
    appr_v2 = ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=2, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-v2-proposal-id", reason="Authorize successor plan V2",
    )
    assert appr_v2.proposal_id == f"{plan.plan_id}_v2"
    assert appr_v2.proposal_version == 2
    assert appr_v2.commitment_id == plan.commitment_id
    assert appr_v2.actor_id == manager.actor_id
    assert appr_v2.approved_amount == plan.estimated_extra_cost
    assert session.get(ManagerApprovalRecord, (manager.tenant_id, appr_v1.approval_id)).proposal_id == plan.plan_id
    assert ManagerApprovalService().decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=2, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="approval-v2-proposal-id", reason="Authorize successor plan V2",
    ).approval_id == appr_v2.approval_id
    assert session.query(ManagerApprovalRecord).count() == 2
    audit_count = session.query(AuditEventRecord).count()
    plan_v2_rec.payload = dict(plan_v2_rec.payload, proposal_id=plan.plan_id)
    session.commit()
    with pytest.raises(DomainError) as changed_payload:
        ManagerApprovalService().decide(
            session, manager, key, plan.plan_id, decision="APPROVED",
            expected_plan_version=2, expected_commitment_version=2,
            expected_snapshot_version=plan.snapshot_version,
            idempotency_key="approval-v2-proposal-id", reason="Authorize successor plan V2",
        )
    assert changed_payload.value.code == "PROPOSAL_PLAN_IDENTITY_CONFLICT"
    assert session.query(ManagerApprovalRecord).count() == 2
    assert session.query(AuditEventRecord).count() == audit_count


def test_manager_approval_revokes_exact_versioned_offer_without_mutating_v1(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    service = ManagerApprovalService()
    v1 = service.decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=1, expected_commitment_version=2,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="revocation-v1", reason="Authorize first offer",
    )
    core_manager = RequestContext(manager.tenant_id, manager.actor_id, "MANAGER", manager.correlation_id)
    first = CommitmentService().create_proposal(
        session, core_manager, plan.commitment_id,
        ProposalCreateRequest(
            proposal_id=plan.plan_id, proposal_version=1,
            expected_commitment_version=2, revised_terms=v1.approved_terms,
            reason="Approved recovery V1", evidence_refs=[v1.audit_id],
        ),
    )
    original = session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
    assert original is not None
    offered_version = first.commitment.commitment_version
    session.add(RecoveryPlanRecord(
        tenant_id=original.tenant_id, plan_id=original.plan_id, plan_version=2,
        case_id=original.case_id, commitment_id=original.commitment_id,
        assessment_id=original.assessment_id, snapshot_id=original.snapshot_id,
        snapshot_version=original.snapshot_version,
        core_commitment_version=offered_version,
        evaluated_commitment_version=original.evaluated_commitment_version,
        payload=dict(original.payload, plan_version=2,
                     core_commitment_version=offered_version,
                     proposal_id=f"{plan.plan_id}_v2", proposal_version=2,
                     evaluation={**original.payload["evaluation"], "plan_version": 2}),
        status=original.status, created_at=datetime.now(UTC),
    ))
    session.commit()
    v2 = service.decide(
        session, manager, key, plan.plan_id, decision="APPROVED",
        expected_plan_version=2, expected_commitment_version=offered_version,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="revocation-v2", reason="Authorize successor offer",
    )
    second = CommitmentService().create_proposal(
        session, core_manager, plan.commitment_id,
        ProposalCreateRequest(
            proposal_id=v2.proposal_id, proposal_version=2,
            expected_commitment_version=offered_version,
            revised_terms=v2.approved_terms, reason="Approved recovery V2",
            evidence_refs=[v2.audit_id],
        ),
    )
    old_offer = session.get(CommitmentProposalRecord, (manager.tenant_id, v1.proposal_id))
    new_offer = session.get(CommitmentProposalRecord, (manager.tenant_id, v2.proposal_id))
    assert old_offer is not None and old_offer.status == "SUPERSEDED"
    assert new_offer is not None and new_offer.status == "ACTIVE"
    assert new_offer.revised_terms == v2.approved_terms
    revoked = service.decide(
        session, manager, key, plan.plan_id, decision="REVOKED",
        expected_plan_version=2, expected_commitment_version=second.commitment.commitment_version,
        expected_snapshot_version=plan.snapshot_version,
        idempotency_key="revoke-exact-v2", reason="Withdraw successor offer",
    )
    assert (revoked.proposal_id, revoked.proposal_version) == (v2.proposal_id, 2)
    assert session.get(ManagerApprovalRecord, (manager.tenant_id, v1.approval_id)).decision == "APPROVED"
    assert session.get(CommitmentProposalRecord, (manager.tenant_id, v1.proposal_id)).status == "SUPERSEDED"
    with pytest.raises(DomainError) as inactive:
        service.require_active(session, manager, session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 2)))
    assert inactive.value.code == "APPROVAL_NOT_ACTIVE"


@pytest.mark.parametrize("identity", [
    {"proposal_id": "v1", "proposal_version": 1},
    {"proposal_id": "v2", "proposal_version": 1},
    {"proposal_id": "v2", "proposal_version": None},
])
def test_manager_approval_rejects_malformed_v2_proposal_identity_without_evidence(
    session: Session, monkeypatch: pytest.MonkeyPatch, identity: dict,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    original = session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
    assert original is not None
    payload = dict(original.payload, plan_version=2,
                   evaluation={**original.payload["evaluation"], "plan_version": 2})
    payload["proposal_id"] = plan.plan_id if identity["proposal_id"] == "v1" else f"{plan.plan_id}_v2"
    payload["proposal_version"] = identity["proposal_version"]
    session.add(RecoveryPlanRecord(
        tenant_id=original.tenant_id, plan_id=original.plan_id, plan_version=2,
        case_id=original.case_id, commitment_id=original.commitment_id,
        assessment_id=original.assessment_id, snapshot_id=original.snapshot_id,
        snapshot_version=original.snapshot_version,
        core_commitment_version=original.core_commitment_version,
        evaluated_commitment_version=original.evaluated_commitment_version,
        payload=payload, status=original.status, created_at=datetime.now(UTC),
    ))
    session.commit()
    approval_count = session.query(ManagerApprovalRecord).count()
    audit_count = session.query(AuditEventRecord).count()
    with pytest.raises(DomainError) as error:
        ManagerApprovalService().decide(
            session, manager, key, plan.plan_id, decision="APPROVED",
            expected_plan_version=2, expected_commitment_version=2,
            expected_snapshot_version=plan.snapshot_version,
            idempotency_key="invalid-v2-binding", reason="Must fail closed",
        )
    assert error.value.code == "PROPOSAL_PLAN_IDENTITY_CONFLICT"
    assert session.query(ManagerApprovalRecord).count() == approval_count
    assert session.query(AuditEventRecord).count() == audit_count
    assert session.get(CommitmentRecord, (manager.tenant_id, plan.commitment_id)).agreement_state == "CONFIRMED"


def test_manager_approval_rejects_wrong_tenant_and_plan_payload_binding(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, manager, key = _prepared_review(session, monkeypatch)
    service = ManagerApprovalService()
    wrong_tenant = RequestContext("tenant_other", manager.actor_id, manager.actor_role, manager.correlation_id)
    with pytest.raises(DomainError) as missing:
        service.decide(session, wrong_tenant, key, plan.plan_id, decision="APPROVED",
                       expected_plan_version=1, expected_commitment_version=2,
                       expected_snapshot_version=plan.snapshot_version,
                       idempotency_key="wrong-tenant", reason="Wrong tenant")
    assert missing.value.code in {"MANAGER_APPROVAL_REQUIRED", "RECOVERY_PLAN_NOT_FOUND"}
    row = session.get(RecoveryPlanRecord, (manager.tenant_id, plan.plan_id, 1))
    assert row is not None
    row.payload = dict(row.payload, commitment_id="another_commitment")
    session.commit()
    audit_count = session.query(AuditEventRecord).count()
    with pytest.raises(DomainError) as conflict:
        service.decide(session, manager, key, plan.plan_id, decision="APPROVED",
                       expected_plan_version=1, expected_commitment_version=2,
                       expected_snapshot_version=plan.snapshot_version,
                       idempotency_key="wrong-plan-binding", reason="Wrong plan binding")
    assert conflict.value.code == "RECOVERY_PLAN_BINDING_MISMATCH"
    assert session.query(ManagerApprovalRecord).count() == 0
    assert session.query(AuditEventRecord).count() == audit_count


def test_sqlite_alembic_0009_has_source_constraints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Portable migration check; this is not PostgreSQL verification."""
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{(tmp_path / 'p2_migrated.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    try:
        assert {"p2_operational_snapshots", "p2_supplier_delay_events", "recovery_plan_versions",
                "manager_approval_decisions", "internal_recovery_tasks",
                "recovery_action_executions"} <= set(inspect(engine).get_table_names())
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            scripts = ScriptDirectory.from_config(cfg)
            assert scripts.get_heads() == [revision]
            assert "0009_p2_operational_sources" in {
                entry.revision for entry in scripts.iterate_revisions(revision, "base")
            }
            connection.execute(text("""
                INSERT INTO p2_operational_snapshots
                (tenant_id,snapshot_version,snapshot_id,payload,is_current,created_at)
                VALUES ('tenant_p2',1,'before','{}',1,'2026-10-22T00:00:00Z'),
                       ('tenant_p2',2,'after','{}',0,'2026-10-22T00:00:00Z')
            """))
            connection.execute(text("""
                INSERT INTO p2_supplier_delay_events
                (tenant_id,event_id,before_snapshot_version,after_snapshot_version,evidence_ref,
                 impact_id,event_digest,impact_payload,occurred_at)
                VALUES ('tenant_p2','event',1,2,'evidence','impact','digest','{}','2026-10-22T00:00:00Z')
            """))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("DELETE FROM p2_operational_snapshots WHERE tenant_id='tenant_p2' AND snapshot_version=1"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("UPDATE p2_operational_snapshots SET is_current=1 WHERE tenant_id='tenant_p2' AND snapshot_version=2"))
    finally:
        engine.dispose()
