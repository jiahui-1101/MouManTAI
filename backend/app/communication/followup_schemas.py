"""P4-local scheduler contracts; no changes to Core lifecycle contracts."""
from typing import Literal

from pydantic import Field, model_validator

from app.core.schemas import ContractModel, OffsetAwareDatetime
from .preferences import ContactHours, Id


class SLAPolicy(ContractModel):
    version: Literal["p4-followup-v1"] = "p4-followup-v1"
    response_sla_seconds: int = Field(default=300, strict=True, ge=60, le=604800)
    max_reminders: int = Field(default=1, strict=True, ge=0, le=3)
    minimum_interval_seconds: int = Field(default=300, strict=True, ge=60, le=604800)
    escalation_delay_seconds: int = Field(default=300, strict=True, ge=60, le=604800)
    contact_hours: ContactHours = Field(default_factory=ContactHours)
    timezone: Literal["UTC", "Asia/Kuala_Lumpur"] = "Asia/Kuala_Lumpur"


class ScheduleFollowUp(ContractModel):
    confirmation_id: Id
    request_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    policy: SLAPolicy = Field(default_factory=SLAPolicy)


class CancelFollowUp(ContractModel):
    reason: str = Field(min_length=1, max_length=256)


class FollowUpView(ContractModel):
    task_id: str
    tenant_id: str
    communication_id: str
    confirmation_id: str
    commitment_id: str
    proposal_id: str
    proposal_version: int
    status: Literal["WAITING", "BLOCKED", "DISPATCHING", "CANCELLED", "ESCALATED"]
    reason_code: str | None
    policy: SLAPolicy
    reminders_sent: int
    next_due_at: OffsetAwareDatetime | None
    escalation_at: OffsetAwareDatetime
    last_reminder_at: OffsetAwareDatetime | None
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime


class ReminderAuthorization(ContractModel):
    """Issued only by a trusted server adapter, never accepted in HTTP input.

    The adapter must authorize EACH action; SEND_MESSAGE alone is insufficient
    to authorize repeat contact or to change the policy approved at scheduling.
    """
    tenant_id: Id
    actor_id: Id
    action: Literal["READ_FOLLOWUP", "SCHEDULE_FOLLOWUP", "CANCEL_FOLLOWUP", "DISPATCH_REMINDER"]
    confirmation_id: str | None = None
    policy_digest: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    expires_at: OffsetAwareDatetime

    @model_validator(mode="after")
    def scoped_write(self):
        if self.action != "READ_FOLLOWUP" and (not self.confirmation_id or not self.policy_digest):
            raise ValueError("Write grants must bind the exact confirmation and SLA policy")
        return self
