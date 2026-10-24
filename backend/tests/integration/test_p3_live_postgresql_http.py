"""Opt-in real HTTP + worker journey on an approved migrated PostgreSQL test DB."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.models import (
    AuditEventRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.feasibility.persisted_sources import stage_snapshot
from app.feasibility.pipeline_fixtures import build_pipeline_example
from app.feasibility.supplier_pipeline import SupplierDelayInputs
from app.integrations.business_ports import ReservationReceipt
from app.orchestration.models import BusinessImpactLinkRecord, BusinessNotificationIntentRecord
from app.orders.models import MockOrbyteReservationRecord, MockOrderSourceRecord, OrderRequestRecord
from app.orders.terms import OrderTerms
from app.recovery.durable_actions import InternalRecoveryTaskRecord, RecoveryActionExecutionRecord
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord


def _approved_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Real PostgreSQL E2E requires an explicit TEST_DATABASE_URL")
    if os.getenv("TEST_DATABASE_APPROVED") != "1":
        pytest.fail("TEST_DATABASE_APPROVED=1 is required")
    if "test" not in url.rsplit("/", 1)[-1].lower():
        pytest.fail("A named disposable test database is required")
    engine = create_engine(url, pool_pre_ping=True)
    assert engine.dialect.name == "postgresql"
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        script = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")))
        assert script.get_heads() == [revision]
        assert "0012_p3_internal_actions" in {
            entry.revision for entry in script.iterate_revisions(revision, "base")
        }
    return engine


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start(command: list[str], env: dict[str, str], log_path: Path | None = None) -> subprocess.Popen:
    with (log_path.open("ab") if log_path else open(os.devnull, "wb")) as log:
        return subprocess.Popen(
            [sys.executable, *command], cwd=Path(__file__).resolve().parents[2], env=env,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def _stop(process: subprocess.Popen | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _eventually(check, *, timeout: float = 25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
        except httpx.ConnectError:
            value = None
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for real server/worker state")


def _seed_verified_accepted_order(
    db: Session, tenant: str, core: CommitmentRecord, source_commitment,
) -> str:
    """Persist one exact synthetic acceptance for the positive P2 link case."""
    now = datetime.now(UTC)
    source_line = source_commitment.lines[0]
    order_request_id = f"order_{core.commitment_id}"
    deadline = source_commitment.delivery_deadline
    terms = OrderTerms.model_validate({
        "tenant_id": tenant,
        "order_request_id": order_request_id,
        "customer_id": f"customer_{core.commitment_id}",
        "terms_revision": 1,
        "items": [{"sku": source_line.sku_id, "quantity": str(source_line.quantity),
                   "unit": source_line.unit, "unit_price": "2"}],
        "fulfilment_method": "DELIVERY",
        "location_ref": "synthetic-address-ref",
        "window_start": (deadline - timedelta(hours=3)).isoformat(),
        "window_end": deadline.isoformat(),
        "business_timezone": "Asia/Singapore",
        "currency": "SGD",
        "fees": "0", "tax": "0", "discount": "0",
        "total": str(source_line.quantity * 2),
        "price_source": {
            "source_type": "APPROVED_CATALOG", "source_id": "synthetic-catalog",
            "source_version": "1", "policy_ref": "synthetic-pricing-policy",
            "disclosed_at": (now - timedelta(hours=1)).isoformat(),
            "evidence_refs": ["synthetic-price-disclosure"],
        },
        "binding_policy_ref": "synthetic-pricing-policy",
        "source_message_ids": ["synthetic-order-message"],
        "evidence_refs": ["synthetic-order-request", "synthetic-price-disclosure"],
    })
    source_id = f"source_{order_request_id}"
    source_refs = ["synthetic-order-request", "synthetic-price-disclosure"]
    source_observed_at = now - timedelta(hours=1)
    source_valid_through = now + timedelta(days=1)
    request = OrderRequestRecord(
        tenant_id=tenant, order_request_id=order_request_id,
        customer_id=terms.customer_id, source_id=source_id, source_version=1,
        source_observed_at=source_observed_at, source_valid_through=source_valid_through,
        source_evidence_refs=source_refs, terms=terms.model_dump(mode="json"),
        terms_hash=terms.terms_hash, request_version=3, decision_status="ACCEPTED",
        review_actor_id="user_manager_01", review_reason="Synthetic exact acceptance",
        commitment_id=core.commitment_id, created_at=now, updated_at=now,
    )
    source = MockOrderSourceRecord(
        tenant_id=tenant, source_id=source_id, customer_id=terms.customer_id,
        source_version=1, terms=terms.model_dump(mode="json"),
        customer_request_ref=source_refs[0], price_disclosure_ref=source_refs[1],
        observed_at=source_observed_at, valid_through=source_valid_through, status="CURRENT",
    )
    operation_id = f"mop_{uuid4().hex}"
    receipt = ReservationReceipt(
        tenant_id=tenant, order_request_id=order_request_id, operation_id=operation_id,
        idempotency_key=f"accept_{order_request_id}", request_version=2,
        terms_hash=terms.terms_hash, terms_revision=terms.terms_revision,
        snapshot_id="synthetic-mock-snapshot", snapshot_version=1,
        assessment_id=f"assessment_{core.commitment_id}", status="CONFIRMED", mode="MOCK",
        checked_at=now, reservation_ids=(f"reservation_{core.commitment_id}",),
        evidence_refs=(f"reservation_receipt_{core.commitment_id}",),
    )
    core.order_id = order_request_id
    core.customer_id = terms.customer_id
    core.terms = {
        **core.terms,
        "mock_order_request_version": receipt.request_version,
        "mock_terms_hash": terms.terms_hash,
    }
    core.evidence_refs = sorted({*core.evidence_refs, *receipt.evidence_refs})
    db.add_all([
        source,
        request,
        MockOrbyteReservationRecord(
            operation_id=operation_id, tenant_id=tenant, order_request_id=order_request_id,
            idempotency_key=receipt.idempotency_key, request_version=receipt.request_version,
            terms_hash=receipt.terms_hash, snapshot_version=receipt.snapshot_version,
            assessment_id=receipt.assessment_id, actor_id="user_manager_01",
            approval_reason="Synthetic exact acceptance", status="CONFIRMED",
            receipt=receipt.model_dump(mode="json"), created_at=now,
        ),
        AuditEventRecord(
            audit_id=f"aud_{uuid4().hex[:16]}", tenant_id=tenant,
            commitment_id=core.commitment_id, event_type="commitment.mock_order_accepted",
            actor_id="user_manager_01", actor_role="MANAGER", dimension="agreement",
            previous_state=None,
            new_state={
                "order_request_id": order_request_id, "terms_hash": terms.terms_hash,
                "request_version": receipt.request_version,
                "reservation_operation_id": operation_id,
            },
            evidence_refs=list(receipt.evidence_refs), reason="Synthetic accepted order receipt",
            correlation_id=f"corr_{order_request_id}", causation_id=operation_id,
            occurred_at=now,
        ),
    ])
    return order_request_id


def test_real_http_worker_restart_and_verified_action_on_migrated_postgresql(tmp_path: Path) -> None:
    engine = _approved_engine()
    tenant = f"tenant_p3_live_{uuid4().hex[:12]}"
    raw = build_pipeline_example(mode="complete")
    source_tenant = raw.request.change.tenant_id
    event_id = f"evt_p3_live_{uuid4().hex}"
    inputs = SupplierDelayInputs.model_validate(json.loads(
        json.dumps(raw.model_dump(mode="json", exclude_computed_fields=True))
        .replace(source_tenant, tenant).replace(raw.request.change.event_id, event_id)
    ))
    with Session(engine) as db:
        for commitment in inputs.before_commitments:
            db.add(CommitmentRecord(
                tenant_id=tenant, commitment_id=commitment.commitment_id,
                order_id=commitment.order_id, customer_id=commitment.customer_id,
                terms=commitment.terms.model_dump(mode="json"), agreement_state="CONFIRMED",
                feasibility_state="NOT_ASSESSED", risk_state="NORMAL", recovery_state="NONE",
                fulfilment_state="NOT_STARTED", commitment_version=commitment.commitment_version,
                evidence_refs=commitment.evidence_refs, updated_at=commitment.updated_at,
            ))
        stage_snapshot(db, inputs.before, current=True)
        stage_snapshot(db, inputs.after)
        db.commit()

    key = "isolated-e2e-" + uuid4().hex
    manager_id = "user_manager_01"  # Exact ID is registered in this isolated server environment.
    env = dict(os.environ, DATABASE_URL=os.environ["TEST_DATABASE_URL"],
               MOUMANTAI_SYNTHETIC_MODE="1",
               MOUMANTAI_ISOLATED_E2E="1", MOUMANTAI_ISOLATED_E2E_KEY=key,
               MOUMANTAI_ISOLATED_E2E_MANAGER_ID=manager_id,
               MOUMANTAI_ISOLATED_E2E_TENANT_ID=tenant)
    port = _free_port()
    server = worker = None
    try:
        server_log = tmp_path / "server.log"
        server = _start(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)], env, server_log)
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=8) as http:
            _eventually(lambda: server.poll() is None and http.get("/health").status_code == 200)
            headers = {"X-Tenant-ID": tenant, "X-Actor-ID": manager_id, "X-Isolated-E2E-Key": key}
            supplier = http.post("/v1/operations/events/supplier-delay", headers=headers,
                                 json=inputs.request.model_dump(mode="json"))
            assert supplier.status_code == 200, server_log.read_text(errors="replace")[-3500:]
            assert any(row["commitment_id"] == "com-001" and row["classification"] == "CONFIRMED_IMPACT"
                       for row in supplier.json()["impacts"])
            unaffected = next(row for row in supplier.json()["impacts"]
                              if row["commitment_id"] == "com-002")
            assert unaffected["classification"] == "VERIFIED_UNAFFECTED"
            impact_id = supplier.json()["impact_id"]
            linkage = http.post(f"/v1/orchestration/impacts/{impact_id}/resolve", headers=headers)
            assert linkage.status_code == 200, linkage.text
            assert linkage.json()["overall_status"] == "UNRESOLVED_HUMAN_REVIEW"
            target_link = next(row for row in linkage.json()["links"]
                               if row["commitment_id"] == "com-001")
            assert target_link["link_status"] == "UNRESOLVED_ORDER_ACCEPTANCE"
            assert "ACCEPTED_ORDER_RECORD_MISSING" in target_link["reason_codes"]
            unaffected_link = next(row for row in linkage.json()["links"]
                                   if row["commitment_id"] == "com-002")
            assert unaffected_link["classification"] == "VERIFIED_UNAFFECTED"
            assert unaffected_link["link_status"] == "UNRESOLVED_ORDER_ACCEPTANCE"
            replayed_linkage = http.post(f"/v1/orchestration/impacts/{impact_id}/resolve", headers=headers)
            assert replayed_linkage.status_code == 200
            assert replayed_linkage.json() == linkage.json()
            denied_linkage = http.post(f"/v1/orchestration/impacts/{impact_id}/resolve",
                                       headers={**headers, "X-Actor-ID": "user_staff_01"})
            assert denied_linkage.status_code == 403
            foreign_impact = http.get(f"/v1/orchestration/impacts/{impact_id}",
                                      headers={**headers, "X-Tenant-ID": "other_tenant"})
            assert foreign_impact.status_code == 404
            worker = _start(["-m", "app.worker"], env)

            def case_ready():
                with Session(engine) as db:
                    case = db.scalar(select(RecoveryCaseRecord).where(
                        RecoveryCaseRecord.tenant_id == tenant,
                        RecoveryCaseRecord.commitment_id == "com-001",
                    ))
                    return case if case and db.scalar(select(func.count()).select_from(
                        ProcessedEventRecord).where(
                            ProcessedEventRecord.tenant_id == tenant,
                            ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
                        )) == 1 else None

            case = _eventually(case_ready)
            assert worker.poll() is None
            with Session(engine) as db:
                trigger = db.scalar(select(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant,
                    RecoveryCaseTriggerRecord.case_id == case.case_id,
                ))
                assert trigger is not None and trigger.assessment_id
                risk = db.scalar(select(OutboxEventRecord).where(
                    OutboxEventRecord.tenant_id == tenant,
                    OutboxEventRecord.event_type == "commitment.at_risk",
                ))
                assert risk is not None and risk.status == "PUBLISHED"
                assert risk.payload["assessment_id"] == trigger.assessment_id
                risk_id = risk.event_id

            wrong = http.get("/v1/recovery/cases/com-001", headers={**headers, "X-Tenant-ID": "other_tenant"})
            assert wrong.status_code == 404
            current = http.get("/v1/recovery/cases/com-001", headers=headers)
            assert current.status_code == 409 and current.json()["code"] == "RECOVERY_EVALUATION_INPUTS_PENDING"
            trigger_view = http.get("/v1/recovery/cases/com-001/trigger", headers=headers)
            assert trigger_view.status_code == 200, trigger_view.text
            case_data = trigger_view.json()
            assert case_data["storage_mode"] == "DURABLE_DATABASE"
            version = case_data["commitment_version"]
            stale = http.post("/v1/recovery/cases/com-001/generate", headers=headers,
                              json={"expected_commitment_version": version + 1})
            assert stale.status_code == 409
            generated = http.post("/v1/recovery/cases/com-001/generate", headers=headers,
                                  json={"expected_commitment_version": version,
                                        "assessment_id": trigger.assessment_id})
            assert generated.status_code == 200, generated.text
            current = http.get("/v1/recovery/cases/com-001", headers=headers)
            assert current.status_code == 200, current.text
            plans = http.get("/v1/recovery/cases/com-001/plans", headers=headers)
            assert plans.status_code == 200, plans.text
            options = plans.json()["plans"]
            assert len(options) == 2
            assert {row["option_id"]: row["feasibility_status"] for row in options} == {
                "alternative_supply": "INFEASIBLE", "revised_schedule": "CONDITIONAL",
            }
            alternate = next(row for row in options if row["option_id"] == "alternative_supply")
            chosen = next(row for row in options if row["option_id"] == "revised_schedule")
            assert chosen["based_on_assessment_id"] == trigger.assessment_id
            assert chosen["snapshot_id"] == trigger.snapshot_id
            decision = {"expected_plan_version": chosen["plan_version"],
                        "expected_commitment_version": version,
                        "expected_snapshot_version": chosen["snapshot_version"],
                        "reason": "Review the revised schedule", "idempotency_key": uuid4().hex}
            alternate_decision = {**decision, "reason": "Supply is not verified", "idempotency_key": uuid4().hex}
            infeasible = http.post(f"/v1/recovery/plans/{alternate['plan_id']}/approve",
                                   json=alternate_decision, headers=headers)
            assert infeasible.status_code == 409 and infeasible.json()["code"] == "PLAN_NOT_APPROVABLE"
            rejected = http.post(f"/v1/recovery/plans/{alternate['plan_id']}/reject",
                                 json=alternate_decision, headers=headers)
            assert rejected.status_code == 200 and rejected.json()["decision"] == "REJECTED"
            revision = http.post(f"/v1/recovery/plans/{alternate['plan_id']}/request-revision",
                                 json={**alternate_decision, "idempotency_key": uuid4().hex}, headers=headers)
            assert revision.status_code == 200 and revision.json()["decision"] == "REVISION_REQUESTED"
            denied = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/approve", json=decision,
                               headers={**headers, "X-Actor-ID": "untrusted_staff"})
            assert denied.status_code == 403
            approved = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/approve", json=decision, headers=headers)
            assert approved.status_code == 200, approved.text
            assert approved.json()["decision"] == "APPROVED"
            history = http.get(f"/v1/recovery/plans/{chosen['plan_id']}/approvals", headers=headers)
            assert history.status_code == 200 and len(history.json()) == 1
            action = {"expected_plan_version": chosen["plan_version"],
                      "expected_commitment_version": version,
                      "expected_snapshot_version": chosen["snapshot_version"],
                      "idempotency_key": uuid4().hex}
            executed = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/execute", json=action, headers=headers)
            assert executed.status_code == 200, executed.text
            task_id = executed.json()["task_id"]
            assert executed.json()["status"] == "SUCCEEDED" and task_id and executed.json()["receipt_ref"]

            def intent_ready():
                with Session(engine) as db:
                    return db.scalar(select(BusinessNotificationIntentRecord).where(
                        BusinessNotificationIntentRecord.tenant_id == tenant,
                        BusinessNotificationIntentRecord.task_id == task_id,
                        BusinessNotificationIntentRecord.receipt_ref == executed.json()["receipt_ref"],
                    ))

            intent = _eventually(intent_ready)
            assert intent.status == "UNRESOLVED_ORDER_ACCEPTANCE"
            assert intent.idempotency_key == intent.source_event_id
            assert intent.customer_ref is None
            assert intent.contact_ref is None and intent.channel_ref is None and intent.consent_ref is None
            assert intent.original_channel_ref is None
            assert "HUMAN_REVIEW_BEFORE_ANY_DRAFT" in intent.review_requirements
            assert intent.source_provenance["p3_event_id"] == intent.source_event_id
            assert intent.integration_mode == "SYNTHETIC"
            assert intent.evidence_tier == "DEMO-ONLY"
            assert intent.verification_status == "INTERNALLY-VERIFIED"
            assert intent.verified_change["change_type"] == "INTERNAL_REVIEW_TASK_CREATED"
            assert intent.verified_change["fulfillment_changed"] is False
            assert "INTERNAL_REVIEW_TASK_IS_NOT_A_CUSTOMER_VISIBLE_MILESTONE" in intent.blocker_codes
            intent_view = http.get(f"/v1/orchestration/notification-intents/{intent.intent_id}", headers=headers)
            assert intent_view.status_code == 200, intent_view.text
            assert intent_view.json()["delivery_status"] == "NOT_SENT"
            assert intent_view.json()["status"] == "UNRESOLVED_ORDER_ACCEPTANCE"
            assert intent_view.json()["verification_status"] == "INTERNALLY-VERIFIED"
            assert intent_view.json()["idempotency_key"] == intent_view.json()["source_event_id"]
            assert intent_view.json()["original_channel_ref"] is None
            assert intent_view.json()["evidence_refs"]
            timeline = http.get("/v1/orchestration/commitments/com-001/timeline", headers=headers)
            assert timeline.status_code == 200, timeline.text
            timeline_types = {row["event_type"] for row in timeline.json()["entries"]}
            assert "supplier.delivery_changed" in timeline_types
            assert "recovery.internal_task_created" in timeline_types
            assert "communication.notification_intent" in timeline_types
            assert timeline.json()["overall_readiness"] == "UNRESOLVED_HUMAN_REVIEW"
            assert http.get(f"/v1/orchestration/notification-intents/{intent.intent_id}",
                            headers={**headers, "X-Tenant-ID": "other_tenant"}).status_code == 404

            progress = http.get("/v1/backend-v2/commitments/com-001/operational-evidence",
                                headers=headers)
            assert progress.status_code == 200, progress.text
            assert progress.json()["recovery"]["execution_status"] == "VERIFIED_INTERNAL_TASK"
            assert progress.json()["recovery"]["receipt_ref"] == executed.json()["receipt_ref"]
            assert progress.json()["actual_delivery"] == "NOT_AVAILABLE"
            duplicate = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/execute", json=action, headers=headers)
            assert duplicate.status_code == 200 and duplicate.json()["task_id"] == task_id
            second_key = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/execute", headers=headers,
                                   json={**action, "idempotency_key": uuid4().hex})
            assert second_key.status_code == 409 and second_key.json()["code"] == "ACTION_ALREADY_EXECUTED"
            actions = http.get(f"/v1/recovery/plans/{chosen['plan_id']}/actions", headers=headers)
            assert actions.status_code == 200 and len(actions.json()) == 1
            revoked = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/revoke", headers=headers,
                                json={**decision, "idempotency_key": uuid4().hex,
                                      "reason": "Manager revoked the approval"})
            assert revoked.status_code == 200 and revoked.json()["decision"] == "REVOKED"
            blocked = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/execute", headers=headers,
                                json={**action, "idempotency_key": uuid4().hex})
            assert blocked.status_code == 409 and blocked.json()["code"] == "APPROVAL_NOT_ACTIVE"
            approved_again = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/approve", headers=headers,
                                       json={**decision, "idempotency_key": uuid4().hex,
                                             "reason": "Reapprove exact proposed terms"})
            assert approved_again.status_code == 200, approved_again.text
            handoff = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/request-communication",
                                headers=headers, json={"expected_plan_version": chosen["plan_version"],
                                                       "expected_commitment_version": version,
                                                       "expected_snapshot_version": chosen["snapshot_version"]})
            assert handoff.status_code == 200, handoff.text
            handoff_body = handoff.json()
            assert handoff_body["approval_id"] == approved_again.json()["approval_id"]
            assert handoff_body["commitment_version"] == version + 1
            updated_case = http.get("/v1/recovery/cases/com-001", headers=headers)
            assert updated_case.status_code == 200, updated_case.text
            assert updated_case.json()["commitment_version"] == version + 1
            assert updated_case.json()["commitment"]["agreement_state"] == "OFFERED"
            assert updated_case.json()["commitment"]["terms"] != handoff_body["approved_terms"]
            intake = http.post("/v1/communications/requests", headers=headers,
                               json={"source_event_id": handoff_body["source_event_id"]})
            assert intake.status_code == 200, intake.text
            assert intake.json()["request_status"] == "BLOCKED"
            assert "VERIFIED_RECIPIENT_REQUIRED" in intake.json()["blocking_reasons"]
            assert "AUTHORIZED_CHANNEL_REQUIRED" in intake.json()["blocking_reasons"]
            assert intake.json()["proposed_terms"] == handoff_body["approved_terms"]
            communication_id = intake.json()["communication_id"]
            listed = http.get("/v1/communications", headers=headers,
                              params={"commitment_id": "com-001"})
            assert listed.status_code == 200
            assert any(row["communication_id"] == communication_id for row in listed.json())
            premature = http.post("/v1/commitments/com-001/confirm-proposal", headers=headers,
                                  json={"proposal_id": handoff_body["proposal_id"],
                                        "proposal_version": handoff_body["proposal_version"],
                                        "expected_commitment_version": handoff_body["commitment_version"],
                                        "decision": "ACCEPT", "evidence_refs": ["client_claim_only"],
                                        "reason": "Attempt to bypass P4"})
            assert premature.status_code == 503
            assert premature.json()["code"] == "P4_CONFIRMATION_AUTHORITY_UNAVAILABLE"
            draft = http.post(f"/v1/communications/{communication_id}/prepare", headers=headers,
                              json={"language": "en"})
            assert draft.status_code == 503
            revoked_after_offer = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/revoke", headers=headers,
                                            json={**decision,
                                                  "expected_commitment_version": handoff_body["commitment_version"],
                                                  "idempotency_key": uuid4().hex,
                                                  "reason": "Withdraw proposed terms after handoff"})
            assert revoked_after_offer.status_code == 200, revoked_after_offer.text
            refused_handoff = http.post(f"/v1/recovery/plans/{chosen['plan_id']}/request-communication",
                                        headers=headers, json={"expected_plan_version": chosen["plan_version"],
                                                               "expected_commitment_version": version,
                                                               "expected_snapshot_version": chosen["snapshot_version"]})
            assert refused_handoff.status_code == 409
            assert refused_handoff.json()["code"] == "APPROVAL_NOT_ACTIVE"
            refused_intake = http.post("/v1/communications/requests", headers=headers,
                                       json={"source_event_id": handoff_body["source_event_id"]})
            assert refused_intake.status_code == 409 and refused_intake.json()["code"] == "APPROVAL_NOT_ACTIVE"

            _stop(worker)
            worker = None
            with Session(engine) as db:
                risk = db.get(OutboxEventRecord, risk_id)
                risk.status = "PENDING"  # Deliberate persisted redelivery after worker restart.
                db.commit()
            worker = _start(["-m", "app.worker"], env)

            def redelivered():
                with Session(engine) as db:
                    risk = db.get(OutboxEventRecord, risk_id)
                    return risk.status == "PUBLISHED" if risk else False

            _eventually(redelivered)
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(BusinessImpactLinkRecord).where(
                    BusinessImpactLinkRecord.tenant_id == tenant,
                    BusinessImpactLinkRecord.impact_id == impact_id,
                    BusinessImpactLinkRecord.commitment_id == "com-001",
                )) == 1
                assert db.scalar(select(func.count()).select_from(BusinessNotificationIntentRecord).where(
                    BusinessNotificationIntentRecord.tenant_id == tenant,
                    BusinessNotificationIntentRecord.source_event_id == intent.source_event_id,
                )) == 1
                assert db.scalar(select(func.count()).select_from(ProcessedEventRecord).where(
                    ProcessedEventRecord.tenant_id == tenant,
                    ProcessedEventRecord.event_id == intent.source_event_id,
                    ProcessedEventRecord.consumer_name == "p5.recovery_notification_intent.v1",
                )) == 1
                assert db.scalar(select(func.count()).select_from(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant,
                    RecoveryCaseRecord.commitment_id == "com-001",
                )) == 1
                assert db.scalar(select(func.count()).select_from(ProcessedEventRecord).where(
                    ProcessedEventRecord.tenant_id == tenant,
                    ProcessedEventRecord.event_id == risk_id,
                    ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
                )) == 1
                assert db.get(InternalRecoveryTaskRecord, (tenant, task_id)) is not None
                assert db.scalar(select(func.count()).select_from(RecoveryActionExecutionRecord).where(
                    RecoveryActionExecutionRecord.tenant_id == tenant,
                    RecoveryActionExecutionRecord.plan_id == chosen["plan_id"],
                )) == 1
                final_core = db.get(CommitmentRecord, (tenant, "com-001"))
                assert final_core.risk_state == "AT_RISK"
                assert final_core.agreement_state == "OFFERED" and final_core.fulfilment_state == "NOT_STARTED"
                proof = db.scalar(select(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == tenant,
                    AuditEventRecord.commitment_id == "com-001",
                    AuditEventRecord.event_type == "recovery.internal_task_created",
                ))
                assert proof is not None
                proof.new_state = {**proof.new_state, "task_id": "forged"}
                db.commit()
            downgraded = http.get("/v1/backend-v2/commitments/com-001/operational-evidence",
                                  headers=headers)
            assert downgraded.status_code == 200
            assert downgraded.json()["recovery"]["execution_status"] == "UNVERIFIED"
            assert downgraded.json()["recovery"]["receipt_ref"] is None
    finally:
        _stop(worker)
        _stop(server)
        engine.dispose()


@pytest.mark.parametrize(
    ("two_affected", "mode", "expected_classification", "accepted_order"),
    [
        (True, "complete", "CONFIRMED_IMPACT", False),
        (True, "complete", "CONFIRMED_IMPACT", True),
        (False, "missing_supplier", "UNKNOWN", False),
    ],
)
def test_http_postgresql_impact_link_multi_commitment_and_missing_evidence(
    tmp_path: Path, two_affected: bool, mode: str, expected_classification: str,
    accepted_order: bool,
) -> None:
    """P2 multi-impact scope is preserved; incomplete evidence stays unresolved."""
    engine = _approved_engine()
    tenant = f"tenant_orchestration_{uuid4().hex[:12]}"
    raw = build_pipeline_example(two_affected=two_affected, mode=mode)
    source_tenant = raw.request.change.tenant_id
    event_id = f"evt_orchestration_{uuid4().hex}"
    inputs = SupplierDelayInputs.model_validate(json.loads(
        json.dumps(raw.model_dump(mode="json", exclude_computed_fields=True))
        .replace(source_tenant, tenant).replace(raw.request.change.event_id, event_id)
    ))
    with Session(engine) as db:
        for commitment in inputs.before_commitments:
            core = CommitmentRecord(
                tenant_id=tenant, commitment_id=commitment.commitment_id,
                order_id=commitment.order_id, customer_id=commitment.customer_id,
                terms=commitment.terms.model_dump(mode="json"), agreement_state="CONFIRMED",
                feasibility_state="NOT_ASSESSED", risk_state="NORMAL", recovery_state="NONE",
                fulfilment_state="NOT_STARTED", commitment_version=commitment.commitment_version,
                evidence_refs=commitment.evidence_refs, updated_at=commitment.updated_at,
            )
            db.add(core)
            if accepted_order and commitment.commitment_id == "com-001":
                source_commitment = next(
                    row for row in inputs.before.operational.confirmed_commitments
                    if row.commitment_id == commitment.commitment_id
                )
                _seed_verified_accepted_order(db, tenant, core, source_commitment)
        stage_snapshot(db, inputs.before, current=True)
        stage_snapshot(db, inputs.after)
        db.commit()

    key = "isolated-e2e-" + uuid4().hex
    manager_id = "user_manager_01"
    env = dict(os.environ, DATABASE_URL=os.environ["TEST_DATABASE_URL"],
               MOUMANTAI_SYNTHETIC_MODE="1", MOUMANTAI_ISOLATED_E2E="1",
               MOUMANTAI_ISOLATED_E2E_KEY=key, MOUMANTAI_ISOLATED_E2E_MANAGER_ID=manager_id,
               MOUMANTAI_ISOLATED_E2E_TENANT_ID=tenant)
    port = _free_port()
    server = None
    try:
        server_log = tmp_path / f"{mode}-{two_affected}-server.log"
        server = _start(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                        env, server_log)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=8) as http:
            _eventually(lambda: server.poll() is None and http.get("/health").status_code == 200)
            headers = {"X-Tenant-ID": tenant, "X-Actor-ID": manager_id, "X-Isolated-E2E-Key": key}
            supplier = http.post("/v1/operations/events/supplier-delay", headers=headers,
                                 json=inputs.request.model_dump(mode="json"))
            assert supplier.status_code == 200, server_log.read_text(errors="replace")[-3500:]
            observed = {row["commitment_id"]: row["classification"]
                        for row in supplier.json()["impacts"]}
            assert observed == {"com-001": expected_classification,
                                "com-002": expected_classification}
            if expected_classification == "UNKNOWN":
                assert not any(
                    intent["event"]["event_type"] == "commitment.at_risk"
                    for intent in supplier.json()["event_intents"]
                )

            impact_id = supplier.json()["impact_id"]
            links = http.post(f"/v1/orchestration/impacts/{impact_id}/resolve", headers=headers)
            assert links.status_code == 200, links.text
            assert links.json()["overall_status"] == "UNRESOLVED_HUMAN_REVIEW"
            assert len(links.json()["links"]) == 2
            accepted_link = next(row for row in links.json()["links"]
                                 if row["commitment_id"] == "com-001")
            if accepted_order:
                assert accepted_link["link_status"] == "LINKED_ACCEPTED_ORDER"
                assert accepted_link["order_request_id"] == "order_com-001"
                assert accepted_link["order_request_version"] == 3
                assert any(ref.startswith("reservation_receipt_")
                           for ref in accepted_link["evidence_refs"])
            else:
                assert accepted_link["link_status"] == (
                    "UNRESOLVED_IMPACT" if expected_classification == "UNKNOWN"
                    else "UNRESOLVED_ORDER_ACCEPTANCE"
                )
            for link in links.json()["links"]:
                assert link["commitment_id"] in {"com-001", "com-002"}
                expected_link_status = (
                    "LINKED_ACCEPTED_ORDER" if accepted_order and link["commitment_id"] == "com-001"
                    else "UNRESOLVED_IMPACT" if expected_classification == "UNKNOWN"
                    else "UNRESOLVED_ORDER_ACCEPTANCE"
                )
                assert link["link_status"] == expected_link_status
                assert link["evidence_refs"]
            foreign = http.get(f"/v1/orchestration/impacts/{impact_id}",
                               headers={**headers, "X-Tenant-ID": f"foreign_{tenant}"})
            assert foreign.status_code == 404
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(BusinessImpactLinkRecord).where(
                    BusinessImpactLinkRecord.tenant_id == tenant,
                    BusinessImpactLinkRecord.impact_id == impact_id,
                )) == 2
                assert db.scalar(select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == tenant,
                    AuditEventRecord.event_type == "orchestration.impact_link_unresolved",
                )) == (1 if accepted_order else 2)
    finally:
        _stop(server)
        engine.dispose()
