"""P1 Context Lifecycle Service: evolutive OrderContext generation, merge and review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .association_schemas import IdentityLinkStatus
from .association_service import AssociationService
from .order_context_schemas import (
    ContextReadinessStatus,
    ContextReviewRequest,
    ContextUpdateRequest,
    OrderContextRecord,
    RequestedItem,
)
from .repository import (
    ContextNotFound,
    ExtractionNotFound,
    MessageNotFound,
    MessageRepository,
    StaleContextVersion,
)


class ContextService:
    def __init__(self, repository: MessageRepository):
        self.repo = repository

    def create_or_update_from_message(self, tenant_id: str, message_id: str) -> OrderContextRecord:
        message = self.repo.get(tenant_id, message_id)
        if message is None:
            raise MessageNotFound(f"Message {message_id} not found")
        existing_lookup = getattr(self.repo, 'get_order_context_by_message', None)
        existing_for_message = existing_lookup(tenant_id, message_id) if existing_lookup else None
        if existing_for_message:
            # Reprocessing changes extraction history, never the reviewed
            # context automatically. Explicit review is the versioned edit path.
            return existing_for_message

        # 1. Retrieve latest extraction attempt
        try:
            attempt = self.repo.get_latest_extraction(tenant_id, message_id)
        except ExtractionNotFound:
            attempt = None

        if attempt is None:
            # Trigger process if not yet extracted
            proc = self.repo.process(tenant_id, message_id)
            attempt = proc.attempt

        # 2. Retrieve or evaluate association
        assoc = self.repo.get_association(tenant_id, message_id)
        if assoc is None:
            extracted_dicts = [f.model_dump(mode="json") for f in attempt.fields]
            assoc_svc = AssociationService()
            assoc_record = assoc_svc.evaluate_association(message, extracted_dicts)
            assoc = self.repo.save_association(assoc_record)

        # 3. Parse fields from extraction attempt
        extracted_sku: str | None = None
        extracted_qty: str | None = None
        extracted_unit: str | None = None
        extracted_delivery_at: datetime | None = None
        extracted_qualifier: str | None = None
        field_evidence: dict[str, list[dict[str, Any]]] = {}
        uncertain_terms = sorted({f.field_name for f in attempt.fields
            if f.validation_status in {'INVALID', 'UNRESOLVED', 'CONFLICT'}
            and f.field_name in {'sku', 'quantity', 'unit', 'requested_delivery_at'}
            and any(ev.method == 'RULE' for ev in f.evidence)})

        for f in attempt.fields:
            fn = "sku" if f.field_name in ("sku", "product") else (
                "requested_delivery_at" if f.field_name in ("requested_delivery_at", "delivery_datetime", "delivery_date")
                else f.field_name
            )
            ev_list = [{**ev.model_dump(mode="json"), "normalized_value": f.value,
                        "qualifier": f.qualifier, "normalization_metadata": f.metadata} for ev in f.evidence]
            if f.validation_status == "VALID":
                if fn == "sku" and f.value:
                    extracted_sku = f.value
                    field_evidence["sku"] = ev_list
                elif fn == "quantity" and f.value:
                    extracted_qty = f.value
                    field_evidence["quantity"] = ev_list
                elif fn == "unit" and f.value:
                    extracted_unit = f.value
                    field_evidence["unit"] = ev_list
                elif fn == "requested_delivery_at" and f.value:
                    try:
                        if "T" in f.value:
                            extracted_delivery_at = datetime.fromisoformat(f.value)
                        else:
                            # Preserve date in JSON evidence; the datetime contract
                            # cannot express date-only. No fabricated midnight.
                            extracted_delivery_at = None
                    except Exception:
                        extracted_delivery_at = None
                    field_evidence["requested_delivery_at"] = ev_list
                    if f.metadata and "relation" in f.metadata:
                        extracted_qualifier = f.metadata["relation"]
                    elif f.metadata and "qualifier" in f.metadata:
                        extracted_qualifier = f.metadata["qualifier"]
                    elif f.qualifier:
                        extracted_qualifier = f.qualifier
            else:
                # Retain candidate model proposals or unresolved fields in field_evidence
                # if no VALID field exists, so that the operator in ReviewDrawer can see
                # and explicitly apply/confirm them. We NEVER auto-promote them to new_items.
                if fn not in field_evidence and ev_list:
                    field_evidence[fn] = ev_list

        new_items: list[RequestedItem] = []
        if extracted_sku and extracted_qty and extracted_unit:
            new_items.append(RequestedItem(sku=extracted_sku, quantity=extracted_qty, unit=extracted_unit))

        # 4. Determine order reference to bind or find existing context
        target_order_id: str | None = None
        if assoc.verified_order:
            target_order_id = assoc.verified_order.order_id

        existing_context: OrderContextRecord | None = None
        if target_order_id:
            existing_context = self.repo.get_order_context_by_order(tenant_id, target_order_id)

        now = datetime.now(timezone.utc)

        # 5. Merge into existing context or create new
        if existing_context is not None:
            # Reopening/reprocessing a linked message must not rewrite a human
            # review or create another version of the identical source merge.
            if message_id in existing_context.source_message_ids:
                return existing_context
            conflicts = list(existing_context.conflicts)
            for name in uncertain_terms:
                conflicts.append(f"Incoming {name} from message {message_id} requires review; existing value preserved")
            # Detect item conflicts
            if new_items and existing_context.requested_items:
                ex_it = existing_context.requested_items[0]
                new_it = new_items[0]
                if ex_it.sku != new_it.sku:
                    conflicts.append(f"Product conflict: existing {ex_it.sku} vs message {message_id} {new_it.sku}")
                if ex_it.quantity != new_it.quantity:
                    conflicts.append(f"Quantity conflict: existing {ex_it.quantity} vs message {message_id} {new_it.quantity}")
            elif new_items and not existing_context.requested_items:
                existing_context.requested_items = new_items

            # Detect delivery conflicts
            if extracted_delivery_at and existing_context.requested_delivery_at:
                if extracted_delivery_at != existing_context.requested_delivery_at:
                    conflicts.append(
                        f"Delivery conflict: existing {existing_context.requested_delivery_at.isoformat()} vs message {message_id} {extracted_delivery_at.isoformat()}"
                    )
            elif extracted_delivery_at and not existing_context.requested_delivery_at:
                existing_context.requested_delivery_at = extracted_delivery_at
                existing_context.delivery_qualifier = extracted_qualifier

            # Append source message
            source_ids = list(existing_context.source_message_ids)
            if message_id not in source_ids:
                source_ids.append(message_id)

            # Merge evidence
            merged_ev = dict(existing_context.field_evidence)
            for k, v in field_evidence.items():
                merged_ev.setdefault(k, []).extend(v)

            # Re-evaluate missing fields
            missing: list[str] = []
            if not existing_context.requested_items:
                missing.append("requested_items")
            if not existing_context.requested_delivery_at:
                missing.append("requested_delivery_at")
            if not existing_context.customer_id:
                missing.append("customer_identity")

            # Determine readiness
            if conflicts:
                status: ContextReadinessStatus = "CONFLICT"
            elif missing:
                status = "INFORMATION_PARTIAL"
            elif existing_context.customer_identity_status != "LINK_VERIFIED":
                status = "INFORMATION_PARTIAL"
            else:
                status = "INFORMATION_READY"

            updated_record = OrderContextRecord(
                context_id=existing_context.context_id,
                tenant_id=tenant_id,
                order_id=existing_context.order_id,
                customer_id=existing_context.customer_id,
                customer_identity_status=existing_context.customer_identity_status,
                status=status,
                context_version=existing_context.context_version,
                requested_items=existing_context.requested_items,
                requested_delivery_at=existing_context.requested_delivery_at,
                delivery_qualifier=existing_context.delivery_qualifier,
                special_instructions=existing_context.special_instructions,
                source_message_ids=source_ids,
                field_evidence=merged_ev,
                missing_fields=missing,
                conflicts=conflicts,
                last_reviewed_by=existing_context.last_reviewed_by,
                last_reviewed_role=existing_context.last_reviewed_role,
                last_reviewed_at=existing_context.last_reviewed_at,
                core_commitment_id=existing_context.core_commitment_id,
                published_to_core_at=existing_context.published_to_core_at,
                created_at=existing_context.created_at,
                updated_at=now,
            )
            return self.repo.save_order_context(
                updated_record,
                change_type="MESSAGE_MERGE",
                reason=f"Merged follow-up message {message_id}",
            )
        else:
            # Create new OrderContext
            conflicts = list(assoc.conflicts)
            missing = []
            if not new_items:
                missing.append("requested_items")
            if not extracted_delivery_at:
                missing.append("requested_delivery_at")
            cust_id = assoc.verified_customer.customer_id if assoc.verified_customer else None
            if not cust_id:
                missing.append("customer_identity")

            status: ContextReadinessStatus
            if conflicts:
                status = "CONFLICT"
            elif missing:
                status = "INFORMATION_PARTIAL"
            elif assoc.status != IdentityLinkStatus.LINK_VERIFIED:
                status = "INFORMATION_PARTIAL"
            else:
                status = "INFORMATION_READY"

            new_record = OrderContextRecord(
                context_id=str(uuid4()),
                tenant_id=tenant_id,
                order_id=target_order_id,
                customer_id=cust_id,
                customer_identity_status=assoc.status.value,
                status=status,
                context_version=1,
                requested_items=new_items,
                requested_delivery_at=extracted_delivery_at,
                delivery_qualifier=extracted_qualifier,
                special_instructions=None,
                source_message_ids=[message_id],
                field_evidence=field_evidence,
                missing_fields=missing,
                conflicts=conflicts,
                created_at=now,
                updated_at=now,
            )
            return self.repo.save_order_context(
                new_record,
                change_type="INITIAL_CREATION",
                reason=f"Created from message {message_id}",
            )

    def review_context(
        self,
        tenant_id: str,
        context_id: str,
        request: ContextReviewRequest,
        actor_id: str,
        actor_role: str,
    ) -> OrderContextRecord:
        return self.repo.apply_context_review(tenant_id, context_id, request, actor_id=actor_id, actor_role=actor_role)

    def update_context(
        self,
        tenant_id: str,
        context_id: str,
        request: ContextUpdateRequest,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> OrderContextRecord:
        updates: dict[str, Any] = {}
        if request.requested_items is not None:
            updates["requested_items"] = request.requested_items
        if request.requested_delivery_at is not None:
            updates["requested_delivery_at"] = request.requested_delivery_at
        if request.delivery_qualifier is not None:
            updates["delivery_qualifier"] = request.delivery_qualifier
        if request.special_instructions is not None:
            updates["special_instructions"] = request.special_instructions

        return self.repo.update_order_context(
            tenant_id=tenant_id,
            context_id=context_id,
            expected_version=request.expected_context_version,
            updates=updates,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=request.reason,
        )
