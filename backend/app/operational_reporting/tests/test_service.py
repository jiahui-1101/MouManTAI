"""Synthetic contract tests. These do not assert a live status or P4 adapter."""

from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.models import CommitmentRecord
from app.operational_reporting.models import (
    EventKind,
    EvidenceTier,
    Milestone,
    SendHistory,
    Template,
)
from app.operational_reporting.planning import Eligibility
from app.operational_reporting.service import (
    ApprovedTemplate,
    CommitmentIdentity,
    CoreCommitmentLookup,
    HistoryResult,
    OperationalReadService,
    PurposePolicy,
    ReadCode,
    ReportPage,
    VerifiedCaller,
    read_daily,
)
from app.operational_reporting.tests.test_d1 import NOW, event, facts, recipient, status

CONTEXT = RequestContext("t", "actor", "CUSTOMER", "correlation")


class Resolver:
    def __init__(self, caller=None):
        self.caller = caller or VerifiedCaller("t", "actor", "customer")

    def verify(self, context):
        return self.caller


class Commitments:
    def __init__(self, identity=None):
        self.identity = identity or CommitmentIdentity("t", "c", "o", "customer", 1, NOW)
        self.calls = 0

    def find(self, caller, commitment_id):
        self.calls += 1
        if (
            caller.tenant_id != self.identity.tenant_id
            or caller.customer_id != self.identity.customer_id
            or commitment_id != self.identity.commitment_id
        ):
            return None
        return self.identity


class Orders:
    def __init__(self, order=None, projected=None):
        self.order = order or facts()
        self.projected = projected or status(self.order)
        self.calls = 0

    def read(self, identity):
        self.calls += 1
        return self.order, self.projected


class P4:
    def __init__(
        self,
        purpose="MILESTONE",
        complete=True,
        approved=True,
        unknown=frozenset(),
        recipient_policy=None,
        history_complete=True,
    ):
        self.purpose = purpose
        self.complete = complete
        self.approved = approved
        self.unknown = unknown
        self.recipient_policy = recipient_policy or recipient()
        self.history_complete = history_complete
        self.calls = []

    def policy(self, identity, purpose):
        self.calls.append("policy")
        return PurposePolicy(self.purpose, self.recipient_policy, self.complete)

    def template(self, milestone):
        self.calls.append("template")
        return ApprovedTemplate(Template("accepted", "v1", milestone), self.approved)

    def history(self, identity, purpose):
        self.calls.append("history")
        return HistoryResult(SendHistory(self.history_complete, frozenset()), self.unknown)


def service(resolver=None, commitments=None, orders=None, p4=None):
    return OperationalReadService(
        resolver or Resolver(), commitments or Commitments(), orders or Orders(), p4
    )


def test_missing_resolver_denies_without_lookup():
    lookup = Commitments()
    result = OperationalReadService(None, lookup, Orders()).read_order(CONTEXT, "c", as_of=NOW)
    assert result.code == ReadCode.AUTHORIZATION_DENIED
    assert lookup.calls == 0


def test_core_lookup_uses_tenant_and_customer_scope_without_mutation():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    CommitmentRecord.__table__.create(engine)
    with Session(engine) as db:
        for tenant, customer in (("t", "customer"), ("other", "customer")):
            db.add(
                CommitmentRecord(
                    tenant_id=tenant,
                    commitment_id="c",
                    order_id="o",
                    customer_id=customer,
                    terms={},
                    agreement_state="CONFIRMED",
                    feasibility_state="UNKNOWN",
                    risk_state="UNKNOWN",
                    recovery_state="NONE",
                    fulfilment_state="NOT_STARTED",
                    commitment_version=1,
                    evidence_refs=[],
                    updated_at=NOW,
                )
            )
        db.commit()
        lookup = CoreCommitmentLookup(db)
        assert lookup.find(VerifiedCaller("t", "actor", "customer"), "c").tenant_id == "t"
        assert lookup.find(VerifiedCaller("t", "actor", "other"), "c") is None
        assert lookup.find(VerifiedCaller("t", "actor", "customer"), "absent") is None
        assert not db.dirty and not db.new and not db.deleted
        db.add(
            CommitmentRecord(
                tenant_id="t",
                commitment_id="pending",
                order_id="uncommitted",
                customer_id="customer",
                terms={},
                agreement_state="REQUESTED",
                feasibility_state="UNKNOWN",
                risk_state="UNKNOWN",
                recovery_state="NONE",
                fulfilment_state="NOT_STARTED",
                commitment_version=1,
                evidence_refs=[],
                updated_at=NOW,
            )
        )
        assert lookup.find(VerifiedCaller("t", "actor", "customer"), "pending") is None
        assert len(db.new) == 1
        db.rollback()
    engine.dispose()


