"""Real module services + actual migrated PostgreSQL. No successful authority double.

The journey intentionally asserts the CURRENT Core 503 boundary rather than
inventing a Core transition. That is a persisted module integration test.
"""
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, func, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app.main import app
from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError
from app.core.models import CommitmentRecord, CommitmentProposalRecord, OutboxEventRecord, AuditEventRecord
from app.core.outbox import OutboxDispatcher, to_domain_event
from app.core.manager_approval import ManagerApprovalService, ManagerApprovalRecord
from app.feasibility.pipeline_fixtures import build_pipeline_example
from app.feasibility.supplier_pipeline import SupplierDelayInputs
from app.feasibility.persisted_sources import stage_snapshot, PersistedSupplierDelayProcessor
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.recovery.durable_plans import DurablePlanService
from app.recovery.durable_communication import DurableCommunicationHandoff, RequestCommunicationInput
from app.worker import configure_isolated_subscribers
from app.context.postgres_repository import PostgresMessageRepository, P1Base
from app.context.customer_directory import SyntheticCustomerDirectory
from app.context.association_service import AssociationService
from app.context.schemas import RawMessageEnvelope
from app.context.ingestion import IngestionService
from app.communication.challenge_delivery import configure_isolated_delivery_sink, parse_customer_reply
from app.communication.models import (ConfirmationSessionRecord, ConfirmationDecisionRecord,
    FollowUpTaskRecord, ReminderAttemptRecord, RecipientPreferenceRecord)
from app.communication.core_confirmation_bridge import attempt_existing_core_command, build_core_confirmation_consumer
from app.communication.followup_schemas import SLAPolicy
from app.communication.templates import fingerprint
from app.communication.worker_adapter import run_isolated_reminder_tick
from app.communication.isolated_app import PrivateInboundGateway
from app.communication.tests.test_migration_persistence import migrated

TENANT = "synthetic_tenant_a"
MANAGER = RequestContext(TENANT, "user_manager_01", "MANAGER", "corr_trusted_runtime")
PROCESSOR = RequestContext(TENANT, "service_core", "SERVICE", "corr_trusted_processor")
pytestmark = pytest.mark.parametrize("migrated", ["postgresql"], indirect=True)


def seed_approved_proposal(engine, key):
    raw = build_pipeline_example(mode="complete")
    payload = json.dumps(raw.model_dump(mode="json", exclude_computed_fields=True)).replace(raw.request.change.tenant_id, TENANT)
    for row in raw.before_commitments:
        payload = payload.replace(row.customer_id, "cust_bk")
    payload = payload.replace(raw.request.change.event_id, "evt_" + uuid4().hex)
    inputs = SupplierDelayInputs.model_validate_json(payload)
    with Session(engine) as db:
        for row in inputs.before_commitments:
            # Explicit operational starting fixture, not an acceptance of the NEW proposal.
            db.add(CommitmentRecord(tenant_id=TENANT, commitment_id=row.commitment_id, order_id=row.order_id,
                customer_id=row.customer_id, terms=row.terms.model_dump(mode="json"), agreement_state="CONFIRMED",
                feasibility_state="NOT_ASSESSED", risk_state="NORMAL", recovery_state="NONE",
                fulfilment_state="NOT_STARTED", commitment_version=row.commitment_version,
                evidence_refs=row.evidence_refs, updated_at=row.updated_at))
        stage_snapshot(db, inputs.before, current=True)
        stage_snapshot(db, inputs.after)
        db.commit()
        PersistedSupplierDelayProcessor().process(db, MANAGER, inputs.request)
    dispatcher = OutboxDispatcher()
    configure_isolated_subscribers(dispatcher)
    for _ in range(3):
        with Session(engine) as dispatch_session:
            dispatcher.process_outbox_batch(dispatch_session, batch_size=50)
    with Session(engine) as db:
        core = db.get(CommitmentRecord, (TENANT, "com-001"))
        case = db.scalar(select(RecoveryCaseRecord).where(RecoveryCaseRecord.tenant_id == TENANT,
            RecoveryCaseRecord.commitment_id == core.commitment_id))
        assert case is not None
        trigger = db.scalar(select(RecoveryCaseTriggerRecord).where(RecoveryCaseTriggerRecord.tenant_id == TENANT,
            RecoveryCaseTriggerRecord.case_id == case.case_id))
        plans = DurablePlanService().generate(db, MANAGER, core.commitment_id,
            expected_commitment_version=core.commitment_version, assessment_id=trigger.assessment_id)
        plan = next(row for row in plans if row.option_id == "revised_schedule")
        version = db.get(CommitmentRecord, (TENANT, "com-001")).commitment_version
        approval = ManagerApprovalService().decide(db, MANAGER, key, plan.plan_id, decision="APPROVED",
            expected_plan_version=plan.plan_version, expected_commitment_version=version,
            expected_snapshot_version=plan.snapshot_version, idempotency_key="approve_" + uuid4().hex, reason="Isolated trusted integration")
        assert approval.approval_id and approval.audit_id
        return DurableCommunicationHandoff().request(db, MANAGER, key, plan.plan_id,
            RequestCommunicationInput(expected_plan_version=plan.plan_version, expected_commitment_version=version,
                                      expected_snapshot_version=plan.snapshot_version))


