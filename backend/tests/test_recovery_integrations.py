from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import Commitment
from app.recovery.feasibility import SyntheticP2Evaluator
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.integrations import (
    IntegrationSource,
    P2FeasibilityEvaluatorAdapter,
    P5CommitmentReader,
    UnavailableOperationalSnapshotProvider,
    UnavailableRecoveryEventPublisher,
    UnverifiedP5ContextAdapter,
    VersionedSnapshot,
    require_verified_actor,
    validate_proposal_binding,
    validate_snapshot_binding,
)
from app.recovery.models import OperationalSnapshotReference, RecoveryStrategy, ValidationSource


def _commitment() -> Commitment:
    return load_demo_recovery_inputs().commitment


def _snapshot(commitment: Commitment, *, source=IntegrationSource.SYNTHETIC_TEST_DOUBLE, version=7):
    inner = SimpleNamespace(snapshot_id="snap-1", snapshot_version=version, tenant_id=commitment.tenant_id)
    payload = SimpleNamespace(operational=inner)
    return VersionedSnapshot(payload, commitment.tenant_id, commitment.commitment_id,
                             commitment.commitment_version, "snap-1", version,
                             datetime.now(UTC), source)


def test_p2_adapter_invokes_only_the_p2_evaluate_contract():
    commitment = _commitment()
    snapshot = _snapshot(commitment)
    proposal = SimpleNamespace(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                               expected_commitment_version=commitment.commitment_version,
                               expected_snapshot_version=7)

    result = SimpleNamespace(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                             commitment_version=commitment.commitment_version, snapshot_id="snap-1",
                             snapshot_version=7)
    calls = []

    def evaluate(*args):
        calls.append(args)
        return result

    returned = P2FeasibilityEvaluatorAdapter(evaluate, allow_test_double=True).evaluate(
        snapshot, proposal, commitment
    )
    assert returned is result
    assert calls == [(snapshot.snapshot, proposal, commitment)]


def test_p2_result_version_mismatch_is_rejected():
    commitment = _commitment()
    snapshot = _snapshot(commitment)
    bad_result = SimpleNamespace(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                                 commitment_version=commitment.commitment_version - 1, snapshot_id="snap-1",
                                 snapshot_version=7)
    with pytest.raises(DomainError, match="result identity or versions"):
        P2FeasibilityEvaluatorAdapter(lambda *args: bad_result, allow_test_double=True).evaluate(
            snapshot, None, commitment
        )


@pytest.mark.parametrize("source", [IntegrationSource.SYNTHETIC_TEST_DOUBLE])
def test_test_double_snapshot_requires_explicit_isolated_opt_in(source):
    commitment = _commitment()
    with pytest.raises(DomainError, match="explicitly isolated tests"):
        P2FeasibilityEvaluatorAdapter(SimpleNamespace(evaluate=lambda *args: None)).evaluate(
            _snapshot(commitment, source=source), None, commitment)


def test_authoritative_p2_evaluation_requires_matching_current_snapshot_token():
    commitment = _commitment()
    snapshot = _snapshot(commitment, source=IntegrationSource.AUTHORITATIVE)
    snapshot.snapshot.current_snapshot_version = None
    with pytest.raises(DomainError, match="current snapshot version token"):
        P2FeasibilityEvaluatorAdapter(lambda *args: None).evaluate(snapshot, None, commitment)

    snapshot.snapshot.current_snapshot_version = snapshot.snapshot_version + 1
    with pytest.raises(DomainError, match="does not match"):
        P2FeasibilityEvaluatorAdapter(lambda *args: None).evaluate(snapshot, None, commitment)


def test_synthetic_evaluator_result_retains_test_double_provenance():
    commitment = _commitment()
    snapshot = OperationalSnapshotReference(
        snapshot_id="synthetic-snapshot", snapshot_version=1,
        captured_at=datetime.now(UTC), source="fixture",
    )
    result = SyntheticP2Evaluator().evaluate(
        snapshot, {"strategy": RecoveryStrategy.ALTERNATIVE_SUPPLY.value}, commitment
    )
    assert result.validation_source == ValidationSource.TEST_DOUBLE_VALIDATED


def test_snapshot_version_and_tenant_binding_are_enforced():
    commitment = _commitment()
    stale = _snapshot(commitment, version=7)
    stale.snapshot.operational.snapshot_version = 8
    with pytest.raises(DomainError, match="envelope"):
        validate_snapshot_binding(stale, commitment)

    other_tenant = _snapshot(commitment)
    object.__setattr__(other_tenant, "tenant_id", "other-tenant")
    with pytest.raises(DomainError, match="tenant"):
        validate_snapshot_binding(other_tenant, commitment)


def test_proposal_expected_versions_must_match_snapshot_and_commitment():
    commitment = _commitment()
    snapshot = _snapshot(commitment)
    proposal = SimpleNamespace(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                               expected_commitment_version=commitment.commitment_version - 1,
                               expected_snapshot_version=7)
    with pytest.raises(DomainError, match="versions"):
        validate_proposal_binding(proposal, snapshot, commitment)


def test_p5_commitment_reader_uses_tenant_context_and_checks_expected_version():
    commitment = _commitment()
    context = RequestContext(commitment.tenant_id, "user_manager_01", "MANAGER", "corr-1")

    class Service:
        def get(self, db, request_context, commitment_id):
            assert request_context is context
            assert commitment_id == commitment.commitment_id
            return commitment

    reader = P5CommitmentReader(Service())
    assert reader.get_commitment(None, context, commitment.commitment_id,
                                 expected_commitment_version=commitment.commitment_version) == commitment
    with pytest.raises(DomainError, match="version is stale"):
        reader.get_commitment(None, context, commitment.commitment_id,
                              expected_commitment_version=commitment.commitment_version + 1)


def test_unavailable_integrations_fail_explicitly_and_actor_is_not_verified():
    context = RequestContext("tenant-1", "user_manager_01", "MANAGER", "corr-1")
    with pytest.raises(DomainError, match="No authoritative"):
        UnavailableOperationalSnapshotProvider().get_snapshot(context, _commitment())
    with pytest.raises(DomainError, match="no agreed public"):
        UnavailableRecoveryEventPublisher().publish(None, context, None)
    actor = UnverifiedP5ContextAdapter().get_verified_context(context)
    assert actor.verified is False
    with pytest.raises(DomainError, match="verified P5 actor"):
        require_verified_actor(actor)