def test_wrong_tenant_actor_or_customer_is_not_disclosed():
    for caller, expected in (
        (VerifiedCaller("other", "actor", "customer"), ReadCode.AUTHORIZATION_DENIED),
        (VerifiedCaller("t", "other", "customer"), ReadCode.AUTHORIZATION_DENIED),
        (VerifiedCaller("t", "actor", "other"), ReadCode.NOT_FOUND),
    ):
        source = Orders()
        result = service(resolver=Resolver(caller), orders=source).read_order(
            CONTEXT, "c", as_of=NOW
        )
        assert result.code == expected and result.facts is None and source.calls == 0


def test_missing_status_owner_and_bad_commitment_are_fail_closed():
    assert (
        OperationalReadService(Resolver(), Commitments()).read_order(CONTEXT, "c", as_of=NOW).code
        == ReadCode.SOURCE_UNAVAILABLE
    )
    assert service().read_order(CONTEXT, "other", as_of=NOW).code == ReadCode.NOT_FOUND


def test_status_vector_identity_version_freshness_and_evidence():
    base = facts()
    variants = (
        (replace(base, tenant_id="other"), status(base), ReadCode.SOURCE_STALE),
        (replace(base, order_id="other"), status(base), ReadCode.SOURCE_STALE),
        (replace(base, customer_id="other"), status(base), ReadCode.SOURCE_STALE),
        (replace(base, aggregate_version=2), status(base), ReadCode.SOURCE_STALE),
        (
            base,
            replace(status(base), snapshot_at=NOW - timedelta(seconds=1)),
            ReadCode.SOURCE_STALE,
        ),
        (replace(base, events=()), status(base), ReadCode.EVIDENCE_MISSING),
        (base, replace(status(base), milestone=Milestone.NOT_AVAILABLE), ReadCode.STATUS_UNKNOWN),
    )
    for order, projected, expected in variants:
        result = service(orders=Orders(order, projected)).read_order(CONTEXT, "c", as_of=NOW)
        assert result.code == expected
    assert service().read_order(CONTEXT, "c", as_of=NOW).code == ReadCode.VERIFIED_STATUS_AVAILABLE
    assert (
        service().read_order(CONTEXT, "c", as_of=NOW + timedelta(hours=2)).code
        == ReadCode.SOURCE_STALE
    )


def test_concurrent_core_version_change_is_detected():
    class Changing(Commitments):
        def find(self, caller, commitment_id):
            result = super().find(caller, commitment_id)
            return replace(result, version=2) if self.calls == 2 else result

    assert (
        service(commitments=Changing()).read_order(CONTEXT, "c", as_of=NOW).code
        == ReadCode.SOURCE_STALE
    )


def test_milestone_requires_exact_purpose_approved_template_and_history():
    assert service(p4=None).plan(CONTEXT, "c", "e1", as_of=NOW).reason == "P4_UNAVAILABLE"
    assert (
        service(p4=P4(purpose="TRANSACTIONAL_REVISED_TERMS"))
        .plan(CONTEXT, "c", "e1", as_of=NOW)
        .reason
        == "PURPOSE_POLICY_UNAVAILABLE"
    )
    assert (
        service(p4=P4(complete=False)).plan(CONTEXT, "c", "e1", as_of=NOW).result
        == Eligibility.UNKNOWN
    )
    assert (
        service(p4=P4(history_complete=False)).plan(CONTEXT, "c", "e1", as_of=NOW).reason
        == "SEND_HISTORY_UNKNOWN"
    )
    assert (
        service(p4=P4(recipient_policy=recipient(consent=False)))
        .plan(CONTEXT, "c", "e1", as_of=NOW)
        .result
        == Eligibility.BLOCKED
    )
    assert (
        service(p4=P4(approved=False)).plan(CONTEXT, "c", "e1", as_of=NOW).reason
        == "APPROVED_TEMPLATE_UNAVAILABLE"
    )
    assert service(p4=P4()).plan(CONTEXT, "c", "absent", as_of=NOW).reason == "EVENT_SOURCE_MISSING"
    result = service(p4=P4()).plan(CONTEXT, "c", "e1", as_of=NOW)
    assert result.result == Eligibility.ELIGIBLE and result.dedup_key
    blocked = service(p4=P4(unknown=frozenset({result.dedup_key}))).plan(
        CONTEXT, "c", "e1", as_of=NOW
    )
    assert blocked.result == Eligibility.UNKNOWN and blocked.reason == "PROVIDER_OUTCOME_UNKNOWN"