@pytest.fixture
def runtime(migrated, monkeypatch):
    engine, _ = migrated
    if engine.dialect.name != "postgresql": pytest.skip("Trusted runtime requires actual PostgreSQL")
    keys = {name: uuid4().hex + uuid4().hex for name in ("manager", "processor", "worker", "challenge")}
    for name, value in {
        "P4_TRUSTED_ISOLATED":"1", "APP_ENV":"synthetic", "P4_RUNTIME_MODE":"SYNTHETIC",
        "P4_SYNTHETIC_TENANTS":TENANT, "MOUMANTAI_ISOLATED_E2E":"1",
        "MOUMANTAI_ISOLATED_E2E_KEY":keys["manager"], "MOUMANTAI_ISOLATED_E2E_MANAGER_ID":MANAGER.actor_id,
        "P4_ISOLATED_PROCESSOR_KEY":keys["processor"], "P4_ISOLATED_WORKER_KEY":keys["worker"],
        "P4_CHALLENGE_SIGNING_KEY":keys["challenge"],
        "P4_ISOLATED_REMINDER_POLICY_DIGEST":fingerprint(SLAPolicy(response_sla_seconds=60,
            minimum_interval_seconds=60, escalation_delay_seconds=60).model_dump(mode="json")),
    }.items(): monkeypatch.setenv(name, value)
    # Latest Main's real 0016 migration must supply P1 tables. No create_all or
    # alternate schema bootstrap is allowed to hide a missing migration.
    assert inspect(engine).has_table("inbound_messages", schema="p1_dev")
    handoff = seed_approved_proposal(engine, keys["manager"])
    received = []
    configure_isolated_delivery_sink(received.append)
    previous = app.dependency_overrides.copy()
    def database():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db] = database
    headers = {"X-Tenant-ID":TENANT, "X-Actor-ID":MANAGER.actor_id, "X-Isolated-E2E-Key":keys["manager"]}
    processor_headers = {"X-Tenant-ID":TENANT, "X-Actor-ID":"service_core", "X-P4-Processor-Key":keys["processor"]}
    try:
        with TestClient(PrivateInboundGateway(app)) as client:
            yield client, engine, handoff, received, headers, processor_headers, keys
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        configure_isolated_delivery_sink(None)


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def send_approved(runtime, *, expected_status="SENT", expected_http=200):
    client, engine, handoff, received, headers, _, _ = runtime
    now = datetime.now(timezone.utc)
    checked(client.post("/v1/communications/recipient-preferences", headers=headers, json={
        "request_key":"consent_" + uuid4().hex, "customer_id":"cust_bk", "channel":"MOCK_WHATSAPP",
        "consent_status":"OPTED_IN", "consent_evidence_ref":"synthetic:consent:trusted_runtime_" + uuid4().hex,
        "source":"SYNTHETIC_FIXTURE", "consent_expires_at":(now+timedelta(hours=2)).isoformat(), "expected_version":0}))
    request = checked(client.post("/v1/communications/requests", headers=headers, json={"source_event_id":handoff.source_event_id}))
    assert request["request_status"] == "READY_FOR_DRAFTING"
    base = "/v1/communications/" + request["communication_id"]
    draft = checked(client.post(base+"/prepare", headers=headers, json={"template_key":"delivery_change_secure"}))
    assert draft["template_version"] == 2 and "CONFIRM <confirmation_id> <secure_code>" in draft["body"]
    checked(client.post(base+"/drafts/"+draft["draft_id"]+"/approve", headers=headers,
        json={"request_key":"review_"+uuid4().hex,"expected_content_hash":draft["content_hash"]}))
    command = {"request_key":"send_"+uuid4().hex,"expected_content_hash":draft["content_hash"]}
    response=client.post(base+"/drafts/"+draft["draft_id"]+"/send", headers=headers,json=command)
    if expected_http!=200:
        assert response.status_code==expected_http,response.text
        return request,draft,response
    sent = checked(response)
    assert sent["status"] == expected_status and len(received) == (1 if expected_status=="SENT" else 0)
    assert checked(client.post(base+"/drafts/"+draft["draft_id"]+"/send", headers=headers,json=command))["outbound_id"] == sent["outbound_id"]
    assert len(received) == (1 if expected_status=="SENT" else 0)
    return request, draft, sent


