"""Cross-module contract checks for the non-production B/D/F/G/H candidate."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec

from app.core.dependencies import RequestContext
from app.decision_memory.models import CurrentSituation, Domain
from app.decision_memory.service import DecisionMemoryService
from app.feasibility.portfolio_readiness import inspect_portfolio_inputs
from app.feasibility.production_fixtures import build_production_example
from app.feasibility.readiness import assess_operational_readiness
from app.forecasting.models import SourceUnavailable
from app.forecasting.service import ForecastService
from app.integrations.business_ports import (
    ReservationCommand,
    ReservationReceipt,
    require_receipt_binding,
)
from app.operational_reporting.service import (
    CommitmentIdentity,
    OperationalReadService,
    ReadCode,
    VerifiedCaller,
)
from app.optimization.models import CandidateBinding
from app.optimization.service import compare
from app.optimization.tests.test_optimization import (
    FixtureProvider,
    FixtureVerifier,
)
from app.optimization.tests.test_optimization import (
    fixture as optimization_fixture,
)
from app.orders.terms import OrderTerms


def _canonical_terms(*, tenant_id: str, order_request_id: str, quantity: Decimal) -> OrderTerms:
    window_start = datetime(2026, 10, 25, 10, tzinfo=UTC)
    return OrderTerms.model_validate(
        {
            "tenant_id": tenant_id,
            "order_request_id": order_request_id,
            "customer_id": "fixture-customer",
            "terms_revision": 2,
            "items": [
                {
                    "sku": "box",
                    "variant": None,
                    "quantity": format(quantity, "f"),
                    "unit": "each",
                    "unit_price": "1",
                }
            ],
            "fulfilment_method": "DELIVERY",
            "location_ref": "fixture-address-v1",
            "window_start": window_start.isoformat(),
            "window_end": (window_start + timedelta(hours=1)).isoformat(),
            "business_timezone": "Asia/Singapore",
            "currency": "MYR",
            "fees": "0",
            "tax": "0",
            "discount": "0",
            "total": format(quantity, "f"),
            "price_source": {
                "source_type": "APPROVED_CATALOG",
                "source_id": "fixture-price",
                "source_version": "1",
                "policy_ref": "fixture-pricing-policy",
                "disclosed_at": "2026-10-24T00:00:00Z",
                "evidence_refs": ["fixture-price-evidence"],
            },
            "binding_policy_ref": "fixture-binding-policy",
            "source_message_ids": ["fixture-message"],
            "evidence_refs": ["fixture-order-evidence"],
        }
    )


def test_foundation_command_receipt_and_h_candidate_bind_the_same_terms():
    request, spec = optimization_fixture()
    candidate = request.candidates[0]
    terms = _canonical_terms(
        tenant_id=request.tenant_id,
        order_request_id=candidate.order_request_id,
        quantity=candidate.lines[0].quantity,
    )
    command = ReservationCommand(
        tenant_id=candidate.tenant_id,
        order_request_id=candidate.order_request_id,
        request_version=candidate.request_version,
        terms=terms,
        snapshot_id=request.snapshot_id,
        snapshot_version=request.snapshot_version,
        assessment_id=request.assessment_watermark,
        idempotency_key="fixture-reservation-idempotency",
    )
    assert command.request_version != command.terms.terms_revision

    updated_candidate = candidate.model_copy(
        update={
            "terms_revision": terms.terms_revision,
            "terms_hash": terms.terms_hash,
            "financial": candidate.financial.model_copy(update={"terms_hash": terms.terms_hash}),
        }
    )
    candidates = (updated_candidate, *request.candidates[1:])
    request = request.model_copy(update={"candidates": candidates})
    spec = spec.model_copy(
        update={
            "candidate_bindings": tuple(
                CandidateBinding(
                    order_request_id=item.order_request_id,
                    request_version=item.request_version,
                    terms_revision=item.terms_revision,
                    terms_hash=item.terms_hash,
                    source_identity=item.source_identity,
                    evidence_refs=item.evidence_refs,
                )
                for item in candidates
            )
        }
    )

    receipt = ReservationReceipt(
        tenant_id=command.tenant_id,
        order_request_id=command.order_request_id,
        operation_id="fixture-operation",
        idempotency_key=command.idempotency_key,
        request_version=command.request_version,
        terms_hash=command.terms.terms_hash,
        terms_revision=command.terms.terms_revision,
        snapshot_id=command.snapshot_id,
        snapshot_version=command.snapshot_version,
        assessment_id=command.assessment_id,
        status="PENDING",
        mode="SYNTHETIC",
        checked_at=request.evaluated_at,
        evidence_refs=("fixture-receipt",),
    )
    require_receipt_binding(receipt, expected=command, operation_id="fixture-operation")
    assert receipt.reservation_confirmed is False


def test_h_candidate_runs_synthetic_cpsat_fixture():
    request, spec = optimization_fixture()
    result = compare(
        request,
        provider=FixtureProvider(spec),
        verifier=FixtureVerifier(spec),
    )
    if find_spec("ortools") is None:
        assert result.scenarios == ()
        assert "SOLVER_STATUS_UNKNOWN" in result.limitation_codes
        assert result.recommendation_only is True
        return

    assert result.scenarios
    assert all(scenario.validation_status == "FIXTURE_VALIDATED" for scenario in result.scenarios)
    assert all(scenario.integration_mode == "SYNTHETIC" for scenario in result.scenarios)


def test_b_d_f_g_h_stay_fail_closed_without_live_owner_adapters():
    snapshot, commitment = build_production_example()
    b = assess_operational_readiness(
        tenant_id=commitment.tenant_id,
        commitment=commitment,
        snapshot=None,
        checked_at=snapshot.as_of,
    )
    assert b.status == "UNKNOWN"
    assert b.reservation_authorized is False

    class Resolver:
        def verify(self, context):
            return VerifiedCaller(context.tenant_id, context.actor_id, "fixture-customer")

    class Commitments:
        def find(self, caller, commitment_id):
            if not commitment_id:
                return None
            return CommitmentIdentity(
                caller.tenant_id,
                commitment_id,
                "fixture-order",
                caller.customer_id,
                1,
                datetime(2026, 10, 24, tzinfo=UTC),
            )

    now = datetime(2026, 10, 24, tzinfo=UTC)
    context = RequestContext("fixture-tenant", "fixture-actor", "CUSTOMER", "fixture-correlation")
    d = OperationalReadService(Resolver(), Commitments(), orders=None).read_order(
        context, "fixture-commitment", as_of=now
    )
    assert d.code is ReadCode.SOURCE_UNAVAILABLE

    f = ForecastService().baseline(
        "fixture-tenant", "fixture-sku", "each", date(2026, 10, 24), 1, now
    )
    assert isinstance(f, SourceUnavailable)

    g = DecisionMemoryService().retrieve_similar_cases(
        CurrentSituation(
            tenant_id="fixture-tenant",
            domain=Domain.RECOVERY,
            situation_version=1,
            business_context_ref="fixture-context",
            context_schema="recovery-v1",
            context=(),
            hard_constraints=(),
            evidence_refs=("synthetic-fixture",),
            as_of=now,
        ),
        live=True,
    )
    assert g.status == "SOURCE_UNAVAILABLE"

    h_request, h_spec = optimization_fixture()
    h_request = h_request.model_copy(update={"integration_mode": "LIVE"})
    h = compare(
        h_request,
        provider=FixtureProvider(h_spec),
        verifier=FixtureVerifier(h_spec),
    )
    assert h.scenarios == ()
    assert h.limitation_codes == ("P2_CONSTRAINT_SPEC_UNAVAILABLE",)


def test_b_does_not_promote_pending_requests_to_confirmed_baseline():
    snapshot, commitment = build_production_example()
    result = inspect_portfolio_inputs(
        tenant_id=commitment.tenant_id,
        snapshot=snapshot,
        checked_at=snapshot.as_of,
        pending_order_request_ids=("fixture-pending-request",),
    )
    assert result.status == "PENDING_TARGET_UNSUPPORTED"
    assert result.allocation_authorized is False
    assert result.profit_strategy_available is False
    assert result.expiry_strategy_available is False
