"""P1 Core Publisher: converts P1 OrderContextRecord into Core BusinessContext,
enforces publication eligibility gates, and publishes via CoreIntegrationFacade."""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.integration import CoreIntegrationFacade
from app.core.schemas import (
    BusinessContext,
    Commitment,
    ContextStatus,
    CustomerIdentityStatus,
    RequestedItem as CoreRequestedItem,
)
from app.context.order_context_schemas import OrderContextRecord

logger = logging.getLogger(__name__)


class IneligibleContextError(Exception):
    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.reasons = reasons


class CoreContextPublisher:
    def __init__(self, facade: CoreIntegrationFacade | None = None) -> None:
        self.facade = facade or CoreIntegrationFacade()

    def check_eligibility(self, context: OrderContextRecord) -> tuple[bool, list[str]]:
        """Validate whether an OrderContextRecord is eligible for Core publication.

        Strict zero-guessing invariants:
        - status must be INFORMATION_READY
        - customer_identity_status must be LINK_VERIFIED
        - customer_id must be present
        - requested_items must have at least 1 item with positive quantity
        - conflicts must be empty
        - missing_fields must be empty
        """
        reasons: list[str] = []
        if context.status != "INFORMATION_READY":
            reasons.append(f"Context status '{context.status}' is not INFORMATION_READY")
        if context.customer_identity_status != "LINK_VERIFIED":
            reasons.append(
                f"Customer identity status '{context.customer_identity_status}' is not LINK_VERIFIED"
            )
        if not context.customer_id:
            reasons.append("Customer ID is missing")
        if not context.requested_items:
            reasons.append("No requested items present")
        else:
            for idx, item in enumerate(context.requested_items):
                try:
                    qty = Decimal(item.quantity)
                    if qty <= 0:
                        reasons.append(f"Item #{idx + 1} quantity '{item.quantity}' is not positive")
                except Exception:
                    reasons.append(f"Item #{idx + 1} quantity '{item.quantity}' is not a valid decimal")
        if context.conflicts:
            reasons.append(f"Unresolved conflicts: {', '.join(context.conflicts)}")
        if context.missing_fields:
            reasons.append(f"Missing mandatory fields: {', '.join(context.missing_fields)}")

        return (len(reasons) == 0, reasons)

    def to_business_context(self, context: OrderContextRecord) -> BusinessContext:
        """Map P1 OrderContextRecord to canonical Core BusinessContext."""
        delivery_at = context.requested_delivery_at
        special_instructions = context.special_instructions

        if delivery_at is not None:
            if delivery_at.tzinfo is None:
                delivery_at = delivery_at.replace(tzinfo=timezone.utc)
            # If qualifier is DATE_ONLY, bound to operating close (17:00:00 local/UTC) if time is midnight
            if context.delivery_qualifier == "DATE_ONLY":
                if delivery_at.time() == time(0, 0):
                    delivery_at = delivery_at.replace(hour=17, minute=0, second=0)
                tag = "[DATE_ONLY]"
                if special_instructions:
                    if tag not in special_instructions:
                        special_instructions = f"{tag} {special_instructions}"
                else:
                    special_instructions = tag

        core_items = [
            CoreRequestedItem(
                sku=it.sku,
                quantity=Decimal(it.quantity),
                unit=it.unit,
            )
            for it in context.requested_items
        ]

        # Field evidence mapping: P1 field_evidence -> Core dict[str, list[str]]
        mapped_evidence: dict[str, list[str]] = {}
        for field, ev_list in (context.field_evidence or {}).items():
            refs: list[str] = []
            for item in ev_list:
                if isinstance(item, dict):
                    ref = item.get("evidence_ref") or item.get("evidence_id")
                    if not ref:
                        quote = str(item.get("quote", ""))[:16]
                        ref = f"ev_p1_{context.context_id}_{field}_{abs(hash(quote)) % 10000}"
                    refs.append(ref)
                elif isinstance(item, str):
                    refs.append(item)
            if refs:
                mapped_evidence[field] = refs
        if not mapped_evidence:
            mapped_evidence = {"context": [f"ev_p1_ctx_{context.context_id}"]}

        identity_map = {
            "LINK_VERIFIED": CustomerIdentityStatus.LINK_VERIFIED,
            "LINK_CANDIDATE": CustomerIdentityStatus.LINK_CANDIDATE,
            "UNVERIFIED": CustomerIdentityStatus.UNVERIFIED,
            "CONFLICT": CustomerIdentityStatus.CONFLICT,
        }
        identity_status = identity_map.get(
            context.customer_identity_status, CustomerIdentityStatus.UNVERIFIED
        )

        status_map = {
            "INFORMATION_READY": ContextStatus.INFORMATION_READY,
            "INFORMATION_PARTIAL": ContextStatus.INFORMATION_PARTIAL,
            "CONFLICT": ContextStatus.CONFLICT,
            "UNRESOLVED": ContextStatus.UNRESOLVED,
        }
        status = status_map.get(context.status, ContextStatus.UNRESOLVED)

        source_message_ids = (
            list(context.source_message_ids)
            if context.source_message_ids
            else [f"msg_{context.context_id}"]
        )

        return BusinessContext(
            tenant_id=context.tenant_id,
            context_id=context.context_id,
            commitment_id=context.core_commitment_id,
            source_message_ids=source_message_ids,
            customer_id=context.customer_id,
            customer_identity_status=identity_status,
            order_id=context.order_id,
            requested_items=core_items,
            requested_delivery_at=delivery_at,
            special_instructions=special_instructions,
            field_evidence=mapped_evidence,
            conflicts=list(context.conflicts or []),
            missing_fields=list(context.missing_fields or []),
            context_version=context.context_version,
            status=status,
        )

    def publish_to_core(
        self,
        session: Session,
        request_context: RequestContext,
        order_context: OrderContextRecord,
        *,
        enforce_eligibility: bool = True,
    ) -> Commitment:
        """Publish an OrderContextRecord to Core using CoreIntegrationFacade."""
        if enforce_eligibility:
            is_eligible, reasons = self.check_eligibility(order_context)
            if not is_eligible:
                raise IneligibleContextError(
                    f"Context '{order_context.context_id}' is ineligible for Core publication: {', '.join(reasons)}",
                    reasons=reasons,
                )

        business_context = self.to_business_context(order_context)
        commitment = self.facade.handle_context_updated(session, request_context, business_context)

        # Update P1 record with commitment link within the session
        from app.context.postgres_repository import OrderContext

        row = session.scalar(
            select(OrderContext).where(
                OrderContext.tenant_id == order_context.tenant_id,
                OrderContext.context_id == order_context.context_id,
            )
        )
        now = datetime.now(timezone.utc)
        if row is not None:
            row.core_commitment_id = commitment.commitment_id
            row.published_to_core_at = now
            session.commit()

        order_context.core_commitment_id = commitment.commitment_id
        order_context.published_to_core_at = now
        return commitment