def persist_p1_reply(engine, receipt, *, sender="+60123456789", text=None):
    body = text or receipt.challenge.body.split("\n\n")[-1]
    repository = PostgresMessageRepository(engine)
    raw = RawMessageEnvelope(tenant_id=TENANT, channel="WHATSAPP", provider_message_id="p1_"+uuid4().hex,
        sender_identity_id=sender, sender_alias="Synthetic sender", received_at=datetime.now(timezone.utc), text=body)
    ingested = IngestionService(repository).ingest(raw, TENANT)
    message = repository.get(TENANT, ingested.message.message_id)
    association = AssociationService(SyntheticCustomerDirectory()).evaluate_association(message)
    repository.save_association(association)
    return ingested.message.message_id


def schedule(client, headers, confirmation_id):
    policy=SLAPolicy(response_sla_seconds=60, minimum_interval_seconds=60, escalation_delay_seconds=60)
    return checked(client.post("/v1/follow-ups", headers=headers, json={"confirmation_id":confirmation_id,
        "request_key":"schedule_"+uuid4().hex,"policy":policy.model_dump(mode="json")}))


def test_real_p1_reply_persists_acceptance_and_cancels_reminders_but_core_is_blocked(runtime):
    client, engine, handoff, received, headers, processor_headers, _ = runtime
    request, draft, sent = send_approved(runtime)
    receipt = received[0]
    confirmation_id, secret, _ = parse_customer_reply(receipt.challenge.body.split("\n\n")[-1])
    task = schedule(client, headers, confirmation_id)
    assert secret not in repr(receipt) and secret not in json.dumps(sent)
    assert secret not in client.get("/v1/confirmations", headers=headers).text
    # P1's existing provisional raw message API cannot expose reply codes to a
    # manager/browser; only a separate authenticated processor can use it.
    assert client.get("/v1/messages",headers=headers).status_code==403
    message_id = persist_p1_reply(engine, receipt)
    result = checked(client.post("/v1/confirmations/process-inbound", headers=processor_headers, json={"inbound_message_id":message_id}))
    assert result["intent"] == "ACCEPT"
    with Session(engine) as db:
        session = db.get(ConfirmationSessionRecord, (TENANT, confirmation_id))
        assert session.state == "ACCEPTED" and session.token_digest != secret
        assert db.get(FollowUpTaskRecord, (TENANT, task["task_id"])).status == "CANCELLED"
        row = db.scalar(select(OutboxEventRecord).where(OutboxEventRecord.tenant_id==TENANT,
            OutboxEventRecord.event_type=="confirmation.accepted"))
        event = to_domain_event(row)
        assert event.schema_version == 1 and event.causation_id == message_id
        assert event.payload["proposal_id"] == handoff.proposal_id
        assert not {"recovery_case_id","plan_id","plan_version"} & event.payload.keys()
        with pytest.raises(DomainError) as caught:
            attempt_existing_core_command(db, MANAGER, event)
        assert caught.value.code == "P4_CONFIRMATION_AUTHORITY_UNAVAILABLE"
        db.rollback()
        with pytest.raises(DomainError) as missing:
            build_core_confirmation_consumer(None)(db,event)
        assert missing.value.code == "P5_VERIFIED_CONFIRMATION_PORT_UNAVAILABLE"
    with Session(engine) as db:
        core=db.get(CommitmentRecord,(TENANT,"com-001"))
        assert (core.agreement_state,core.fulfilment_state,core.commitment_version)==("OFFERED","NOT_STARTED",handoff.commitment_version)
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord)) == 0
    duplicate=client.post("/v1/confirmations/process-inbound",headers=processor_headers,json={"inbound_message_id":message_id})
    assert duplicate.status_code==409 and duplicate.json()["code"]=="CONFIRMATION_CONSUMED"


