"""Real migrated PostgreSQL + SQLite; explicit upstream test authority only.

Nothing in this file is installed in production dependency wiring.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace

from alembic import command as alembic_command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.communication.confirmation_schemas import CreateConfirmation
from app.communication.demo_policy import SyntheticScope
from app.communication.followup import FollowUpService, RuntimeFollowUpAuthority
from app.communication.followup_schemas import ReminderAuthorization, ScheduleFollowUp, SLAPolicy
from app.communication.models import (FollowUpTaskRecord, ReminderAttemptRecord,
    ConfirmationDecisionRecord, ConfirmationSessionRecord, OutboundMessageRecord)
from app.communication.outbound import OutboundService
from app.communication.preferences import PreferenceCommand, PreferenceService
from app.communication.providers import LocalMockProvider
from app.communication.tests.test_confirmation_integration import fixture_sent, confirmation_service
from app.communication.tests.test_confirmations import FixtureInbound, text, respond
from app.communication.tests.test_migration_persistence import migrated, config
from app.communication.tests.test_outbound import FixtureSendAuthority
from app.communication.tests.test_requests import NOW, OWNER, expect_error
from app.communication.tests.test_review import MANAGER
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord, CommitmentProposalRecord, OutboxEventRecord
from app.main import app
from app.db.base import Base
from app.core.events import create_domain_event
from app.core.outbox import to_domain_event
import app.communication.confirmations as confirmation_module
import app.communication.followup as followup_module


class TestPolicyAuthority:
    __test__ = False
    def __init__(self):
        self.denied = False
        self.overrides = {}

    def authorize(self, db, context, *, action, confirmation_id, policy_digest, now):
        if self.denied or context.actor_id != MANAGER.actor_id or context.actor_role != "MANAGER":
            raise DomainError("TEST_REMINDER_POLICY_DENIED", "Test-only policy denies this action", status_code=403)
        return ReminderAuthorization(**{ "tenant_id": context.tenant_id, "actor_id": context.actor_id,
            "action": action, "confirmation_id": confirmation_id, "policy_digest": policy_digest,
            "evidence_refs": ["test:approved-repeat-contact-policy"],
            "expires_at": now + timedelta(minutes=10), **self.overrides})


def preferences(db):
    # Typed P1 directory PORT fixture, NOT an identity database or runtime grant.
    contact = SimpleNamespace(channel="MOCK_EMAIL", sender_identity_id="identity_001")
    customer = SimpleNamespace(tenant_id="tenant_a", customer_id="customer_001", active=True, verified_contacts=[contact])
    directory = SimpleNamespace(get_customer=lambda *args: customer, get_contact_for_channel=lambda *args: contact)
    return PreferenceService(db, SyntheticScope(True, frozenset({"tenant_a"})), directory)


def seed(db):
    sent, drafts, reviews = fixture_sent(db)
    confirmations = confirmation_service(db, drafts, reviews, FixtureInbound())
    issued = confirmations.issue(MANAGER, CreateConfirmation(outbound_id=sent.outbound_id), now=NOW)
    pref = preferences(db)
    pref.save(MANAGER, PreferenceCommand(request_key="followup_consent_key", customer_id="customer_001",
        channel="MOCK_EMAIL", consent_status="OPTED_IN", consent_evidence_ref="synthetic:consent:followup_explicit",
        source="SYNTHETIC_FIXTURE", consent_expires_at=NOW + timedelta(hours=4), expected_version=0), now=NOW)
    return issued, drafts, reviews


def service(db, drafts, reviews, authority=None, outcome="SENT"):
    confirmations = confirmation_service(db, drafts, reviews, FixtureInbound())
    outbound = OutboundService(db, drafts, reviews, FixtureSendAuthority(), LocalMockProvider(outcome))
    return FollowUpService(db, authority or TestPolicyAuthority(), confirmations, outbound, preferences(db))


def command(issued, **policy):
    return ScheduleFollowUp(confirmation_id=issued.confirmation.confirmation_id, request_key="followup_schedule_key",
        policy=SLAPolicy(response_sla_seconds=60, minimum_interval_seconds=60, escalation_delay_seconds=120,
                         timezone="UTC", **policy))


@pytest.fixture
def graph(migrated):
    engine, cfg = migrated
    with Session(engine) as db:
        issued, drafts, reviews = seed(db)
        task = service(db, drafts, reviews).schedule(MANAGER, command(issued), now=NOW)
    return engine, cfg, issued, drafts, reviews, task


def test_reminder_once_then_escalation_is_durable_and_core_unchanged(graph):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        assert runner.run_due(MANAGER, now=NOW + timedelta(seconds=59)) == []
        result = runner.run_due(MANAGER, now=NOW + timedelta(seconds=60))[0]
        assert result.reminders_sent == 1 and result.status == "WAITING"
        assert runner.run_due(MANAGER, now=NOW + timedelta(seconds=60)) == []
        # Restarted worker/service, no duplicate provider intent after restart.
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        replay = runner.schedule(MANAGER, command(issued), now=NOW + timedelta(seconds=61))
        assert replay.task_id == task.task_id and replay.reminders_sent == 1
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=120)).status == "WAITING"
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=180)).status == "ESCALATED"
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=181)).status == "ESCALATED"
    with Session(engine) as db:
        attempts = db.scalars(select(ReminderAttemptRecord)).all()
        assert len(attempts) == 1 and attempts[0].status == "SENT"
        assert attempts[0].provider_reference.startswith("mock_")
        assert db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id)).state == "AWAITING_RESPONSE"
        core = db.get(CommitmentRecord, ("tenant_a", "com_001"))
        assert (core.agreement_state, core.fulfilment_state, core.commitment_version) == ("OFFERED", "NOT_STARTED", 11)
        assert db.scalar(select(func.count()).select_from(OutboundMessageRecord)) == 1
        for model in (AuditEventRecord, OutboxEventRecord):
            assert db.scalar(select(func.count()).select_from(model).where(model.event_type == "communication.escalation_required")) == 1


@pytest.mark.parametrize("outcome", ["FAILED", "DELIVERY_UNKNOWN"])
def test_failed_or_uncertain_reminder_escalates_and_is_never_retried(graph, outcome):
    engine, _, _, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews, outcome=outcome)
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60)).status == "ESCALATED"
        assert runner.run_due(MANAGER, now=NOW + timedelta(seconds=600)) == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 1
        assert db.scalar(select(ReminderAttemptRecord.status)) == outcome
        assert db.scalar(select(FollowUpTaskRecord.reminders_sent)) == 0


@pytest.mark.parametrize("change,expected", [
    ("stale", "BLOCKED"), ("approval", "BLOCKED"), ("consent", "CANCELLED"),
    ("identity", "BLOCKED"), ("expired", "CANCELLED"), ("revoked", "CANCELLED"),
    ("contact_hours", "BLOCKED"), ("missing_preferences", "BLOCKED"),
])
def test_dispatch_rechecks_all_authority_and_consent(graph, change, expected):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        if change == "stale":
            db.get(CommitmentProposalRecord, ("tenant_a", "proposal_001")).status = "SUPERSEDED"
        if change == "approval":
            reviews.overrides["existing_review_status"] = "REVOKED"
        if change == "consent":
            pref = runner.preferences.record("tenant_a", "customer_001", "MOCK_EMAIL")
            pref.consent_status, pref.revoked_at = "OPTED_OUT", NOW
        if change == "identity":
            runner.preferences.contacts.directory.get_contact_for_channel = lambda *args: None
        if change == "contact_hours":
            # Consent journal is revalidated too; use service to change it legitimately.
            saved = runner.preferences.view(runner.preferences.record("tenant_a", "customer_001", "MOCK_EMAIL"))
            runner.preferences.save(MANAGER, PreferenceCommand(request_key="narrow_contact_hours", customer_id="customer_001",
                channel="MOCK_EMAIL", consent_status="OPTED_IN", consent_evidence_ref="synthetic:consent:narrow_hours",
                source="SYNTHETIC_FIXTURE", consent_expires_at=NOW + timedelta(hours=4), expected_version=saved.version,
                timezone="UTC", allowed_contact_hours={"start_hour": 12, "end_hour": 13}), now=NOW)
        if change in {"expired", "revoked"}:
            session = db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id))
            if change == "expired": session.expires_at = NOW + timedelta(seconds=30)
            else: session.revoked_at = NOW
        db.commit()
        if change == "missing_preferences": runner.preferences = None
        result = runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60))
        assert result.status == expected
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 0


@pytest.mark.parametrize("intent", ["ACCEPT", "REJECT", "COUNTEROFFER"])
def test_terminal_response_cancels_followup_in_same_transaction(graph, intent):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        value = text(issued, intent)
        if intent == "COUNTEROFFER": value += ' changes:{"quantity":"80"}'
        reply = respond(runner.confirmations, issued, runner.confirmations.inbound, value)
        assert reply.intent == intent
    with Session(engine) as db:
        row = db.get(FollowUpTaskRecord, ("tenant_a", task.task_id))
        assert row.status == "CANCELLED" and row.reason_code == "CUSTOMER_" + intent and row.next_due_at is None
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 1
        assert service(db, drafts, reviews).run_due(MANAGER, now=NOW + timedelta(seconds=60)) == []


def test_ambiguous_reply_keeps_task_and_revoke_cancels_it(graph):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        respond(runner.confirmations, issued, runner.confirmations.inbound, "OK")
        assert db.get(FollowUpTaskRecord, ("tenant_a", task.task_id)).status == "WAITING"
        db.rollback()
        runner.confirmations.revoke(MANAGER, issued.confirmation.confirmation_id, now=NOW)
    with Session(engine) as db:
        assert db.get(FollowUpTaskRecord, ("tenant_a", task.task_id)).status == "CANCELLED"


def test_response_and_followup_cancellation_rollback_together(graph, monkeypatch):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        def fail(): raise OperationalError("commit", {}, RuntimeError("test failure"))
        monkeypatch.setattr(db, "commit", fail)
        expect_error("CONFIRMATION_STORAGE_UNAVAILABLE", lambda: respond(
            runner.confirmations, issued, runner.confirmations.inbound), 503)
    with Session(engine) as db:
        assert db.get(FollowUpTaskRecord, ("tenant_a", task.task_id)).status == "WAITING"
        assert db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id)).consumed_at is None
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "communication.followup_cancelled")) == 0


def test_policy_grants_idempotency_and_tenant_boundaries(graph):
    engine, _, issued, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        expect_error("FOLLOWUP_IDEMPOTENCY_CONFLICT", lambda: runner.schedule(MANAGER,
            command(issued, max_reminders=2), now=NOW), 409)
        different_key = command(issued).model_copy(update={"request_key": "another_schedule_key"})
        expect_error("FOLLOWUP_ALREADY_SCHEDULED", lambda: runner.schedule(MANAGER, different_key, now=NOW), 409)
        wrong = RequestContext("tenant_b", MANAGER.actor_id, "MANAGER", "corr-wrong-tenant")
        expect_error("FOLLOWUP_NOT_FOUND", lambda: runner.process(wrong, task.task_id, now=NOW), 404)
        expect_error("TEST_REMINDER_POLICY_DENIED", lambda: runner.process(OWNER, task.task_id, now=NOW), 403)
        runner.authority.overrides["confirmation_id"] = "different-confirmation"
        expect_error("FOLLOWUP_FORBIDDEN", lambda: runner.process(MANAGER, task.task_id, now=NOW), 403)
        runner.authority.overrides = {}
        cancelled = runner.cancel(MANAGER, task.task_id, "Manager cancelled", now=NOW)
        assert cancelled.status == "CANCELLED"
        assert runner.schedule(MANAGER, command(issued), now=NOW).status == "CANCELLED"


def test_migration_parent_rollback_preserves_all_other_tables(graph):
    engine, cfg, _, _, _, _ = graph
    scripts = ScriptDirectory.from_config(cfg)
    heads = scripts.get_heads()
    assert len(heads) == 1 and "0015_p4_followup" in {r.revision for r in scripts.iterate_revisions(heads[0], "base")}
    assert scripts.get_revision("0015_p4_followup").down_revision == "0014_merge_p3_p4_confirmations"
    # Exercise the follow-up migration's own parent boundary. Later additive
    # migrations have their own tables and are outside this rollback assertion.
    alembic_command.downgrade(cfg, "0015_p4_followup")
    before = set(inspect(engine).get_table_names())
    alembic_command.downgrade(cfg, "0014_merge_p3_p4_confirmations")
    assert set(inspect(engine).get_table_names()) == before - {"communication_followup_tasks", "communication_reminder_attempts"}
    with Session(engine) as db:
        assert db.get(CommitmentRecord, ("tenant_a", "com_001")).agreement_state == "OFFERED"
        assert db.scalar(select(func.count()).select_from(ConfirmationSessionRecord)) == 1
    alembic_command.upgrade(cfg, "head")
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(FollowUpTaskRecord)) == 0


def test_runtime_reminder_routes_are_mounted_and_fail_closed(monkeypatch):
    monkeypatch.delenv("P4_RUNTIME_MODE", raising=False)
    with TestClient(app) as client:
        assert {"/v1/follow-ups", "/v1/follow-ups/run-due", "/v1/follow-ups/{task_id}/cancel"} <= set(app.openapi()["paths"])
        for method, path, payload in [
            ("get", "/v1/follow-ups", None), ("post", "/v1/follow-ups/run-due", None),
            ("post", "/v1/follow-ups", {"confirmation_id": "test", "request_key": "schedule_key"}),
            ("post", "/v1/follow-ups/test/cancel", {"reason": "cancel"}),
        ]:
            response = getattr(client, method)(path, headers={"X-Tenant-ID": "tenant_a", "X-Actor-ID": MANAGER.actor_id},
                **({"json": payload} if payload is not None else {}))
            assert response.status_code == 503 and response.json()["code"] == "FOLLOWUP_AUTHORITY_UNAVAILABLE"


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_two_workers_create_one_durable_reminder(graph):
    engine, _, _, drafts, reviews, task = graph
    barrier = Barrier(2)
    def worker():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return service(db, drafts, reviews).process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60))
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: worker(), range(2)))
    assert len(results) == 2
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 1
        assert db.scalar(select(FollowUpTaskRecord.reminders_sent)) == 1


def test_result_commit_failure_preserves_unknown_and_never_resubmits(graph, monkeypatch):
    engine, _, _, drafts, reviews, task = graph
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        original = db.commit
        count = 0
        def commit():
            nonlocal count
            count += 1
            if count == 2: raise OperationalError("result commit", {}, RuntimeError("test"))
            original()
        monkeypatch.setattr(db, "commit", commit)
        result = runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60))
        assert result.status == "DISPATCHING"
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=61)).status == "DISPATCHING"
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 1
        assert db.scalar(select(ReminderAttemptRecord.status)) == "DELIVERY_UNKNOWN"
        db.rollback()
        result = runner.run_due(MANAGER, now=NOW + timedelta(seconds=180))[0]
        assert result.status == "ESCALATED" and result.reason_code == "REMINDER_OUTCOME_UNRECONCILED"
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 1


def test_followup_migrated_schema_exactly_matches_models(migrated):
    engine, _ = migrated
    tables = {"communication_followup_tasks", "communication_reminder_attempts"}
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection, opts={
            "include_object": lambda obj, name, kind, reflected, compare_to: name in tables if kind == "table" else True,
        }), Base.metadata)
        assert differences == []


@pytest.mark.parametrize("maximum", [0, 2, 3])
def test_maximum_reminders_and_minimum_spacing(migrated, maximum):
    engine, _ = migrated
    with Session(engine) as db:
        issued, drafts, reviews = seed(db)
        runner = service(db, drafts, reviews)
        task = runner.schedule(MANAGER, command(issued, max_reminders=maximum), now=NOW)
        for number in range(maximum):
            when = NOW + timedelta(seconds=60 * (number + 1))
            result = runner.process(MANAGER, task.task_id, now=when)
            assert result.reminders_sent == number + 1
            result = runner.process(MANAGER, task.task_id, now=when + timedelta(seconds=1))
            assert result.reminders_sent == number + 1
        result = runner.process(MANAGER, task.task_id, now=task.escalation_at)
        assert result.status == "ESCALATED" and result.reminders_sent == maximum
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == maximum


def test_authority_revoked_between_claim_and_submission_never_calls_provider(graph, monkeypatch):
    engine, _, _, drafts, reviews, task = graph
    with Session(engine) as db:
        authority = TestPolicyAuthority()
        runner = service(db, drafts, reviews, authority)
        original = db.commit
        def revoke():
            original()
            authority.denied = True
        monkeypatch.setattr(db, "commit", revoke)
        expect_error("TEST_REMINDER_POLICY_DENIED", lambda: runner.process(MANAGER, task.task_id,
            now=NOW + timedelta(seconds=60)), 403)
    with Session(engine) as db:
        row = db.scalar(select(ReminderAttemptRecord))
        assert row.status == "DELIVERY_UNKNOWN" and row.provider_reference is None
        assert row.finished_at is None


@pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)
def test_response_racing_scheduler_has_no_deadlock_or_post_response_send(graph):
    engine, _, issued, drafts, reviews, task = graph
    barrier = Barrier(2)
    def response():
        with Session(engine) as db:
            runner = service(db, drafts, reviews)
            barrier.wait(timeout=10)
            return respond(runner.confirmations, issued, runner.confirmations.inbound,
                now=NOW + timedelta(seconds=60)).intent
    def due():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return service(db, drafts, reviews).process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60)).status
    with ThreadPoolExecutor(max_workers=2) as workers:
        f1, f2 = workers.submit(response), workers.submit(due)
        assert f1.result(timeout=20) == "ACCEPT"
        assert f2.result(timeout=20) in {"WAITING", "CANCELLED"}
    with Session(engine) as db:
        assert db.get(FollowUpTaskRecord, ("tenant_a", task.task_id)).status == "CANCELLED"
        assert service(db, drafts, reviews).run_due(MANAGER, now=NOW + timedelta(seconds=120)) == []
        attempts = db.scalars(select(ReminderAttemptRecord)).all()
        assert len(attempts) <= 1
        session = db.get(ConfirmationSessionRecord, ("tenant_a", issued.confirmation.confirmation_id))
        for attempt in attempts:
            assert attempt.started_at <= session.consumed_at


def test_event_envelopes_round_trip_v1_with_approved_counteroffer_changes(graph, monkeypatch):
    engine, _, issued, drafts, reviews, task = graph
    produced = {}
    def capture(**kwargs):
        value = create_domain_event(**kwargs)
        produced[value.event_id] = value
        return value
    monkeypatch.setattr(confirmation_module, "create_domain_event", capture)
    monkeypatch.setattr(followup_module, "create_domain_event", capture)
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=60))
        decision = respond(runner.confirmations, issued, runner.confirmations.inbound,
            text(issued, "COUNTEROFFER") + ' changes:{"quantity":"80"}', now=NOW + timedelta(seconds=61))
    with Session(engine) as db:
        assert produced
        for event_id, original in produced.items():
            persisted = db.get(OutboxEventRecord, event_id)
            restored = to_domain_event(persisted)
            assert restored.model_dump(mode="json") == original.model_dump(mode="json")
            assert restored.schema_version == 1 and restored.tenant_id == "tenant_a"
            assert restored.commitment_id == "com_001" and restored.correlation_id == MANAGER.correlation_id
        outcome = db.scalar(select(OutboxEventRecord).where(
            OutboxEventRecord.event_type == "confirmation.counteroffer_received"))
        assert outcome.payload["proposal_id"] == issued.confirmation.reference.proposal_id
        assert outcome.payload["proposal_version"] == issued.confirmation.reference.proposal_version
        assert not {"recovery_case_id", "plan_id", "plan_version"} & outcome.payload.keys()
        stored = db.get(ConfirmationDecisionRecord, ("tenant_a", outcome.payload["decision_id"]))
        assert stored.proposed_changes == {"quantity": "80"} and stored.attempt_id == decision.attempt_id
        assert outcome.payload["proposed_changes"] == stored.proposed_changes
        audit = db.scalar(select(AuditEventRecord).where(
            AuditEventRecord.event_type == "confirmation.counteroffer_received"))
        assert audit.new_state["proposed_changes"] == stored.proposed_changes
        for original in produced.values():
            if original.event_type != "confirmation.counteroffer_received":
                assert "proposed_changes" not in original.payload
        # Existing public history cannot serve as a decision_id-keyed trusted
        # lookup contract: document the gap, do not silently access P4 from P3.
        history = service(db, drafts, reviews).confirmations.history(MANAGER, issued.confirmation.confirmation_id)
        assert history[0].proposed_changes == {"quantity": "80"}
        assert "decision_id" not in history[0].model_dump()


def test_real_clock_is_rechecked_after_claim_before_provider_effect(graph, monkeypatch):
    engine, _, _, drafts, reviews, task = graph
    instant = [NOW + timedelta(seconds=60)]
    real_utc = followup_module.utc
    monkeypatch.setattr(followup_module, "utc", lambda value=None: real_utc(value) if value is not None else instant[0])
    with Session(engine) as db:
        runner = service(db, drafts, reviews)
        original = db.commit
        def advance():
            original()
            instant[0] = NOW + timedelta(days=2)
        monkeypatch.setattr(db, "commit", advance)
        expect_error("FOLLOWUP_CONFIRMATION_INACTIVE", lambda: runner.process(MANAGER, task.task_id), 409)
    with Session(engine) as db:
        attempt = db.scalar(select(ReminderAttemptRecord))
        assert attempt.status == "DELIVERY_UNKNOWN" and attempt.provider_reference is None and attempt.finished_at is None


def test_default_sla_fits_confirmation_and_late_scheduling_does_not_extend_deadline(migrated):
    engine, _ = migrated
    with Session(engine) as db:
        issued, drafts, reviews = seed(db)
        runner = service(db, drafts, reviews)
        default = ScheduleFollowUp(confirmation_id=issued.confirmation.confirmation_id, request_key="default_sla_key")
        task = runner.schedule(MANAGER, default, now=NOW + timedelta(seconds=120))
        assert task.next_due_at == NOW + timedelta(seconds=300)
        assert task.escalation_at == NOW + timedelta(seconds=600)
        assert task.escalation_at < issued.confirmation.expires_at
        assert runner.process(MANAGER, task.task_id, now=NOW + timedelta(seconds=300)).reminders_sent == 1
