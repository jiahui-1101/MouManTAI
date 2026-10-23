"""v2.2 operational seams; implementations require verified provider contracts.

All arguments come from authenticated server context and persisted intent, not
an LLM/client authority claim. The caller owns durable reconciliation and Core
state/outbox. A receipt cannot itself grant acceptance or human approval.
"""

from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, model_validator

from app.core.errors import DomainError
from app.feasibility.production import EvaluationSnapshot
from app.orders.terms import Evidence, ImmutableContract, OrderTerms, Text


class ReservationCommand(ImmutableContract):
    tenant_id: Text
    order_request_id: Text
    request_version: int = Field(ge=1)
    terms: OrderTerms
    snapshot_id: Text
    snapshot_version: int = Field(ge=1)
    assessment_id: Text
    idempotency_key: Text

    @model_validator(mode="after")
    def terms_binding(self):
        if (self.tenant_id, self.order_request_id) != (self.terms.tenant_id, self.terms.order_request_id):
            raise ValueError("Reservation terms must belong to this tenant and order")
        if self.request_version != self.terms.terms_revision:
            raise ValueError("Reservation terms revision must match request")
        return self


class ReservationReceipt(ImmutableContract):
    tenant_id: Text
    order_request_id: Text
    operation_id: Text
    idempotency_key: Text
    request_version: int = Field(ge=1)
    terms_hash: str = Field(pattern=r"^order-terms-v1:[0-9a-f]{64}$")
    snapshot_version: int = Field(ge=1)
    status: Literal["PENDING", "CONFIRMED", "UNKNOWN", "FAILED", "RELEASED"]
    mode: Literal["SYNTHETIC", "MOCK", "LIVE"]
    checked_at: AwareDatetime
    reservation_ids: tuple[Text, ...] = ()
    evidence_refs: tuple[Text, ...]

    @model_validator(mode="after")
    def success_evidence(self):
        if self.status == "CONFIRMED" and (not self.reservation_ids or not self.evidence_refs):
            raise ValueError("Confirmed reservation requires resource IDs and receipt evidence")
        return self

    @property
    def reservation_confirmed(self) -> bool:
        """Structural receipt status only; verify binding and source authenticity separately."""
        return self.status == "CONFIRMED"


def require_receipt_binding(receipt: ReservationReceipt, *, tenant_id: str, order_request_id: str,
                            operation_id: str, idempotency_key: str, request_version: int,
                            terms_hash: str) -> None:
    expected = dict(tenant_id=tenant_id, order_request_id=order_request_id,
                    operation_id=operation_id, idempotency_key=idempotency_key,
                    request_version=request_version, terms_hash=terms_hash)
    if any(getattr(receipt, name) != value for name, value in expected.items()):
        raise DomainError("RESERVATION_RECEIPT_MISMATCH", "Reservation receipt does not match intent",
                          status_code=409)


class ReviewNotification(ImmutableContract):
    tenant_id: Text
    task_id: Text
    source_ref: Text
    idempotency_key: Text
    evidence_refs: Evidence


class BusinessDataReader(Protocol):
    def get_operational_snapshot(self, tenant_id: str) -> EvaluationSnapshot:
        """Use the real P2 stock/BOM/schedule type; no feature-local calculator."""
        ...


class BusinessCommandPort(Protocol):
    def reserve_resources(self, command: ReservationCommand) -> ReservationReceipt: ...

    def read_reservation_status(self, tenant_id: str, operation_id: str) -> ReservationReceipt: ...

    def release_reservation(self, tenant_id: str, operation_id: str,
                            idempotency_key: str) -> ReservationReceipt:
        """Only after caller validates its persisted intent/compensation policy."""
        ...


class ApprovalNotificationPort(Protocol):
    def publish_review_task(self, notification: ReviewNotification) -> str: ...

    def verify_approval_callback(self, signed_payload: bytes) -> str:
        """Return authenticated receipt reference; never infer approval from raw content."""
        ...