@pytest.mark.parametrize("fault", ["unknown_sender", "wrong_recipient", "invalid_token", "wrong_proposal",
    "stale_version", "expired", "revoked", "unverified", "provenance", "cross_tenant", "unauthorized_processor"])
def test_trusted_reply_negatives_do_not_persist_acceptance(runtime, fault):
    client, engine, handoff, received, headers, processor_headers, _ = runtime
    send_approved(runtime)
    receipt=received[0]
    original=receipt.challenge.body.split("\n\n")[-1]
    target, secret, _=parse_customer_reply(original)
    value=original
    if fault=="invalid_token": value=value.replace(secret,"x"*43)
    if fault=="wrong_proposal": value=value.replace("ACCEPT "+handoff.proposal_id,"ACCEPT wrong_proposal")
    if fault=="stale_version": value=value.replace(" v1 terms:"," v2 terms:")
    sender="+60198765432" if fault=="wrong_recipient" else "unverified_sender" if fault=="unknown_sender" else "+60123456789"
    message=persist_p1_reply(engine,receipt,sender=sender,text=value)
    if fault=="unverified":
        from app.context.association_schemas import IdentityLinkStatus
        repository=PostgresMessageRepository(engine)
        association=repository.get_association(TENANT,message)
        association=association.model_copy(update={"status":IdentityLinkStatus.UNVERIFIED,"verified_customer":None})
        repository.save_association(association)
    if fault=="provenance":
        from app.context.postgres_repository import InboundMessage
        with Session(engine) as db:
            db.get(InboundMessage,message).content_sha256="a"*64
            db.commit()
    if fault in {"expired","revoked"}:
        with Session(engine) as db:
            row=db.get(ConfirmationSessionRecord,(TENANT,target))
            if fault=="expired": row.expires_at=row.created_at+timedelta(microseconds=1)
            else: row.revoked_at=datetime.now(timezone.utc)
            db.commit()
    request_headers=dict(processor_headers)
    if fault=="cross_tenant": request_headers["X-Tenant-ID"]="synthetic_tenant_b"
    if fault=="unauthorized_processor": request_headers={"X-Tenant-ID":TENANT,"X-Actor-ID":"service_core"}
    response=client.post("/v1/confirmations/process-inbound",headers=request_headers,json={"inbound_message_id":message})
    assert response.status_code in {403,404,409,422}, response.text
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord))==0
        assert db.get(ConfirmationSessionRecord,(TENANT,target)).consumed_at is None
        core=db.get(CommitmentRecord,(TENANT,"com-001"))
        assert core.agreement_state=="OFFERED" and core.fulfilment_state=="NOT_STARTED"


