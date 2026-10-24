"""Real HTTP + worker P1 → Core → P2 → supplier impact → P3 proof.

Requires an explicitly approved, migrated disposable PostgreSQL database. The
test never creates, migrates, resets, or drops a database. P1 and Core must use
the same isolated database because P1's Core publisher writes through its
configured P1 engine.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.context.postgres_repository import InboundMessage, OrderContext
from app.core.models import (
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.feasibility.demo_seed import seed_upstream_demo_snapshots
from app.feasibility.persisted_sources import (
    OperationalSnapshotRecord,
    SupplierDelayEventRecord,
    read_snapshot,
)
from app.feasibility.service import evaluate
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord


def _approved_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL upstream E2E requires an explicit TEST_DATABASE_URL")
    if os.getenv("TEST_DATABASE_APPROVED") != "1":
        pytest.fail("TEST_DATABASE_APPROVED=1 is required")
    if not os.getenv("P1_DATABASE_URL"):
        pytest.skip("P1_DATABASE_URL is required to exercise the real P1 repository")
    parsed = make_url(url)
    p1_parsed = make_url(os.environ["P1_DATABASE_URL"])
    if not parsed.database or not any(
        token in parsed.database.lower() for token in ("test", "demo")
    ):
        pytest.fail("A named disposable test/demo database is required")
    if (
        parsed.database != p1_parsed.database
        or parsed.host != p1_parsed.host
        or parsed.port != p1_parsed.port
    ):
        pytest.fail(
            "P1_DATABASE_URL and TEST_DATABASE_URL must point to the same isolated database"
        )

    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        pytest.fail("This acceptance test requires the PostgreSQL dialect")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    with engine.connect() as connection:
        revisions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
    if len(script.get_heads()) != 1 or revisions != script.get_heads():
        pytest.fail(
            f"Database migration head {revisions!r} differs from repository head {script.get_heads()!r}"
        )
    return engine


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start(command: list[str], env: dict[str, str], log_path: Path | None = None):
    if log_path is None:
        return subprocess.Popen(
            [sys.executable, *command],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    with log_path.open("ab") as log:
        return subprocess.Popen(
            [sys.executable, *command],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _eventually(check, *, timeout: float = 25):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except httpx.ConnectError as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for durable upstream state: {last_error}")


def _create_context_and_confirm(
    http: httpx.Client, tenant: str, order_id: str, quantity: int, headers: dict[str, str]
) -> tuple[str, str, str]:
    envelope = {
        "tenant_id": tenant,
        "channel": "WHATSAPP",
        "provider_message_id": f"msg-{uuid4().hex}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Synthetic verified buyer",
        "received_at": "2026-10-23T09:00:00+08:00",
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": f"Please send {quantity} pcs burgers tomorrow before 3pm for {order_id}",
        "attachments": [],
    }
    ingest = http.post("/v1/messages/ingest", headers=headers, json=envelope)
    assert ingest.status_code == 201, ingest.text
    message_id = ingest.json()["message"]["message_id"]

    created = http.post(f"/v1/contexts/from-message/{message_id}", headers=headers)
    assert created.status_code == 201, created.text
    context = created.json()
    assert context["tenant_id"] == tenant and context["order_id"] == order_id, context
    assert context["status"] == "INFORMATION_READY", context
    assert context["customer_identity_status"] == "LINK_VERIFIED", context
    assert context["source_message_ids"] == [message_id]

    publish = http.post(
        f"/v1/contexts/{context['context_id']}/publish",
        headers={**headers, "X-Actor-ID": "user_staff_01"},
    )
    assert publish.status_code == 200, publish.text
    published_context = publish.json()
    commitment_id = published_context["core_commitment_id"]
    assert commitment_id

    manager_headers = {**headers, "X-Actor-ID": "user_manager_01"}
    current = http.get(f"/v1/commitments/{commitment_id}", headers=manager_headers)
    assert current.status_code == 200, current.text
    requested = current.json()
    assert requested["agreement_state"] == "REQUESTED"
    assert requested["terms"]["quantity"] == str(quantity)
    assert requested["terms"]["sku"] == "BURGER"
    assert requested["fulfilment_state"] == "NOT_STARTED"

    proposal_id = f"prop-upstream-{uuid4().hex}"
    offered = http.post(
        f"/v1/commitments/{commitment_id}/proposals",
        headers=manager_headers,
        json={
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "expected_commitment_version": requested["commitment_version"],
            "revised_terms": requested["terms"],
            "reason": "Synthetic customer order confirmation",
            "evidence_refs": [f"synthetic:proposal:{proposal_id}"],
        },
    )
    assert offered.status_code == 200, offered.text
    offered_body = offered.json()
    assert offered_body["commitment"]["agreement_state"] == "OFFERED"
    assert offered_body["commitment"]["fulfilment_state"] == "NOT_STARTED"

    accepted = http.post(
        f"/v1/commitments/{commitment_id}/confirm-proposal",
        headers=manager_headers,
        json={
            "proposal_id": proposal_id,
            "proposal_version": 1,
            "expected_commitment_version": offered_body["commitment"]["commitment_version"],
            "decision": "ACCEPT",
            "evidence_refs": [f"synthetic:customer-acceptance:{proposal_id}:v1"],
            "reason": "Authorized synthetic demo customer acceptance",
        },
    )
    assert accepted.status_code == 200, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["commitment"]["agreement_state"] == "CONFIRMED"
    assert accepted_body["commitment"]["fulfilment_state"] == "NOT_STARTED"
    return message_id, commitment_id, accepted_body["domain_event"]["event_id"]


def test_real_p1_context_to_p2_supplier_impact_to_p3_case_on_postgresql(tmp_path: Path) -> None:
    engine = _approved_engine()
    # P1's approved synthetic customer directory is intentionally allowlisted,
    # not dynamically generated. Use its two existing Burger King orders.
    tenant = "synthetic_tenant_a"
    key = "isolated-upstream-e2e-" + uuid4().hex
    manager_id = "user_manager_01"
    env = dict(
        os.environ,
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        P1_DATABASE_URL=os.environ["P1_DATABASE_URL"],
        MOUMANTAI_ISOLATED_E2E="1",
        MOUMANTAI_ISOLATED_E2E_KEY=key,
        MOUMANTAI_ISOLATED_E2E_MANAGER_ID=manager_id,
    )
    port = _free_port()
    server = worker = None
    server_log = tmp_path / "upstream-server.log"
    worker_log = tmp_path / "upstream-worker.log"
    try:
        with Session(engine) as db:
            existing_contexts = db.scalar(
                select(func.count())
                .select_from(OrderContext)
                .where(
                    OrderContext.tenant_id == tenant,
                    OrderContext.order_id.in_(("ORD-1001", "ORD-1002")),
                )
            )
            existing_commitments = db.scalar(
                select(func.count())
                .select_from(CommitmentRecord)
                .where(
                    CommitmentRecord.tenant_id == tenant,
                    CommitmentRecord.order_id.in_(("ORD-1001", "ORD-1002")),
                )
            )
        if existing_contexts or existing_commitments:
            pytest.fail(
                "The approved disposable DB already contains upstream E2E fixture rows; provision a fresh test DB"
            )

        server = _start(
            ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            env,
            server_log,
        )
        base_url = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base_url, timeout=8) as http:
            _eventually(lambda: server.poll() is None and http.get("/health").status_code == 200)
            headers = {
                "X-Tenant-ID": tenant,
                "X-Actor-ID": manager_id,
                "X-Isolated-E2E-Key": key,
            }

            target_message, target_id, target_confirmation = _create_context_and_confirm(
                http, tenant, "ORD-1001", 100, headers
            )
            control_message, control_id, control_confirmation = _create_context_and_confirm(
                http, tenant, "ORD-1002", 20, headers
            )

            with Session(engine) as db:
                from app.core.dependencies import RequestContext
                from app.core.service import CommitmentService

                context = RequestContext(
                    tenant_id=tenant,
                    actor_id="service_p2_feasibility",
                    actor_role="SERVICE",
                    correlation_id=f"corr-seed-{uuid4().hex}",
                )
                service = CommitmentService()
                target_commitment = service.get(db, context, target_id)
                control_commitment = service.get(db, context, control_id)
                seeded = seed_upstream_demo_snapshots(
                    db, tenant, target_commitment, control_commitment
                )
                assert seeded.created is True
                db.commit()

            with Session(engine) as db:
                replay_context = RequestContext(
                    tenant_id=tenant,
                    actor_id="service_p2_feasibility",
                    actor_role="SERVICE",
                    correlation_id=f"corr-seed-replay-{uuid4().hex}",
                )
                replay = seed_upstream_demo_snapshots(
                    db,
                    tenant,
                    CommitmentService().get(db, replay_context, target_id),
                    CommitmentService().get(db, replay_context, control_id),
                )
                assert replay.created is False
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OperationalSnapshotRecord)
                        .where(
                            OperationalSnapshotRecord.tenant_id == tenant,
                        )
                    )
                    == 2
                )

            # Reload the persisted versions and call the real P2 evaluator.
            # These calculations verify fixture/schema compatibility, not source authority.
            with Session(engine) as db:
                from app.core.dependencies import RequestContext
                from app.core.service import CommitmentService

                source_context = RequestContext(
                    tenant_id=tenant,
                    actor_id="service_p2_feasibility",
                    actor_role="SERVICE",
                    correlation_id=f"corr-read-snapshot-{uuid4().hex}",
                )
                persisted_before = read_snapshot(db, tenant, version=1)
                persisted_after = read_snapshot(db, tenant, version=2)
                target_commitment = CommitmentService().get(db, source_context, target_id)
                control_commitment = CommitmentService().get(db, source_context, control_id)
                assert (
                    evaluate(persisted_before, None, target_commitment).status.value == "FEASIBLE"
                )
                assert (
                    evaluate(persisted_after, None, target_commitment).status.value == "INFEASIBLE"
                )
                assert (
                    evaluate(persisted_after, None, control_commitment).status.value == "FEASIBLE"
                )

            worker = _start(["-m", "app.worker"], env, worker_log)

            def synthetic_baseline_rejected():
                with Session(engine) as db:
                    confirmation_rows = db.scalars(
                        select(OutboxEventRecord).where(
                            OutboxEventRecord.tenant_id == tenant,
                            OutboxEventRecord.event_id.in_(
                                (target_confirmation, control_confirmation)
                            ),
                        )
                    ).all()
                    processed = db.scalars(
                        select(ProcessedEventRecord).where(
                            ProcessedEventRecord.tenant_id == tenant,
                            ProcessedEventRecord.event_id.in_(
                                (target_confirmation, control_confirmation)
                            ),
                            ProcessedEventRecord.consumer_name == "p2_confirmed_evaluator",
                        )
                    ).all()
                    if (
                        len(confirmation_rows) == 2
                        and all(
                            row.attempts > 0
                            and row.status in {"FAILED", "DEAD_LETTER"}
                            and "synthetic" in (row.last_error or "").lower()
                            for row in confirmation_rows
                        )
                        and not processed
                    ):
                        return confirmation_rows
                    return None

            refused_confirmations = _eventually(synthetic_baseline_rejected)
            assert len(refused_confirmations) == 2
            with Session(engine) as db:
                commitments = db.scalars(
                    select(CommitmentRecord).where(
                        CommitmentRecord.tenant_id == tenant,
                        CommitmentRecord.commitment_id.in_((target_id, control_id)),
                    )
                ).all()
                assert all(row.feasibility_state == "NOT_ASSESSED" for row in commitments)
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(RecoveryCaseRecord)
                        .where(
                            RecoveryCaseRecord.tenant_id == tenant,
                        )
                    )
                    == 0
                )

            delay_response = http.post(
                "/v1/operations/events/supplier-delay",
                headers=headers,
                json=seeded.supplier_delay.model_dump(mode="json"),
            )
            assert delay_response.status_code == 200, delay_response.text
            delay_result = delay_response.json()
            impact_rows = {row["commitment_id"]: row for row in delay_response.json()["impacts"]}
            assert impact_rows[target_id]["classification"] == "CONFIRMED_IMPACT"
            assert impact_rows[control_id]["classification"] == "VERIFIED_UNAFFECTED"
            duplicate_delay = http.post(
                "/v1/operations/events/supplier-delay",
                headers=headers,
                json=seeded.supplier_delay.model_dump(mode="json"),
            )
            assert duplicate_delay.status_code == 200, duplicate_delay.text
            assert duplicate_delay.json()["impact_id"] == delay_result["impact_id"]

            def case_ready():
                with Session(engine) as db:
                    case = db.scalar(
                        select(RecoveryCaseRecord).where(
                            RecoveryCaseRecord.tenant_id == tenant,
                            RecoveryCaseRecord.commitment_id == target_id,
                        )
                    )
                    processed = db.scalar(
                        select(func.count())
                        .select_from(ProcessedEventRecord)
                        .where(
                            ProcessedEventRecord.tenant_id == tenant,
                            ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
                        )
                    )
                    return case if case is not None and processed == 1 else None

            case = _eventually(case_ready)
            assert worker.poll() is None
            with Session(engine) as db:
                target = db.get(CommitmentRecord, (tenant, target_id))
                control = db.get(CommitmentRecord, (tenant, control_id))
                assert target is not None and target.risk_state == "AT_RISK"
                assert target.feasibility_state == "INFEASIBLE"
                assert control is not None and control.risk_state == "NORMAL"
                assert control.feasibility_state == "FEASIBLE"
                assert target.fulfilment_state == "NOT_STARTED"
                assert control.fulfilment_state == "NOT_STARTED"

                delay_record = db.get(
                    SupplierDelayEventRecord,
                    (tenant, seeded.supplier_delay.change.event_id),
                )
                assert delay_record is not None
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(SupplierDelayEventRecord)
                        .where(
                            SupplierDelayEventRecord.tenant_id == tenant,
                            SupplierDelayEventRecord.event_id
                            == seeded.supplier_delay.change.event_id,
                        )
                    )
                    == 1
                )
                assert delay_record.before_snapshot_version == 1
                assert delay_record.after_snapshot_version == 2
                snapshots = db.scalars(
                    select(OperationalSnapshotRecord)
                    .where(
                        OperationalSnapshotRecord.tenant_id == tenant,
                    )
                    .order_by(OperationalSnapshotRecord.snapshot_version)
                ).all()
                assert len(snapshots) == 2
                assert snapshots[0].is_current is False and snapshots[1].is_current is True

                trigger = db.scalar(
                    select(RecoveryCaseTriggerRecord).where(
                        RecoveryCaseTriggerRecord.tenant_id == tenant,
                        RecoveryCaseTriggerRecord.case_id == case.case_id,
                    )
                )
                assert trigger is not None
                assert trigger.event_id
                assert trigger.assessment_id
                assert trigger.snapshot_id == seeded.after.operational.snapshot_id
                assert trigger.snapshot_version == 2
                assert trigger.assessment_provenance_status == "VERIFIED_AUTHORITATIVE"
                assert trigger.evidence_refs
                assert any("synthetic" in ref.lower() for ref in trigger.evidence_refs)
                assert (
                    db.scalar(
                        select(OutboxEventRecord).where(
                            OutboxEventRecord.tenant_id == tenant,
                            OutboxEventRecord.event_type == "commitment.at_risk",
                            OutboxEventRecord.status == "PUBLISHED",
                        )
                    )
                    is not None
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(RecoveryCaseRecord)
                        .where(
                            RecoveryCaseRecord.tenant_id == tenant,
                            RecoveryCaseRecord.commitment_id == control_id,
                        )
                    )
                    == 0
                )
                assert (
                    db.get(
                        ProcessedEventRecord, (tenant, trigger.event_id, "p3.recovery_trigger.v1")
                    )
                    is not None
                )

            # Prove read-after-restart against persisted P1 and P3 records.
            _stop(server)
            server = _start(
                ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                env,
                server_log,
            )
            with httpx.Client(base_url=base_url, timeout=8) as restarted_http:
                _eventually(
                    lambda: (
                        server.poll() is None and restarted_http.get("/health").status_code == 200
                    )
                )
                trigger_read = restarted_http.get(
                    f"/v1/recovery/cases/{target_id}/trigger", headers=headers
                )
                assert trigger_read.status_code == 200, trigger_read.text
                assert trigger_read.json()["storage_mode"] == "DURABLE_DATABASE"
                assert trigger_read.json()["commitment_id"] == target_id
                trigger_events = trigger_read.json()["trigger_events"]
                assert any(row["event_id"] == trigger.event_id for row in trigger_events)
            with Session(engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OutboxEventRecord)
                        .where(
                            OutboxEventRecord.tenant_id == tenant,
                            OutboxEventRecord.event_id.in_(
                                (target_confirmation, control_confirmation)
                            ),
                        )
                    )
                    >= 2
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(ProcessedEventRecord)
                        .where(
                            ProcessedEventRecord.tenant_id == tenant,
                            ProcessedEventRecord.event_id.in_(
                                (target_confirmation, control_confirmation)
                            ),
                            ProcessedEventRecord.consumer_name == "p2_confirmed_evaluator",
                        )
                    )
                    == 0
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(ProcessedEventRecord)
                        .where(
                            ProcessedEventRecord.tenant_id == tenant,
                            ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
                        )
                    )
                    == 1
                )
                assert db.get(InboundMessage, target_message) is not None
                assert db.get(InboundMessage, control_message) is not None
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OrderContext)
                        .where(
                            OrderContext.tenant_id == tenant,
                            OrderContext.core_commitment_id.in_((target_id, control_id)),
                        )
                    )
                    == 2
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(CommitmentRecord)
                        .where(
                            CommitmentRecord.tenant_id == tenant,
                            CommitmentRecord.fulfilment_state == "FULFILLED",
                        )
                    )
                    == 0
                )
    finally:
        _stop(worker)
        _stop(server)
        engine.dispose()