def test_demo_evidence_and_feedback_wrong_purpose_never_invite():
    order = facts()
    demo = replace(
        order,
        evidence=tuple(
            replace(item, tier=EvidenceTier.DEMO_ONLY)
            if item.ref in {"accept", "reserve"}
            else item
            for item in order.evidence
        ),
    )
    assert (
        service(orders=Orders(demo, status(demo, tier=EvidenceTier.DEMO_ONLY)))
        .read_order(CONTEXT, "c", as_of=NOW)
        .code
        == ReadCode.STATUS_UNKNOWN
    )
    assert (
        service(orders=Orders(demo, status(demo, tier=EvidenceTier.DEMO_ONLY)), p4=P4())
        .plan(CONTEXT, "c", "e1", as_of=NOW)
        .result
        != Eligibility.ELIGIBLE
    )
    assert (
        service(p4=P4(purpose="MILESTONE"))
        .plan(CONTEXT, "c", "e1", as_of=NOW, feedback=True)
        .reason
        == "PURPOSE_POLICY_UNAVAILABLE"
    )


def test_feedback_composition_needs_verified_fulfilment_and_exact_purpose():
    order = facts(
        events=(event(), event(EventKind.FULFILLED, 2, refs=("done",))),
        fulfilment="FULFILLED",
    )
    identity = CommitmentIdentity("t", "c", "o", "customer", 2, NOW)
    result = service(
        commitments=Commitments(identity),
        orders=Orders(order, status(order, Milestone.COMPLETED)),
        p4=P4(purpose="FEEDBACK"),
    ).plan(CONTEXT, "c", "", as_of=NOW, feedback=True)
    assert result.result == Eligibility.ELIGIBLE and result.dedup_key
    duplicate = service(
        commitments=Commitments(identity),
        orders=Orders(order, status(order, Milestone.COMPLETED)),
        p4=P4(purpose="FEEDBACK", unknown=frozenset({result.dedup_key})),
    ).plan(CONTEXT, "c", "", as_of=NOW, feedback=True)
    assert duplicate.result == Eligibility.UNKNOWN


class Pages:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def page(self, tenant_id, start, end, cursor):
        self.calls.append((tenant_id, start, end, cursor))
        return next(self.pages)


def test_daily_requires_verified_staff_and_marks_missing_source_partial():
    assert read_daily(CONTEXT, None, None, date(2026, 10, 23), "UTC", as_of=NOW) is None
    staff = Resolver(VerifiedCaller("t", "actor", None, True))
    report = read_daily(CONTEXT, staff, None, date(2026, 10, 23), "UTC", as_of=NOW)
    assert not report.source_complete and "ORDER_SOURCE_UNAVAILABLE" in report.limitations
    assert report.accepted_orders == report.due_orders == 0


def test_daily_pages_are_tenant_day_bounded_and_complete_only_at_end():
    staff = Resolver(VerifiedCaller("t", "actor", None, True))
    source = Pages(
        (
            ReportPage((), "page-2", NOW, True),
            ReportPage((), None, NOW, True),
        )
    )
    report = read_daily(CONTEXT, staff, source, date(2026, 10, 23), "UTC", as_of=NOW)
    assert report.source_complete and len(source.calls) == 2
    assert source.calls[0][0] == "t" and source.calls[1][3] == "page-2"
    assert not read_daily(
        CONTEXT,
        staff,
        Pages((ReportPage((), "again", NOW, True), ReportPage((), "again", NOW, True))),
        date(2026, 10, 23),
        "UTC",
        as_of=NOW,
    ).source_complete
    assert not read_daily(
        CONTEXT,
        staff,
        Pages(
            (
                ReportPage((), "page-2", NOW, True),
                ReportPage((), None, NOW - timedelta(seconds=1), True),
            )
        ),
        date(2026, 10, 23),
        "UTC",
        as_of=NOW,
    ).source_complete