@pytest.mark.parametrize("fault", ["missing_approval","revoked_approval","expired_approval","terms_mismatch","opt_out","expired_consent","unauthorized_send"])
def test_current_authority_changes_prevent_additional_send(runtime, fault):
    client, engine, handoff, received, headers, _, _=runtime
    request,draft,sent=send_approved(runtime)
    with Session(engine) as db:
        approval=db.get(ManagerApprovalRecord,(TENANT,handoff.approval_id))
        if fault=="missing_approval": db.delete(approval)
        if fault=="revoked_approval": approval.decision="REVOKED"
        if fault=="expired_approval": approval.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        if fault=="terms_mismatch": approval.approved_terms={**approval.approved_terms,"quantity":"9999"}
        pref=db.get(RecipientPreferenceRecord,(TENANT,"cust_bk","MOCK_WHATSAPP","TRANSACTIONAL_REVISED_TERMS"))
        if fault=="opt_out": pref.consent_status,pref.revoked_at="OPTED_OUT",datetime.now(timezone.utc)
        if fault=="expired_consent": pref.consent_expires_at=pref.consent_recorded_at+timedelta(microseconds=1)
        db.commit()
    request_headers=dict(headers)
    if fault=="unauthorized_send": request_headers.pop("X-Isolated-E2E-Key")
    result=client.post(f'/v1/communications/{request["communication_id"]}/drafts/{draft["draft_id"]}/send',
        headers=request_headers,json={"request_key":"another_send_key","expected_content_hash":draft["content_hash"]})
    assert result.status_code in {403,409},result.text
    assert len(received)==1


def test_worker_restarts_and_terminal_response_prevents_future_reminders(runtime):
    client,engine,_,received,headers,processor_headers,keys=runtime
    send_approved(runtime)
    target=received[0].challenge.confirmation_id
    task=schedule(client,headers,target)
    due=datetime.fromisoformat(task["next_due_at"].replace("Z","+00:00"))
    factory=sessionmaker(engine)
    first=run_isolated_reminder_tick(factory,PROCESSOR,keys["worker"],SyntheticCustomerDirectory(),now=due)
    assert first[0].reminders_sent==1 and len(received)==2
    assert received[1].challenge.confirmation_id==target
    assert run_isolated_reminder_tick(factory,PROCESSOR,keys["worker"],SyntheticCustomerDirectory(),now=due)==[]
    message=persist_p1_reply(engine,received[1])
    checked(client.post("/v1/confirmations/process-inbound",headers=processor_headers,json={"inbound_message_id":message}))
    assert run_isolated_reminder_tick(factory,PROCESSOR,keys["worker"],SyntheticCustomerDirectory(),now=due+timedelta(minutes=2))==[]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ReminderAttemptRecord))==1
        assert db.get(FollowUpTaskRecord,(TENANT,task["task_id"])).status=="CANCELLED"


def test_actual_dispatcher_consumer_failure_keeps_core_and_evidence(runtime):
    client,engine,_,received,headers,processor_headers,_=runtime
    send_approved(runtime)
    message=persist_p1_reply(engine,received[0])
    checked(client.post("/v1/confirmations/process-inbound",headers=processor_headers,json={"inbound_message_id":message}))
    dispatcher=OutboxDispatcher()
    dispatcher.register_subscriber("confirmation.accepted","p5.confirmation.required",build_core_confirmation_consumer(None))
    with Session(engine) as db:
        dispatcher.process_outbox_batch(db,batch_size=100)
    with Session(engine) as db:
        row=db.scalar(select(OutboxEventRecord).where(OutboxEventRecord.event_type=="confirmation.accepted"))
        assert row.status=="FAILED" and row.attempts==1
        assert db.get(CommitmentRecord,(TENANT,"com-001")).agreement_state=="OFFERED"
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord))==1


