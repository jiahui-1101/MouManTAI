"""Service for Verified Identity and Order Association (Batch 2).

Core Rules:
1. Distinguish platform identity, customer account, verified link, and suggested match.
2. Extracted order reference alone is NEVER authorization.
3. Never establish identity from sender_alias name similarity or model output.
4. If multiple orders exist or sender is unverified, generate AssociationCandidates with reasons.
5. Preserve CONFLICT if extracted order belongs to a different customer than the verified sender.
6. Support manual confirmation/rejection with actor, role, timestamp, reason, and optimistic concurrency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .association_schemas import (
    AssociationCandidate,
    AssociationDecision,
    AssociationDecisionRequest,
    CustomerAccount,
    IdentityLinkStatus,
    MatchType,
    MessageAssociationRecord,
    OrderReference,
)
from .customer_directory import CustomerDirectory, DEFAULT_DIRECTORY
from .ingestion_schemas import StoredMessage


class StaleAssociationVersion(Exception):
    """The association record has evolved since expected_version."""


class AssociationService:
    def __init__(self, directory: CustomerDirectory | None = None) -> None:
        self.directory = directory or DEFAULT_DIRECTORY

    def evaluate_association(
        self,
        message: StoredMessage,
        extracted_fields: list[dict] | None = None,
    ) -> MessageAssociationRecord:
        """Deterministically evaluates identity and order association candidates for a message."""
        raw = message.raw
        tenant_id = raw.tenant_id
        message_id = message.message_id
        now = datetime.now(timezone.utc)

        # 1. Identify verified customer via verified channel lookup (phone / sender_identity_id)
        verified_customer: CustomerAccount | None = self.directory.find_by_sender(
            tenant_id=tenant_id,
            channel=raw.channel,
            sender_identity_id=raw.sender_identity_id,
        )

        # 2. Inspect extracted order references
        extracted_order_ids: list[str] = []
        if extracted_fields:
            for f in extracted_fields:
                if f.get("field_name") == "order_id" and f.get("value"):
                    val = str(f["value"]).strip()
                    if val not in extracted_order_ids:
                        extracted_order_ids.append(val)

        candidates: list[AssociationCandidate] = []
        conflicts: list[str] = []
        verified_order: OrderReference | None = None
        status = IdentityLinkStatus.UNVERIFIED

        # Scenario A: Sender identity is verified
        if verified_customer is not None:
            status = IdentityLinkStatus.LINK_VERIFIED
            customer_orders = self.directory.list_customer_orders(tenant_id, verified_customer.customer_id)

            if not extracted_order_ids:
                # No specific order mentioned
                if len(customer_orders) == 1:
                    # Single active order candidate
                    candidates.append(
                        AssociationCandidate(
                            customer_id=verified_customer.customer_id,
                            customer_name=verified_customer.display_name,
                            order_id=customer_orders[0].order_id,
                            match_type=MatchType.TRUSTED_SENDER,
                            reasons=["Verified sender with exactly one ongoing order"],
                            evidence=[f"Sender {raw.sender_identity_id} bound to {verified_customer.customer_id}"],
                            confidence=0.8,
                        )
                    )
                elif len(customer_orders) > 1:
                    # Multiple ongoing orders -> Never arbitrarily choose! Return all candidates
                    for o in customer_orders:
                        candidates.append(
                            AssociationCandidate(
                                customer_id=verified_customer.customer_id,
                                customer_name=verified_customer.display_name,
                                order_id=o.order_id,
                                match_type=MatchType.TRUSTED_SENDER,
                                reasons=[f"Verified sender has multiple active orders; manual selection required for {o.order_id}"],
                                evidence=[f"Order {o.order_id} ({o.description})"],
                                confidence=0.5,
                            )
                        )
            else:
                # Extracted order references exist
                for ref in extracted_order_ids:
                    order = self.directory.get_order(tenant_id, ref)
                    if order is None:
                        conflicts.append(f"Referenced order {ref} does not exist in tenant {tenant_id}")
                    elif order.customer_id != verified_customer.customer_id:
                        # Conflict! Verified sender references someone else's order!
                        conflicts.append(
                            f"Security Conflict: Verified sender {verified_customer.customer_id} referenced order {ref} belonging to {order.customer_id}"
                        )
                        status = IdentityLinkStatus.CONFLICT
                    else:
                        # Order belongs to verified customer!
                        if len(extracted_order_ids) == 1 and not conflicts:
                            verified_order = order
                        candidates.append(
                            AssociationCandidate(
                                customer_id=verified_customer.customer_id,
                                customer_name=verified_customer.display_name,
                                order_id=order.order_id,
                                match_type=MatchType.EXTRACTED_ORDER_REF,
                                reasons=[f"Verified sender explicitly referenced valid matching order {order.order_id}"],
                                evidence=[f"Quote in text matches {order.order_id}"],
                                confidence=1.0,
                            )
                        )

        # Scenario B: Sender identity is NOT verified
        else:
            if extracted_order_ids:
                status = IdentityLinkStatus.LINK_CANDIDATE
                for ref in extracted_order_ids:
                    order = self.directory.get_order(tenant_id, ref)
                    if order is None:
                        conflicts.append(f"Unverified sender referenced non-existent order {ref}")
                    else:
                        cust = self.directory.get_customer(tenant_id, order.customer_id)
                        cust_name = cust.display_name if cust else "Unknown Customer"
                        # Extracted order reference alone is NEVER authorization. Propose candidate only.
                        candidates.append(
                            AssociationCandidate(
                                customer_id=order.customer_id,
                                customer_name=cust_name,
                                order_id=order.order_id,
                                match_type=MatchType.EXTRACTED_ORDER_REF,
                                reasons=[
                                    f"Explicit reference {ref} found, but sender {raw.sender_identity_id} is unverified. Manual authorization required."
                                ],
                                evidence=[f"Unverified sender {raw.sender_identity_id} referenced {ref}"],
                                confidence=0.4,
                            )
                        )
            else:
                # Unknown sender and no order reference
                status = IdentityLinkStatus.UNVERIFIED

        if conflicts and status != IdentityLinkStatus.CONFLICT:
            status = IdentityLinkStatus.CONFLICT

        return MessageAssociationRecord(
            association_id=str(uuid4()),
            tenant_id=tenant_id,
            message_id=message_id,
            status=status,
            verified_customer=verified_customer,
            verified_order=verified_order,
            candidates=candidates,
            conflicts=conflicts,
            last_decision=None,
            version=1,
            updated_at=now,
        )

    def apply_decision(
        self,
        current: MessageAssociationRecord,
        request: AssociationDecisionRequest,
        actor_id: str,
        actor_role: str,
    ) -> MessageAssociationRecord:
        """Applies manual authorization/rejection with optimistic locking."""
        if current.version != request.expected_version:
            raise StaleAssociationVersion(
                f"Association version mismatch: expected {request.expected_version}, current {current.version}"
            )

        now = datetime.now(timezone.utc)
        decision = AssociationDecision(
            decision=request.decision,
            target_customer_id=request.target_customer_id,
            target_order_id=request.target_order_id,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=request.reason,
            decided_at=now,
        )

        verified_cust = current.verified_customer
        verified_ord = current.verified_order
        status = current.status

        if request.decision == "CONFIRMED":
            if request.target_customer_id:
                cust = self.directory.get_customer(current.tenant_id, request.target_customer_id)
                if cust:
                    verified_cust = cust
                    status = IdentityLinkStatus.LINK_VERIFIED
            if request.target_order_id:
                ord_ref = self.directory.get_order(current.tenant_id, request.target_order_id)
                if ord_ref:
                    verified_ord = ord_ref
        elif request.decision == "REJECTED":
            verified_cust = None
            verified_ord = None
            status = IdentityLinkStatus.UNVERIFIED

        return MessageAssociationRecord(
            association_id=current.association_id,
            tenant_id=current.tenant_id,
            message_id=current.message_id,
            status=status,
            verified_customer=verified_cust,
            verified_order=verified_ord,
            candidates=current.candidates,
            conflicts=current.conflicts,
            last_decision=decision,
            version=current.version + 1,
            updated_at=now,
        )
