"""P1 Context Lifecycle Service: evolutive OrderContext generation, merge and review."""



from __future__ import annotations



from datetime import datetime, timezone
import re
from typing import Any
from uuid import uuid4

EXPLICIT_NEW_ORDER_RE = re.compile(
    r"\b(?:new\s+order|separate\s+order|another\s+order|different\s+order|second\s+order|additional\s+order|"
    r"fresh\s+order|independent\s+order|not\s+part\s+of\s+(?:the\s+)?(?:previous|earlier|last)\s+order|"
    r"pesanan\s+baru|pesanan\s+berasingan|order\s+baru|order\s+lain)\b|"
    r"(?:新订单|新的订单|另外一单|另一单|单独下单|新的一单)",
    re.IGNORECASE,
)

EXPLICIT_FOLLOWUP_RE = re.compile(
    r"\b(?:for\s+that\s+order|for\s+the\s+(?:earlier|previous|above|same)\s+order|"
    r"regarding\s+(?:my|the|that|our)\s+order|about\s+(?:my|the|that|our)\s+order|"
    r"the\s+unit\s+is|unit\s+is|quantity\s+is|update\s+(?:my|the|that)\s+order|"
    r"add\s+to\s+(?:my|the|that)\s+order|change\s+(?:my|the|that)\s+order|"
    r"untuk\s+pesanan\s+(?:itu|tadi)|pasal\s+order\s+tadi)\b|"
    r"(?:关于刚才的订单|针对刚才的订单|刚才那单)",
    re.IGNORECASE,
)



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
        extracted_delivery_at: datetime | None = None
        extracted_qualifier: str | None = None
        extracted_special_instructions: str | None = None
        field_evidence: dict[str, list[dict[str, Any]]] = {}
        item_groups: dict[str, dict[str, Any]] = {}
        missing_item_fields = sorted({f.field_name for f in attempt.fields
            if f.field_name in {'sku', 'quantity', 'unit'} and f.validation_status == 'MISSING'} |
            {'sku_mapping' for f in attempt.fields if f.field_name == 'sku'
             and f.metadata.get('disposition') == 'unverified_product'})
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
                         "qualifier": f.qualifier, "validation_status": f.validation_status,
                         "normalization_metadata": f.metadata} for ev in f.evidence]
            gid = (f.metadata.get("group_id") if f.metadata else None) or "g1"
            if gid not in item_groups:
                item_groups[gid] = {"sku": None, "quantity": None, "unit": None}

            if f.validation_status == "VALID":
                if fn == "sku" and f.value:
                    item_groups[gid]["sku"] = f.value
                    field_evidence.setdefault("sku", []).extend(ev_list)
                elif fn == "quantity" and f.value:
                    item_groups[gid]["quantity"] = f.value
                    field_evidence.setdefault("quantity", []).extend(ev_list)
                elif fn == "unit" and f.value:
                    item_groups[gid]["unit"] = f.value
                    field_evidence.setdefault("unit", []).extend(ev_list)
                elif fn == "special_instructions" and f.value:
                    extracted_special_instructions = f.value
                    field_evidence.setdefault("special_instructions", []).extend(ev_list)
                elif fn == "requested_delivery_at" and f.value:
                    try:
                        if "T" in f.value:
                            extracted_delivery_at = datetime.fromisoformat(f.value)
                        else:
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
                field_evidence.setdefault(fn, []).extend(ev_list)
                if fn == "special_instructions" and f.value and not extracted_special_instructions:
                    extracted_special_instructions = f.value
                if f.metadata and f.metadata.get("requires_written_confirmation") == "true" and not extracted_special_instructions:
                    extracted_special_instructions = f.metadata.get("confirmation_constraint") or "manual written confirmation is required"
                if fn == "requested_delivery_at" and f.value and f.metadata and (f.metadata.get("rescheduling") == "true" or f.metadata.get("correction") == "true"):
                    try:
                        if "T" in f.value:
                            extracted_delivery_at = datetime.fromisoformat(f.value)
                    except Exception:
                        extracted_delivery_at = None
                    if f.qualifier:
                        extracted_qualifier = f.qualifier
                    elif f.metadata and "qualifier" in f.metadata:
                        extracted_qualifier = f.metadata["qualifier"]
                if f.metadata and f.metadata.get("domain_supported") == "true" and f.metadata.get("disposition") in ("proposal", "duplicate"):
                    if fn == "sku" and f.value and not item_groups[gid]["sku"]:
                        item_groups[gid]["sku"] = f.value
                    elif fn == "quantity" and f.value and not item_groups[gid]["quantity"]:
                        item_groups[gid]["quantity"] = f.value
                    elif fn == "unit" and f.value and not item_groups[gid]["unit"]:
                        item_groups[gid]["unit"] = f.value

        new_items: list[RequestedItem] = []
        for gid in sorted(item_groups.keys()):
            grp = item_groups[gid]
            if grp.get("sku") and grp.get("quantity") and grp.get("unit"):
                new_items.append(RequestedItem(sku=grp["sku"], quantity=grp["quantity"], unit=grp["unit"]))
        # 4. Determine order reference to bind or find existing context

        target_order_id: str | None = None

        if assoc.verified_order:

            target_order_id = assoc.verified_order.order_id

        existing_context: OrderContextRecord | None = None

        # If this exact message was already linked to a context, return or reuse it
        if hasattr(self.repo, "get_order_context_by_message"):
            already_linked = self.repo.get_order_context_by_message(tenant_id, message_id)
            if already_linked is not None and already_linked.tenant_id == tenant_id:
                existing_context = already_linked

        if existing_context is None and target_order_id:
            existing_context = self.repo.get_order_context_by_order(tenant_id, target_order_id)

        # If not referenced by explicit order_id, only merge into an active uncommitted context
        # when the message is an explicit follow-up/clarification and association is unambiguous.
        # Same sender alone is NEVER sufficient evidence that two messages belong to the same order.
        cust_id = assoc.verified_customer.customer_id if assoc.verified_customer else None
        has_assoc_conflict = bool(assoc.conflicts)
        raw_text_msg = message.raw.text or ""
        is_explicit_new_order = bool(EXPLICIT_NEW_ORDER_RE.search(raw_text_msg))
        has_thread_or_reply = bool(message.raw.reply_to_provider_message_id or message.raw.thread_ref)
        has_explicit_followup_cue = bool(EXPLICIT_FOLLOWUP_RE.search(raw_text_msg))
        has_incoming_sku = any(grp.get("sku") for grp in item_groups.values()) or any(
            f.field_name == "sku" and f.value for f in attempt.fields
        )
        is_partial_clarification = not has_incoming_sku and bool(
            any(grp.get("unit") or grp.get("quantity") for grp in item_groups.values())
            or extracted_delivery_at is not None
        )
        can_attempt_followup_merge = (
            not is_explicit_new_order
            and not has_assoc_conflict
            and (has_thread_or_reply or has_explicit_followup_cue or is_partial_clarification)
        )

        if existing_context is None and can_attempt_followup_merge:
            # 1. Check thread_ref / reply_to_provider_message_id first if present
            if has_thread_or_reply and hasattr(self.repo, "get_contexts_by_thread_or_reply"):
                thread_ctxs = self.repo.get_contexts_by_thread_or_reply(
                    tenant_id,
                    message.raw.sender_identity_id,
                    message.raw.reply_to_provider_message_id,
                    message.raw.thread_ref,
                )
                if len(thread_ctxs) == 1:
                    existing_context = thread_ctxs[0]
                elif len(thread_ctxs) > 1:
                    assoc.conflicts.append(
                        "Ambiguous context association: multiple active order contexts match thread/reply reference; manual review required"
                    )

            # 2. If not resolved via thread/reply and no ambiguity conflict yet, check active contexts for customer/sender
            if existing_context is None and not assoc.conflicts:
                candidate_map: dict[str, OrderContextRecord] = {}
                if cust_id and hasattr(self.repo, "list_active_contexts_by_customer"):
                    for c in self.repo.list_active_contexts_by_customer(tenant_id, cust_id):
                        candidate_map[c.context_id] = c
                elif cust_id and hasattr(self.repo, "get_latest_active_context_by_customer"):
                    c = self.repo.get_latest_active_context_by_customer(tenant_id, cust_id)
                    if c is not None:
                        candidate_map[c.context_id] = c

                if not candidate_map and message.raw.sender_identity_id:
                    if hasattr(self.repo, "list_active_contexts_by_sender"):
                        for c in self.repo.list_active_contexts_by_sender(tenant_id, message.raw.sender_identity_id):
                            candidate_map[c.context_id] = c
                    elif hasattr(self.repo, "get_latest_active_context_by_sender"):
                        c = self.repo.get_latest_active_context_by_sender(tenant_id, message.raw.sender_identity_id)
                        if c is not None:
                            candidate_map[c.context_id] = c

                active_candidates = list(candidate_map.values())
                if len(active_candidates) == 1:
                    existing_context = active_candidates[0]
                elif len(active_candidates) > 1:
                    assoc.conflicts.append(
                        "Ambiguous context association: multiple active order contexts exist for sender without an explicit order reference; manual review required"
                    )

        # Security Guard: PO Reference and Identity Ownership Check
        # An order reference alone is NEVER authorization. Never associate an order belonging to another customer.
        if existing_context is not None:
            # 1. Enforce strict tenant boundary
            if existing_context.tenant_id != tenant_id:
                existing_context = None
            # 2. Enforce customer ownership boundary
            elif (
                existing_context.customer_id
                and assoc.verified_customer
                and existing_context.customer_id != assoc.verified_customer.customer_id
            ):
                # Security conflict: message belongs to a different customer than the existing context
                assoc.conflicts.append(
                    f"Security Conflict: Message sender {assoc.verified_customer.customer_id} cannot access context {existing_context.context_id} owned by {existing_context.customer_id}"
                )
                existing_context = None



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

            # Detect item conflicts and merge follow-up clarifications across conversational messages
            incoming_sku = None
            incoming_qty = None
            incoming_unit = None
            for gid, grp in item_groups.items():
                if grp.get("sku"): incoming_sku = grp["sku"]
                if grp.get("quantity"): incoming_qty = grp["quantity"]
                if grp.get("unit"): incoming_unit = grp["unit"]

            if new_items and existing_context.requested_items:

                ex_it = existing_context.requested_items[0]

                new_it = new_items[0]

                if ex_it.sku != new_it.sku:

                    conflicts.append(f"Product conflict: existing {ex_it.sku} vs message {message_id} {new_it.sku}")

                if ex_it.quantity != new_it.quantity:

                    conflicts.append(f"Quantity conflict: existing {ex_it.quantity} vs message {message_id} {new_it.quantity}")

                if (len(new_items) != len(existing_context.requested_items) or
                    [(i.sku, i.quantity, i.unit) for i in new_items[1:]] !=
                    [(i.sku, i.quantity, i.unit) for i in existing_context.requested_items[1:]] or
                    ex_it.unit != new_it.unit):
                    conflicts.append(f"Item association conflict in message {message_id}; all existing items preserved for review")

            elif new_items and not existing_context.requested_items:

                existing_context.requested_items = new_items

            elif not new_items and existing_context.requested_items:
                # Existing context already has items; check incoming partial terms for conflicts
                ex_it = existing_context.requested_items[0]
                if incoming_sku and incoming_sku != ex_it.sku:
                    conflicts.append(f"Product conflict: existing {ex_it.sku} vs message {message_id} {incoming_sku}")
                if incoming_qty and incoming_qty != ex_it.quantity:
                    conflicts.append(f"Quantity conflict: existing {ex_it.quantity} vs message {message_id} {incoming_qty}")
                if incoming_unit and incoming_unit != ex_it.unit:
                    conflicts.append(f"Unit conflict: existing {ex_it.unit} vs message {message_id} {incoming_unit}")

            elif not new_items and not existing_context.requested_items:
                # Follow-up message supplied partial/clarified item terms (e.g. unit 'pcs' or quantity '50')
                prev_ev = existing_context.field_evidence or {}
                prev_sku = None
                for ev_sku in prev_ev.get("sku", []):
                    if ev_sku.get("normalized_value"):
                        prev_sku = str(ev_sku["normalized_value"]).strip()
                        break
                prev_qty = None
                for ev_q in prev_ev.get("quantity", []):
                    if ev_q.get("normalized_value"):
                        prev_qty = str(ev_q["normalized_value"]).strip()
                        break
                prev_unit = None
                for ev_u in prev_ev.get("unit", []):
                    if ev_u.get("normalized_value"):
                        prev_unit = str(ev_u["normalized_value"]).strip()
                        break

                resolved_sku = incoming_sku or prev_sku
                resolved_qty = incoming_qty or prev_qty
                resolved_unit = incoming_unit or prev_unit

                if resolved_sku and resolved_qty and resolved_unit:
                    try:
                        merged_item = RequestedItem(sku=resolved_sku, quantity=resolved_qty, unit=resolved_unit)
                        existing_context.requested_items = [merged_item]
                    except Exception:
                        pass



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



            for f in attempt.fields:
                intent_val = f.metadata.get("request_intent") if f.metadata else None
                if intent_val in ("ADVERSARIAL", "CANCELLED"):
                    conflicts.append(f"Security guard: {intent_val} intent detected in message {message_id}; review required")
                    break

            for f in attempt.fields:
                if f.metadata:
                    if f.metadata.get("rescheduling") == "true":
                        orig_d = f.metadata.get("original_delivery_date") or f.metadata.get("original_delivery_quote") or "original date"
                        req_d = f.metadata.get("requested_delivery_date") or f.metadata.get("requested_delivery_quote") or "new date"
                        resched_msg = f"Rescheduled delivery: moving from {orig_d} to {req_d}; review required"
                        if resched_msg not in conflicts:
                            conflicts.append(resched_msg)
                    if f.metadata.get("correction") == "true":
                        orig_d = f.metadata.get("original_delivery_date") or f.metadata.get("original_delivery_quote") or "original date"
                        req_d = f.metadata.get("requested_delivery_date") or f.metadata.get("requested_delivery_quote") or "new date"
                        corr_msg = f"Corrected delivery date: {orig_d} replaced with {req_d}; review required"
                        if corr_msg not in conflicts:
                            conflicts.append(corr_msg)
                    if f.metadata.get("quantity_correction") == "true":
                        orig_q = f.metadata.get("original_quantity") or "original quantity"
                        req_q = f.metadata.get("requested_quantity") or f.value or "new quantity"
                        qcorr_msg = f"Corrected quantity: {orig_q} replaced with {req_q}; review required"
                        if qcorr_msg not in conflicts:
                            conflicts.append(qcorr_msg)
                    elif f.metadata.get("date_range") == "true":
                        range_msg = f"Delivery date window range requires operator confirmation of specific deadline: {f.metadata.get('reason', '')}"
                        if range_msg not in conflicts:
                            conflicts.append(range_msg)
                    elif f.metadata.get("multiple_delivery_dates") == "true":
                        multi_msg = "Multiple delivery dates mentioned: split delivery or schedule choice requires review"
                        if multi_msg not in conflicts:
                            conflicts.append(multi_msg)
                    elif f.metadata.get("weekday_conflict") == "true":
                        weekday_msg = f.metadata.get("reason") or "Weekday and calendar date contradict in delivery request"
                        if weekday_msg not in conflicts:
                            conflicts.append(weekday_msg)
                    elif f.metadata.get("approximate") == "true":
                        approx_msg = f.metadata.get("reason") or "Approximate requested delivery time requires operator confirmation"
                        if approx_msg not in conflicts:
                            conflicts.append(approx_msg)
                    elif f.metadata.get("meal_period") and not f.metadata.get("target_time"):
                        meal_msg = f.metadata.get("reason") or f"Meal period '{f.metadata.get('meal_period')}' requires specific delivery time confirmation"
                        if meal_msg not in conflicts:
                            conflicts.append(meal_msg)
                    elif f.metadata.get("unconfirmed_time") == "true":
                        unconf_msg = f.metadata.get("reason") or "Delivery date specified without confirmed delivery time; operator confirmation required"
                        if unconf_msg not in conflicts:
                            conflicts.append(unconf_msg)
                if f.metadata and f.metadata.get("requires_written_confirmation") == "true":
                    instr_text = f.metadata.get("confirmation_constraint") or f.value or "manual written confirmation is required"
                    instr_msg = f"Approval constraint: {instr_text}; manual review required"
                    if instr_msg not in conflicts:
                        conflicts.append(instr_msg)
                    if not extracted_special_instructions:
                        extracted_special_instructions = instr_text



            if (extracted_qualifier == "EXACT" or existing_context.delivery_qualifier == "EXACT"):

                exact_msg = "Delivery precision: EXACT arrival time requires human confirmation as DEADLINE before publication"

                if exact_msg not in conflicts:

                    conflicts.append(exact_msg)



            # Determine readiness
            if existing_context.requested_items:
                # Completely assembled items satisfy sku, quantity, and unit
                missing_item_fields = [f for f in missing_item_fields if f not in ("sku", "quantity", "unit", "requested_items")]

            missing = sorted(set(missing + missing_item_fields))

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

                special_instructions=existing_context.special_instructions or extracted_special_instructions,

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

            for f in attempt.fields:
                intent_val = f.metadata.get("request_intent") if f.metadata else None
                if intent_val in ("ADVERSARIAL", "CANCELLED"):
                    conflicts.append(f"Security guard: {intent_val} intent detected; review required")
                    break

            for f in attempt.fields:
                if f.metadata:
                    if f.metadata.get("rescheduling") == "true":
                        orig_d = f.metadata.get("original_delivery_date") or f.metadata.get("original_delivery_quote") or "original date"
                        req_d = f.metadata.get("requested_delivery_date") or f.metadata.get("requested_delivery_quote") or "new date"
                        resched_msg = f"Rescheduled delivery: moving from {orig_d} to {req_d}; review required"
                        if resched_msg not in conflicts:
                            conflicts.append(resched_msg)
                    if f.metadata.get("correction") == "true":
                        orig_d = f.metadata.get("original_delivery_date") or f.metadata.get("original_delivery_quote") or "original date"
                        req_d = f.metadata.get("requested_delivery_date") or f.metadata.get("requested_delivery_quote") or "new date"
                        corr_msg = f"Corrected delivery date: {orig_d} replaced with {req_d}; review required"
                        if corr_msg not in conflicts:
                            conflicts.append(corr_msg)
                    if f.metadata.get("quantity_correction") == "true":
                        orig_q = f.metadata.get("original_quantity") or "original quantity"
                        req_q = f.metadata.get("requested_quantity") or f.value or "new quantity"
                        qcorr_msg = f"Corrected quantity: {orig_q} replaced with {req_q}; review required"
                        if qcorr_msg not in conflicts:
                            conflicts.append(qcorr_msg)
                    elif f.metadata.get("date_range") == "true":
                        range_msg = f"Delivery date window range requires operator confirmation of specific deadline: {f.metadata.get('reason', '')}"
                        if range_msg not in conflicts:
                            conflicts.append(range_msg)
                    elif f.metadata.get("multiple_delivery_dates") == "true":
                        multi_msg = "Multiple delivery dates mentioned: split delivery or schedule choice requires review"
                        if multi_msg not in conflicts:
                            conflicts.append(multi_msg)
                    elif f.metadata.get("weekday_conflict") == "true":
                        weekday_msg = f.metadata.get("reason") or "Weekday and calendar date contradict in delivery request"
                        if weekday_msg not in conflicts:
                            conflicts.append(weekday_msg)
                    elif f.metadata.get("approximate") == "true":
                        approx_msg = f.metadata.get("reason") or "Approximate requested delivery time requires operator confirmation"
                        if approx_msg not in conflicts:
                            conflicts.append(approx_msg)
                    elif f.metadata.get("meal_period") and not f.metadata.get("target_time"):
                        meal_msg = f.metadata.get("reason") or f"Meal period '{f.metadata.get('meal_period')}' requires specific delivery time confirmation"
                        if meal_msg not in conflicts:
                            conflicts.append(meal_msg)
                    elif f.metadata.get("unconfirmed_time") == "true":
                        unconf_msg = f.metadata.get("reason") or "Delivery date specified without confirmed delivery time; operator confirmation required"
                        if unconf_msg not in conflicts:
                            conflicts.append(unconf_msg)
                if f.metadata and f.metadata.get("requires_written_confirmation") == "true":
                    instr_text = f.metadata.get("confirmation_constraint") or f.value or "manual written confirmation is required"
                    instr_msg = f"Approval constraint: {instr_text}; manual review required"
                    if instr_msg not in conflicts:
                        conflicts.append(instr_msg)
                    if not extracted_special_instructions:
                        extracted_special_instructions = instr_text

            if extracted_qualifier and extracted_qualifier == "EXACT":

                conflicts.append("Delivery precision: EXACT arrival time requires human confirmation as DEADLINE before publication")

            for f in attempt.fields:
                if f.field_name == "unit" and f.validation_status == "UNRESOLVED" and f.metadata and f.metadata.get("domain_supported") == "false":
                    unit_reason = f.metadata.get("reason") or f"Unit '{f.value}' unsupported for catalog SKU"
                    if unit_reason not in conflicts:
                        conflicts.append(unit_reason)

            missing = []

            if not new_items:

                missing.append("requested_items")

            if not extracted_delivery_at:

                missing.append("requested_delivery_at")

            cust_id = assoc.verified_customer.customer_id if assoc.verified_customer else None

            if not cust_id:

                missing.append("customer_identity")



            status: ContextReadinessStatus
            missing = sorted(set(missing + missing_item_fields))

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

                special_instructions=extracted_special_instructions,

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

