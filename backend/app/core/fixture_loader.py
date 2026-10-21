from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .schemas import (
    BusinessContext,
    Commitment,
    CommunicationRequest,
    Confirmation,
    ContractModel,
    FeasibilityAssessment,
    RecoveryPlan,
)


class DemoFixture(ContractModel):
    tenant_id: str = Field(min_length=1)
    business_context: BusinessContext
    commitment: Commitment
    operational_snapshot: dict[str, Any]
    supplier_delay: dict[str, Any]
    feasibility_assessment: FeasibilityAssessment
    revalidated_assessment: FeasibilityAssessment
    recovery_plans: list[RecoveryPlan] = Field(min_length=2)
    approval: dict[str, Any]
    communication_request: CommunicationRequest
    confirmation: Confirmation
    fulfilment_evidence: dict[str, Any]

    @model_validator(mode="after")
    def validate_cross_contract_links(self) -> "DemoFixture":
        models = [
            self.business_context,
            self.commitment,
            self.feasibility_assessment,
            self.revalidated_assessment,
            *self.recovery_plans,
            self.communication_request,
            self.confirmation,
        ]
        if any(model.tenant_id != self.tenant_id for model in models):
            raise ValueError("all demo fixture contracts must share tenant_id")
        if self.commitment.commitment_id not in self.feasibility_assessment.affected_commitment_ids:
            raise ValueError("active commitment must be represented in the assessment impact list")
        if any(plan.commitment_id != self.commitment.commitment_id for plan in self.recovery_plans):
            raise ValueError("all recovery plans must target the fixture commitment")
        if self.confirmation.proposal_version != self.communication_request.proposal_version:
            raise ValueError("communication and confirmation must use the same proposal version")
        return self


def load_demo_fixture() -> DemoFixture:
    path = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "demo_dataset.json"
    return DemoFixture.model_validate(json.loads(path.read_text(encoding="utf-8")))
