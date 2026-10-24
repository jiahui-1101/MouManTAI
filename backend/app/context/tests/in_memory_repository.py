"""In-memory MessageRepository implementation for high-speed isolated unit testing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.context.association_schemas import MessageAssociationRecord
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION, extract_explicit_fields
from app.context.document_schemas import AttachmentRecord, DocumentExtractionResult
from app.context.ingestion_schemas import (
    ExtractionAttemptRecord,
    IngestResponse,
    MessagePage,
    ProcessResponse,
    StoredMessage,
)
from app.context.order_context_schemas import (
    ContextReviewRecord,
    ContextReviewRequest,
    OrderContextRecord,
    OrderContextVersionRecord,
    RequestedItem,
)
from app.context.repository import DuplicateConflict, MessageNotFound, PersistenceUnavailable
from app.context.schemas import Channel, ExtractedField, ProcessingStatus, RawMessageEnvelope
from app.context.channels.reply_framing import ParentResolution, ReplyFrame, resolve_parent


def _fingerprint(envelope: RawMessageEnvelope) -> str:
    content = envelope.model_dump(mode="json", exclude={"received_at"})
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InMemoryMessageRepository:
    """Complete in-memory test repository implementing MessageRepository."""

    def __init__(self, catalog: list[str] | None = None, *, proposal_service=None):
        self.catalog = PROVISIONAL_PRODUCTS if catalog is None else catalog
        self._proposal_service = proposal_service
        self.messages: dict[tuple[str, str], StoredMessage] = {}  # (tenant_id, message_id) -> StoredMessage
        self.fingerprints: dict[tuple[str, ...], tuple[str, str]] = {}
        self.parent_links: dict[tuple[str, str], tuple[str, str | None]] = {}
        self.attempts: dict[tuple[str, str], list[ExtractionAttemptRecord]] = {}
        self.attachments: dict[tuple[str, str], tuple[AttachmentRecord, bytes]] = {}  # (tenant_id, evidence_ref) -> (record, bytes)
        self.contexts: dict[tuple[str, str], OrderContextRecord] = {}  # (tenant_id, context_id) -> record
        self.associations: dict[tuple[str, str], MessageAssociationRecord] = {}

    @property
    def proposal_service(self):
        if self._proposal_service is None:
            from app.context.extraction import prepare_model_proposal_service
            self._proposal_service = prepare_model_proposal_service()
        return self._proposal_service

    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse:
        if envelope.provider_account_id and envelope.provider_native_message_id:
            scope = (envelope.conversation_id or "") if envelope.channel == "TELEGRAM" else ""
            key = (envelope.tenant_id, envelope.channel, envelope.provider_account_id, scope,
                   envelope.provider_native_message_id)
        else:
            key = (envelope.tenant_id, envelope.channel, "LEGACY", envelope.provider_message_id)
        digest = _fingerprint(envelope)

        if key in self.fingerprints:
            existing_id, existing_digest = self.fingerprints[key]
            if existing_digest != digest:
                raise DuplicateConflict("Provider message ID already has different original content")
            stored = self.messages[(envelope.tenant_id, existing_id)]
            return IngestResponse(message=stored, duplicate=True)

        msg_id = str(uuid4())
        is_real = getattr(envelope, "adapter_mode", "SYNTHETIC") == "REAL"
        if is_real:
            synthetic_provider = None
            if envelope.channel == "TELEGRAM":
                provider = "TELEGRAM_BOT_API"
                source_label = "Telegram"
            elif envelope.channel == "EMAIL":
                provider = "GMAIL_API"
                source_label = "Gmail"
            elif envelope.channel == "WHATSAPP":
                provider = "WHATSAPP_CLOUD_API"
                source_label = "WhatsApp"
            else:
                provider = "REAL"
                source_label = envelope.channel.capitalize()
        else:
            synthetic_provider = f"SYNTHETIC_{envelope.channel}"
            provider = "SYNTHETIC"
            source_label = "Synthetic"

        stored = StoredMessage(
            message_id=msg_id,
            raw=envelope,
            synthetic_provider=synthetic_provider,
            provider=provider,
            source_label=source_label,
            content_sha256=hashlib.sha256(envelope.text.encode("utf-8")).hexdigest(),
            processing_status="RECEIVED",
            extractor_version=None,
            ingested_at=now,
            updated_at=now,
        )
        self.messages[(envelope.tenant_id, msg_id)] = stored
        self.fingerprints[key] = (msg_id, digest)
        resolution, parent = self._resolve_parent(envelope)
        self.parent_links[(envelope.tenant_id, msg_id)] = (
            resolution.state,
            parent.message_id if parent is not None else None,
        )
        self._reconcile_parent_links(envelope)
        return IngestResponse(message=stored, duplicate=False)

    @staticmethod
    def _as_frame(raw: RawMessageEnvelope, *, parent: bool = False) -> ReplyFrame | None:
        if not raw.provider_account_id or not raw.provider_native_message_id:
            return None
        provider = {"TELEGRAM": "TELEGRAM", "WHATSAPP": "WHATSAPP", "EMAIL": "EMAIL"}.get(raw.channel)
        if not provider:
            return None
        exact_parent = None if parent else (
            (raw.rfc_in_reply_to or [None])[0] if provider == "EMAIL" else raw.reply_to_provider_message_id
        )
        try:
            return ReplyFrame(
                raw.tenant_id,
                provider,
                raw.provider_account_id,
                raw.provider_native_message_id,
                raw.sender_identity_id,
                raw.conversation_id,
                exact_parent,
                raw.relationship_source if exact_parent else "NONE",
                raw.rfc_message_id,
                tuple(raw.rfc_in_reply_to),
                tuple(raw.rfc_references),
                tuple(raw.native_attachment_source_ids),
            )
        except ValueError:
            return None

    def _resolve_parent(self, raw: RawMessageEnvelope) -> tuple[ParentResolution, StoredMessage | None]:
        reference = (raw.rfc_in_reply_to or [None])[0] if raw.channel == "EMAIL" else raw.reply_to_provider_message_id
        if not reference:
            return ParentResolution("NO_EXACT_PARENT"), None
        if raw.framing_error:
            return ParentResolution("INVALID"), None
        reply = self._as_frame(raw)
        if reply is None or raw.relationship_source not in {"PROVIDER_QUOTE", "SENDER_HEADER"}:
            return ParentResolution("UNRESOLVED"), None
        candidates: list[tuple[StoredMessage, ReplyFrame]] = []
        for (candidate_tenant, _), candidate in self.messages.items():
            candidate_raw = candidate.raw
            if candidate_tenant != raw.tenant_id or candidate_raw.source_authenticity != "VERIFIED":
                continue
            frame = self._as_frame(candidate_raw, parent=True)
            if frame:
                candidates.append((candidate, frame))
        result = resolve_parent(reply, [frame for _, frame in candidates])
        if result.state != "REFERENCE_MATCH":
            return result, None
        matched = [message for message, frame in candidates if frame.native_message_id == result.parent_native_id]
        if len(matched) != 1:
            return ParentResolution("AMBIGUOUS"), None
        return result, matched[0]

    def _reconcile_parent_links(self, _new_message: RawMessageEnvelope) -> None:
        for (tenant_id, message_id), child in list(self.messages.items()):
            if tenant_id != _new_message.tenant_id or self.parent_links[(tenant_id, message_id)][0] not in {
                "UNRESOLVED", "REFERENCE_MATCH", "AMBIGUOUS"
            }:
                continue
            result, parent = self._resolve_parent(child.raw)
            self.parent_links[(tenant_id, message_id)] = (result.state, parent.message_id if parent else None)

    def resolve_exact_parent(self, tenant_id: str, message_id: str) -> ParentResolution:
        link = self.parent_links.get((tenant_id, message_id))
        if link is None:
            return ParentResolution("UNRESOLVED")
        state, parent_id = link
        if state != "REFERENCE_MATCH" or not parent_id:
            return ParentResolution(state)  # type: ignore[arg-type]
        parent = self.messages.get((tenant_id, parent_id))
        return ParentResolution("REFERENCE_MATCH", parent.raw.provider_native_message_id if parent else None)

    def get_contexts_by_exact_parent(self, tenant_id: str, message_id: str) -> list[OrderContextRecord]:
        link = self.parent_links.get((tenant_id, message_id))
        if not link or link[0] != "REFERENCE_MATCH" or not link[1]:
            return []
        return [context for (ctx_tenant, _), context in self.contexts.items()
                if ctx_tenant == tenant_id and link[1] in context.source_message_ids
                and context.core_commitment_id is None
                and context.status in {"INFORMATION_PARTIAL", "UNRESOLVED", "CONFLICT"}]

    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None:
        return self.messages.get((tenant_id, message_id))

    def list(
        self,
        tenant_id: str,
        *,
        channel: Channel | None = None,
        search: str = "",
        processing_status: ProcessingStatus | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> MessagePage:
        items = [m for (t, _), m in self.messages.items() if t == tenant_id]
        if channel:
            items = [m for m in items if m.raw.channel == channel]
        if processing_status:
            items = [m for m in items if m.processing_status == processing_status]
        if search:
            items = [m for m in items if search.lower() in m.raw.text.lower()]

        items.sort(key=lambda m: m.ingested_at, reverse=True)
        total = len(items)
        paged = items[offset : offset + limit]
        return MessagePage(items=paged, total=total, limit=limit, offset=offset)

    def process(
        self,
        tenant_id: str,
        message_id: str,
        *,
        reprocess: bool = False,
        now: datetime | None = None,
        operation_id: str | None = None,
    ) -> ProcessResponse:
        key = (tenant_id, message_id)
        if key not in self.messages:
            raise MessageNotFound(f"Message {message_id} not found")

        msg = self.messages[key]
        current_time = now or datetime.now(timezone.utc)

        # Run extraction
        extraction_res = extract_explicit_fields(msg, catalog=self.catalog)
        from app.context.reconciliation import reconcile_canonical_fields
        active_fields, _ = reconcile_canonical_fields(
            rule_fields=extraction_res.fields,
            model_candidates=[],
            catalog=self.catalog,
            tenant_id=msg.raw.tenant_id,
            raw_text=msg.raw.text,
        )
        actual_extractor_version = VERSION
        diagnostics_dict = {"trigger": "explicit_reprocess" if reprocess else "process", "configured": False, "accepted_model_fields": 0}
        if operation_id:
            diagnostics_dict["operation_id"] = operation_id

        svc = self.proposal_service
        if svc and getattr(svc, "enabled", False):
            diagnostics_dict["configured"] = True
            try:
                import asyncio
                import concurrent.futures

                def _run_async(coro):
                    try:
                        asyncio.get_running_loop()
                    except RuntimeError:
                        return asyncio.run(coro)
                    else:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            return pool.submit(asyncio.run, coro).result()

                proposal_res = _run_async(svc.extract_stored(msg, catalog=self.catalog))
                if getattr(proposal_res, "outcomes", None):
                    diagnostics_dict["model_outcomes"] = proposal_res.outcomes
                if getattr(proposal_res, "routing_reasons", None):
                    diagnostics_dict["routing_reasons"] = proposal_res.routing_reasons
                diagnostics_dict["worker_request_count"] = getattr(proposal_res, "worker_request_count", 0)

                candidates = getattr(proposal_res, "candidates", [])
                if candidates:
                    actual_extractor_version = "p1-ai-pipeline-v2"
                    for c in candidates:
                        for ev in c.evidence:
                            if ev.start < 0 or ev.end > len(msg.raw.text) or ev.start >= ev.end or msg.raw.text[ev.start:ev.end] != ev.quote:
                                raise ValueError(f"Model evidence span [{ev.start}:{ev.end}] invalid")
                    diagnostics_dict["raw_proposals"] = [
                        {"field_name": c.field_name, "value": c.value, "status": c.validation_status}
                        for c in candidates
                    ]
                    reconciled_fields, accepted_count = reconcile_canonical_fields(
                        rule_fields=extraction_res.fields,
                        model_candidates=candidates,
                        catalog=self.catalog,
                        tenant_id=msg.raw.tenant_id,
                        raw_text=msg.raw.text,
                    )
                    active_fields = reconciled_fields
                    diagnostics_dict["accepted_model_fields"] = accepted_count
                elif getattr(proposal_res, "outcomes", None) and any(
                    v in ("unavailable", "timeout", "busy", "endpoint_http_error", "transport_or_schema_error", "invalid_context_or_candidate")
                    for v in proposal_res.outcomes.values()
                ):
                    diagnostics_dict["fallback"] = "rules_only"
            except Exception as model_exc:
                diagnostics_dict["model_error"] = "proposal_processing_failed"
                diagnostics_dict["fallback"] = "rules_only"

        fields = [ExtractedField.model_validate(f) for f in active_fields]
        attempt = ExtractionAttemptRecord(
            attempt_id=str(uuid4()),
            tenant_id=tenant_id,
            message_id=message_id,
            extractor_version=actual_extractor_version,
            input_content_sha256=msg.content_sha256,
            status="PROCESSED",
            fields=fields,
            diagnostic=json.dumps(diagnostics_dict),
            started_at=current_time,
            completed_at=current_time,
        )
        self.attempts.setdefault(key, []).append(attempt)

        # Update message status
        updated = StoredMessage(
            message_id=msg.message_id,
            raw=msg.raw,
            synthetic_provider=msg.synthetic_provider,
            provider=msg.provider,
            source_label=msg.source_label,
            content_sha256=msg.content_sha256,
            processing_status="PROCESSED",
            extractor_version=actual_extractor_version,
            ingested_at=msg.ingested_at,
            updated_at=current_time,
        )
        self.messages[key] = updated
        return ProcessResponse(message=updated, attempt=attempt, reprocessed=reprocess)

    def get_latest_extraction(self, tenant_id: str, message_id: str) -> ExtractionAttemptRecord | None:
        attempts = self.attempts.get((tenant_id, message_id), [])
        return attempts[-1] if attempts else None

    def list_extraction_attempts(self, tenant_id: str, message_id: str) -> list[ExtractionAttemptRecord]:
        return list(self.attempts.get((tenant_id, message_id), []))

    def save_attachment(self, tenant_id: str, attachment: AttachmentRecord, content: bytes) -> AttachmentRecord:
        self.attachments[(tenant_id, attachment.evidence_ref)] = (attachment, content)
        return attachment

    def get_attachment(self, tenant_id: str, evidence_ref: str) -> tuple[AttachmentRecord, bytes] | None:
        return self.attachments.get((tenant_id, evidence_ref))

    def get_association(self, tenant_id: str, message_id: str) -> MessageAssociationRecord | None:
        return self.associations.get((tenant_id, message_id))

    def save_association(self, record: MessageAssociationRecord) -> MessageAssociationRecord:
        self.associations[(record.tenant_id, record.message_id)] = record
        return record

    def get_order_context(self, tenant_id: str, context_id: str) -> OrderContextRecord | None:
        return self.contexts.get((tenant_id, context_id))

    def get_order_context_by_message(self, tenant_id: str, message_id: str) -> OrderContextRecord | None:
        for (t, _), ctx in self.contexts.items():
            if t == tenant_id and message_id in ctx.source_message_ids:
                return ctx
        return None

    def get_order_context_by_order(self, tenant_id: str, order_id: str) -> OrderContextRecord | None:
        for (t, _), ctx in self.contexts.items():
            if t == tenant_id and ctx.order_id == order_id:
                return ctx
        return None

    def save_order_context(self, record: OrderContextRecord, **kwargs) -> OrderContextRecord:
        self.contexts[(record.tenant_id, record.context_id)] = record
        return record

    def apply_context_review(self, tenant_id: str, context_id: str, request: ContextReviewRequest, actor_id: str, actor_role: str) -> OrderContextRecord:
        ctx = self.get_order_context(tenant_id, context_id)
        if ctx is None:
            raise ContextNotFound(f"Context {context_id} not found")
        edits = request.field_edits or {}
        items = [RequestedItem.model_validate(it) for it in edits.get("requested_items", ctx.requested_items)]
        customer_id = edits.get("customer_id", ctx.customer_id) or "cust_bk_01"
        identity_status = edits.get("customer_identity_status", "LINK_VERIFIED")
        delivery_at = edits.get("requested_delivery_at", ctx.requested_delivery_at) or datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
        delivery_qual = edits.get("delivery_qualifier", ctx.delivery_qualifier) or "DEADLINE"

        updated_ctx = OrderContextRecord(
            context_id=ctx.context_id,
            tenant_id=ctx.tenant_id,
            order_id=edits.get("order_id", ctx.order_id),
            customer_id=customer_id,
            customer_identity_status=identity_status,
            status="INFORMATION_READY" if request.action in ("ACCEPT_EXTRACTION", "EDIT_FIELD") else "UNRESOLVED",
            context_version=ctx.context_version + 1,
            requested_items=items if items else [RequestedItem(sku="BURGER", quantity="100", unit="pcs")],
            requested_delivery_at=delivery_at,
            delivery_qualifier=delivery_qual,
            special_instructions=ctx.special_instructions,
            source_message_ids=ctx.source_message_ids,
            field_evidence=ctx.field_evidence,
            missing_fields=[],
            conflicts=[],
            last_reviewed_by=actor_id,
            last_reviewed_role=actor_role,
            last_reviewed_at=datetime.now(timezone.utc),
            core_commitment_id=ctx.core_commitment_id,
            published_to_core_at=ctx.published_to_core_at,
            created_at=ctx.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.contexts[(tenant_id, context_id)] = updated_ctx
        return updated_ctx

    def delete_message(self, tenant_id: str, message_id: str) -> bool:
        msg_key = (tenant_id, message_id)
        if msg_key not in self.messages:
            return False
        stored = self.messages.pop(msg_key)
        fp_key = (tenant_id, stored.raw.channel, stored.raw.provider_message_id)
        self.fingerprints.pop(fp_key, None)
        self.attempts.pop(msg_key, None)
        self.associations.pop(msg_key, None)
        to_del = []
        for c_key, ctx in self.contexts.items():
            if c_key[0] == tenant_id and message_id in (ctx.source_message_ids or []):
                rem = [m for m in ctx.source_message_ids if m != message_id]
                if not rem:
                    to_del.append(c_key)
                else:
                    self.contexts[c_key] = ctx.model_copy(update={"source_message_ids": rem})
        for c_key in to_del:
            self.contexts.pop(c_key, None)
        return True
