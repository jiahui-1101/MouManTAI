from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.fixture_loader import resolve_fixture_path
from app.core.schemas import Commitment, FeasibilityAssessment

from .models import ApprovalDecision, OperationalSnapshotReference


@dataclass(frozen=True)
class DemoRecoveryInputs:
    commitment: Commitment
    assessment: FeasibilityAssessment
    snapshot: OperationalSnapshotReference
    approval: ApprovalDecision
    customer_confirmation_evidence_refs: list[str]
    fulfilment_evidence_refs: list[str]
    incident_evidence_refs: list[str]


def _fixture_path() -> Path:
    return resolve_fixture_path("demo_dataset.json")


def load_demo_recovery_inputs() -> DemoRecoveryInputs:
    payload: dict[str, Any] = json.loads(_fixture_path().read_text(encoding="utf-8"))
    commitment = Commitment.model_validate(payload["commitment"])
    assessment = FeasibilityAssessment.model_validate(payload["feasibility_assessment"])
    snapshot_payload = payload["operational_snapshot"]
    snapshot = OperationalSnapshotReference.model_validate(
        {
            "snapshot_id": snapshot_payload["snapshot_id"],
            "snapshot_version": snapshot_payload["snapshot_version"],
            "captured_at": snapshot_payload["captured_at"],
            "source": snapshot_payload["source"],
            "evidence_refs": ["ev_stock_001", "ev_supplier_003"],
        }
    )

    approval_payload = payload["approval"]
    approval = ApprovalDecision.model_validate(
        {
            "approval_id": approval_payload["approval_id"],
            "tenant_id": commitment.tenant_id,
            "commitment_id": commitment.commitment_id,
            "plan_id": approval_payload["plan_id"],
            "plan_version": approval_payload["plan_version"],
            "snapshot_version": approval_payload["snapshot_version"],
            "actor_id": approval_payload["actor_id"],
            "actor_role": approval_payload["actor_role"],
            "decision": approval_payload["decision"],
            "approved_cost_limit": approval_payload["approved_cost_limit"],
            "reason": approval_payload["decision_reason"],
            "expires_at": approval_payload["expires_at"],
            "evidence_refs": approval_payload["evidence_refs"],
        }
    )

    confirmation = payload["confirmation"]
    fulfilment = payload["fulfilment_evidence"]
    return DemoRecoveryInputs(
        commitment=commitment,
        assessment=assessment,
        snapshot=snapshot,
        approval=approval,
        customer_confirmation_evidence_refs=list(confirmation["response_evidence_refs"]),
        fulfilment_evidence_refs=[fulfilment["evidence_id"]],
        incident_evidence_refs=list(assessment.evidence_refs),
    )