def test_ambiguous_verified_reply_never_accepts_and_remains_followup_eligible(runtime):
    client,engine,_,received,headers,processor_headers,_=runtime
    send_approved(runtime)
    target,secret,_=parse_customer_reply(received[0].challenge.body.split("\n\n")[-1])
    task=schedule(client,headers,target)
    message=persist_p1_reply(engine,received[0],text=f"CONFIRM {target} {secret}\nOK")
    result=checked(client.post("/v1/confirmations/process-inbound",headers=processor_headers,json={"inbound_message_id":message}))
    assert result["intent"]=="UNKNOWN"
    with Session(engine) as db:
        assert db.get(FollowUpTaskRecord,(TENANT,task["task_id"])).status=="WAITING"
        assert db.get(CommitmentRecord,(TENANT,"com-001")).agreement_state=="OFFERED"


def test_challenge_outbound_audit_transaction_rolls_back_before_any_delivery(runtime,monkeypatch):
    from app.communication.challenge_delivery import BoundChallengeDelivery
    from app.communication.models import OutboundMessageRecord
    from sqlalchemy.exc import OperationalError
    original=BoundChallengeDelivery.prepare
    def failure(self,*args,**kwargs):
        original(self,*args,**kwargs)
        raise OperationalError("isolated test failure",{},RuntimeError("rollback check"))
    monkeypatch.setattr(BoundChallengeDelivery,"prepare",failure)
    _,_,response=send_approved(runtime,expected_http=503)
    assert response.json()["code"]=="SEND_STORAGE_UNAVAILABLE"
    _,engine,_,received,_,_,_=runtime
    assert received==[]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(OutboundMessageRecord))==0
        assert db.scalar(select(func.count()).select_from(ConfirmationSessionRecord))==0
        assert db.scalar(select(func.count()).select_from(OutboxEventRecord).where(
            OutboxEventRecord.event_type=="confirmation.created"))==0


def test_secure_provider_timeout_does_not_redeliver_or_accept(runtime):
    from app.communication.router import get_outbound_provider
    from app.communication.providers import LocalMockProvider
    client,engine,_,received,headers,_,_=runtime
    app.dependency_overrides[get_outbound_provider]=lambda: LocalMockProvider("DELIVERY_UNKNOWN",receipt_sink=received.append)
    _,_,sent=send_approved(runtime,expected_status="DELIVERY_UNKNOWN")
    assert sent["status"]=="DELIVERY_UNKNOWN" and not received
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ConfirmationSessionRecord))==1
        assert db.scalar(select(func.count()).select_from(ConfirmationDecisionRecord))==0
        assert db.get(CommitmentRecord,(TENANT,"com-001")).agreement_state=="OFFERED"


@pytest.mark.parametrize("intent",["REJECT","COUNTEROFFER"])
def test_actual_p1_rejection_and_counteroffer_preserve_original_terms(runtime,intent):
    client,engine,handoff,received,headers,processor_headers,_=runtime
    send_approved(runtime)
    target,secret,_=parse_customer_reply(received[0].challenge.body.split("\n\n")[-1])
    suffix=' changes:{"quantity":"80"}' if intent=="COUNTEROFFER" else ''
    message=persist_p1_reply(engine,received[0],text=f"CONFIRM {target} {secret}\n{intent} {handoff.proposal_id} v{handoff.proposal_version}{suffix}")
    result=checked(client.post("/v1/confirmations/process-inbound",headers=processor_headers,json={"inbound_message_id":message}))
    assert result["intent"]==intent
    with Session(engine) as db:
        event=db.scalar(select(OutboxEventRecord).where(OutboxEventRecord.event_type==(
            "confirmation.rejected" if intent=="REJECT" else "confirmation.counteroffer_received")))
        if intent=="COUNTEROFFER": assert event.payload["proposed_changes"]=={"quantity":"80"}
        assert db.get(CommitmentRecord,(TENANT,"com-001")).agreement_state=="OFFERED"


def test_bare_app_or_production_mode_cannot_enable_isolated_authorities(runtime,monkeypatch):
    client,_,_,_,headers,_,_=runtime
    with TestClient(app) as bare:
        denied=bare.get("/v1/communications",headers=headers)
        assert denied.status_code==503 and denied.json()["code"]=="PRIVATE_INBOUND_GATEWAY_REQUIRED"
    monkeypatch.setenv("APP_ENV","production")
    denied=client.get("/v1/communications",headers=headers)
    assert denied.status_code==503 and denied.json()["code"]=="TRUSTED_ISOLATED_RUNTIME_UNAVAILABLE"


def test_private_p1_gateway_restricts_processor_to_server_tenant_scope(runtime):
    client,_,_,_,_,processor_headers,_=runtime
    wrong={**processor_headers,"X-Tenant-ID":"synthetic_tenant_b"}
    assert client.get("/v1/messages",headers=wrong).status_code==403
    missing={k:v for k,v in processor_headers.items() if k!="X-Tenant-ID"}
    assert client.get("/v1/messages",headers=missing).status_code==403


@pytest.mark.parametrize("plan_version,binding", [
    (2, {}),
    (2, {"proposal_id": "missing_version"}),
    (2, {"proposal_version": 2}),
    (2, {"proposal_id": "wrong_proposal", "proposal_version": 1}),
    (2, {"proposal_id": "__actual__", "proposal_version": 2}),
    (2, {"proposal_id": "__actual__", "proposal_version": True}),
    (1, {"proposal_id": "__actual__"}),
    (1, {"proposal_version": 1}),
    (1, {"proposal_id": "wrong_proposal", "proposal_version": 1}),
])
def test_persisted_plan_identity_fails_closed_without_rebinding_history(runtime, plan_version, binding):
    # Deliberately corrupted persisted plan inputs, not invented approval proof
    # or a fake positive V2 handoff. Shared P3/P5 producers remain untouched.
    from app.communication.trusted_runtime import PersistedCommunicationAuthority
    from app.communication.service import CommunicationRequestService
    from app.communication.schemas import CreateCommunicationRequest
    from app.recovery.durable_plans import RecoveryPlanRecord
    _, engine, handoff, _, _, _, _ = runtime
    with Session(engine) as db:
        basis = CommunicationRequestService(db).read_current_basis(MANAGER,
            CreateCommunicationRequest(source_event_id=handoff.source_event_id), datetime.now(timezone.utc))
        plan = db.get(RecoveryPlanRecord, (TENANT, handoff.plan_id, handoff.plan_version))
        original = dict(plan.payload)
        values = {column.key: getattr(plan, column.key) for column in RecoveryPlanRecord.__table__.columns}
        bad = {key: (handoff.proposal_id if value == "__actual__" else value) for key, value in binding.items()}
        payload = {key: value for key, value in original.items() if key not in {"proposal_id", "proposal_version"}}
        payload.update(bad)
        if plan_version > 1:
            values.update(plan_version=plan_version, payload=payload)
            db.add(RecoveryPlanRecord(**values))
        else:
            plan.payload = payload
        db.flush()
        reference = basis.reference.model_copy(update={"plan_version": plan_version})
        with pytest.raises(DomainError) as error:
            PersistedCommunicationAuthority(None, None)._approval(db, MANAGER, reference, basis.terms)
        assert error.value.code == "PROPOSAL_PLAN_IDENTITY_CONFLICT"
        assert error.value.status_code == 409
        # This guard never rewrites source, approval, or prior customer evidence.
        source = db.get(OutboxEventRecord, handoff.source_event_id)
        assert source.payload["proposal_id"] == handoff.proposal_id
        assert source.payload["proposal_version"] == handoff.proposal_version
        db.rollback()
