"""Trusted, read-only adapter from P1 persistence to the pure order mapper.

This adapter accepts tenant identity only from an injected server trust
boundary. It never accepts commercial values from the caller and therefore
cannot create a READY_FOR_VALIDATION candidate by itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.context.association_schemas import MessageAssociationRecord
from app.context.ingestion_schemas import ExtractionAttemptRecord, StoredMessage
from app.context.order_context_schemas import (
    ContextReviewRecord,
    OrderContextRecord,
    OrderContextVersionRecord,
)
from app.context.repository import (
    MessageRepository,
    OrderContextSourceSnapshot,
    PersistenceUnavailable,
)
from app.orders.context_mapping import AcceptanceCandidate, MappingReadiness, map_order_context


class TrustedTenantScope(Protocol):
    """Host-provided authenticated tenant binding; never a request header DTO."""

    def current_verified_tenant_id(self) -> str | None: ...


class P1SourceReadResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: MappingReadiness
    candidate: AcceptanceCandidate | None = None
    reason_codes: tuple[str, ...] = ()


def _failure(status: MappingReadiness, reason: str) -> P1SourceReadResult:
    return P1SourceReadResult(status=status, reason_codes=(reason,))


def _validate_model(model_type: type[BaseModel], value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    return model_type.model_validate(value)


def _tenant_id(scope: TrustedTenantScope | None) -> str | None:
    if scope is None:
        return None
    try:
        tenant_id = scope.current_verified_tenant_id()
    except Exception:
        return None
    if not isinstance(tenant_id, str) or not tenant_id or tenant_id != tenant_id.strip():
        return None
    return tenant_id


def _source_evidence_is_current(snapshot: OrderContextSourceSnapshot) -> bool:
    """Bind each P1 field reference to a current extraction or human review."""
    context = snapshot.context
    messages = {message.message_id: message for message in snapshot.source_messages}
    attempts_by_message: dict[str, list] = {}
    for attempt in snapshot.extraction_attempts:
        attempts_by_message.setdefault(attempt.message_id, []).append(attempt)
    reviews_by_id = {review.review_id: review for review in snapshot.context_reviews}
    human_item_edit_is_current = _has_current_human_item_edit(snapshot)

    # Validate every loaded source, including messages that do not contribute
    # a field span. A digest proves byte consistency with the stored text, not
    # provider authenticity; provider/mode consistency is checked separately.
    for message in snapshot.source_messages:
        digest = sha256(message.raw.text.encode("utf-8")).hexdigest()
        if message.content_sha256 != digest or not _message_provenance_valid(message):
            return False

    field_names = {
        "sku": {"sku"},
        "quantity": {"quantity"},
        "unit": {"unit"},
        "requested_delivery_at": {"requested_delivery_at"},
        "special_instructions": {"special_instructions"},
        "customer_id": {"customer_id"},
        "order_id": {"order_id"},
        "requested_items": {"requested_items"},
    }
    for context_field, entries in context.field_evidence.items():
        if not isinstance(entries, list) or not entries:
            return False
        accepted_names = field_names.get(context_field)
        if accepted_names is None:
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                return False
            method = entry.get("method")
            if method == "HUMAN":
                review_id = entry.get("evidence_ref")
                review = reviews_by_id.get(review_id) if isinstance(review_id, str) else None
                changes = review.field_changes.get(context_field) if review else None
                if (
                    review is None
                    or review.tenant_id != context.tenant_id
                    or review.context_id != context.context_id
                    or review.context_version_after != context.context_version
                    or review.action not in {"ACCEPT_EXTRACTION", "EDIT_FIELD"}
                    or review.actor_id != entry.get("actor_id")
                    or review.actor_id != context.last_reviewed_by
                    or review.actor_role != context.last_reviewed_role
                    or review.created_at != context.last_reviewed_at
                    or entry.get("context_version") != context.context_version
                    or not isinstance(changes, dict)
                    or changes.get("new") != entry.get("normalized_value")
                    or not _normalized_value_matches_context(
                        context,
                        context_field,
                        entry.get("normalized_value"),
                        human_item_edit_is_current=human_item_edit_is_current,
                    )
                ):
                    return False
                continue

            evidence_id = entry.get("evidence_id")
            message_id = entry.get("message_id")
            message = messages.get(message_id) if isinstance(message_id, str) else None
            if message is None or not isinstance(evidence_id, str):
                return False
            raw = message.raw
            digest = sha256(raw.text.encode("utf-8")).hexdigest()
            if (
                message.raw.tenant_id != context.tenant_id
                or message.content_sha256 != digest
                or not _message_provenance_valid(message)
            ):
                return False
            start, end, quote = entry.get("start"), entry.get("end"), entry.get("quote")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not isinstance(quote, str)
                or start < 0
                or end <= start
                or raw.text[start:end] != quote
            ):
                return False

            matching = []
            for attempt in attempts_by_message.get(message_id, []):
                if (
                    attempt.tenant_id != context.tenant_id
                    or attempt.message_id != message_id
                    or attempt.status != "PROCESSED"
                    or attempt.input_content_sha256 != message.content_sha256
                ):
                    continue
                for extracted in attempt.fields:
                    if extracted.field_name not in accepted_names:
                        continue
                    for evidence in extracted.evidence:
                        if evidence.evidence_id != evidence_id:
                            continue
                        exact_span = (
                            evidence.message_id == message_id
                            and evidence.start == start
                            and evidence.end == end
                            and evidence.quote == quote
                            and evidence.method == method
                            and evidence.method_version == entry.get("method_version")
                            and attempt.extractor_version == evidence.method_version
                        )
                        normalized = extracted.value == entry.get("normalized_value")
                        optional_metadata_matches = (
                            (
                                "validation_status" not in entry
                                or entry["validation_status"] == extracted.validation_status
                            )
                            and (
                                "qualifier" not in entry
                                or entry["qualifier"] == extracted.qualifier
                            )
                            and (
                                "normalization_metadata" not in entry
                                or entry["normalization_metadata"] == extracted.metadata
                            )
                        )
                        if exact_span and normalized and optional_metadata_matches:
                            matching.append(
                                (
                                    extracted.value,
                                    extracted.validation_status,
                                    evidence.model_dump(),
                                )
                            )
            if not matching or len({repr(item) for item in matching}) != 1:
                return False
            if not _normalized_value_matches_context(
                context,
                context_field,
                entry.get("normalized_value"),
                human_item_edit_is_current=human_item_edit_is_current,
            ):
                return False
    return True


def _has_current_human_item_edit(snapshot: OrderContextSourceSnapshot) -> bool:
    context = snapshot.context
    expected = [item.model_dump(mode="json") for item in context.requested_items]
    for entry in context.field_evidence.get("requested_items", []):
        if not isinstance(entry, dict) or entry.get("method") != "HUMAN":
            continue
        review = next(
            (row for row in snapshot.context_reviews if row.review_id == entry.get("evidence_ref")),
            None,
        )
        change = review.field_changes.get("requested_items") if review else None
        if (
            review is not None
            and review.tenant_id == context.tenant_id
            and review.context_id == context.context_id
            and review.context_version_after == context.context_version
            and review.action in {"ACCEPT_EXTRACTION", "EDIT_FIELD"}
            and review.actor_id == context.last_reviewed_by == entry.get("actor_id")
            and review.actor_role == context.last_reviewed_role
            and review.created_at == context.last_reviewed_at
            and entry.get("context_version") == context.context_version
            and isinstance(change, dict)
            and change.get("new") == expected == entry.get("normalized_value")
        ):
            return True
    return False


def _normalized_value_matches_context(
    context,
    field_name: str,
    value,
    *,
    human_item_edit_is_current: bool = False,
) -> bool:
    if field_name == "sku":
        return human_item_edit_is_current or any(
            item.sku == value for item in context.requested_items
        )
    if field_name == "quantity":
        return human_item_edit_is_current or any(
            item.quantity == value for item in context.requested_items
        )
    if field_name == "unit":
        return human_item_edit_is_current or any(
            item.unit == value for item in context.requested_items
        )
    if field_name == "requested_delivery_at":
        if context.requested_delivery_at is None or not isinstance(value, str):
            return False
        try:
            evidence_time = datetime.fromisoformat(value)
        except ValueError:
            return False
        context_time = context.requested_delivery_at
        if (
            evidence_time.tzinfo is None
            or evidence_time.utcoffset() is None
            or context_time.tzinfo is None
            or context_time.utcoffset() is None
        ):
            return False
        return evidence_time.astimezone(timezone.utc) == context_time.astimezone(timezone.utc)
    if field_name == "special_instructions":
        return context.special_instructions == value
    if field_name == "customer_id":
        return context.customer_id == value
    if field_name == "order_id":
        return context.order_id == value
    if field_name == "requested_items":
        return value == [item.model_dump(mode="json") for item in context.requested_items]
    return False


def _message_provenance_valid(message) -> bool:
    synthetic_providers = {
        "WHATSAPP": "SYNTHETIC_WHATSAPP",
        "EMAIL": "SYNTHETIC_EMAIL",
        "TELEGRAM": "SYNTHETIC_TELEGRAM",
        "UNKNOWN": "SYNTHETIC_UNKNOWN",
    }
    real_providers = {
        "WHATSAPP": "WHATSAPP_CLOUD_API",
        "EMAIL": "GMAIL_API",
        "TELEGRAM": "TELEGRAM_BOT_API",
        "UNKNOWN": "REAL",
    }
    if message.raw.adapter_mode == "REAL":
        return message.synthetic_provider is None and message.provider == real_providers.get(
            message.raw.channel
        )
    if message.raw.adapter_mode == "SYNTHETIC":
        return (
            message.provider == "SYNTHETIC"
            and message.synthetic_provider == synthetic_providers.get(message.raw.channel)
        )
    return False


class P1OrderContextSourceReader:
    """Load and validate authoritative P1 source before invoking the mapper."""

    def __init__(
        self,
        repository: MessageRepository,
        *,
        tenant_scope: TrustedTenantScope | None,
    ) -> None:
        self._repository = repository
        self._tenant_scope = tenant_scope

    def read_candidate(
        self, context_id: str, *, expected_context_version: int
    ) -> P1SourceReadResult:
        tenant_id = _tenant_id(self._tenant_scope)
        if tenant_id is None:
            return _failure("IDENTITY_UNVERIFIED", "TRUSTED_TENANT_SCOPE_UNAVAILABLE")
        if (
            not isinstance(context_id, str)
            or not context_id
            or context_id != context_id.strip()
            or isinstance(expected_context_version, bool)
            or not isinstance(expected_context_version, int)
            or expected_context_version < 1
        ):
            return _failure("REVIEW_REQUIRED", "INVALID_SOURCE_READ_REFERENCE")

        try:
            snapshot = self._repository.read_order_context_source(tenant_id, context_id)
        except PersistenceUnavailable:
            return _failure("REVIEW_REQUIRED", "P1_SOURCE_UNAVAILABLE")
        except Exception:
            # Repository failures are intentionally sanitized at this boundary.
            return _failure("REVIEW_REQUIRED", "P1_SOURCE_UNAVAILABLE")

        if snapshot is None:
            return _failure("INCOMPLETE", "P1_CONTEXT_NOT_FOUND")
        if not isinstance(snapshot, OrderContextSourceSnapshot):
            # Structural test doubles/alternate repositories are permitted, but
            # only if they provide the complete typed snapshot shape.
            try:
                snapshot = OrderContextSourceSnapshot(
                    context=snapshot.context,
                    context_versions=tuple(snapshot.context_versions),
                    context_reviews=tuple(snapshot.context_reviews),
                    source_messages=tuple(snapshot.source_messages),
                    associations=tuple(snapshot.associations),
                    extraction_attempts=tuple(snapshot.extraction_attempts),
                )
            except Exception:
                return _failure("REVIEW_REQUIRED", "P1_SNAPSHOT_INVALID")
        try:
            snapshot = OrderContextSourceSnapshot(
                context=_validate_model(OrderContextRecord, snapshot.context),
                context_versions=tuple(
                    _validate_model(OrderContextVersionRecord, row)
                    for row in snapshot.context_versions
                ),
                context_reviews=tuple(
                    _validate_model(ContextReviewRecord, row) for row in snapshot.context_reviews
                ),
                source_messages=tuple(
                    _validate_model(StoredMessage, row) for row in snapshot.source_messages
                ),
                associations=tuple(
                    _validate_model(MessageAssociationRecord, row) for row in snapshot.associations
                ),
                extraction_attempts=tuple(
                    _validate_model(ExtractionAttemptRecord, row)
                    for row in snapshot.extraction_attempts
                ),
            )
        except Exception:
            return _failure("REVIEW_REQUIRED", "P1_SNAPSHOT_INVALID")

        context = snapshot.context
        if context.tenant_id != tenant_id or context.context_id != context_id:
            return _failure("REVIEW_REQUIRED", "P1_SNAPSHOT_BINDING_UNVERIFIED")

        records = snapshot.context_versions
        if any(row.tenant_id != tenant_id or row.context_id != context_id for row in records):
            return _failure("REVIEW_REQUIRED", "P1_VERSION_BINDING_UNVERIFIED")
        matching_versions = [
            row for row in records if row.context_version == context.context_version
        ]
        if (
            context.context_version != expected_context_version
            or not records
            or len(matching_versions) != 1
            or max(row.context_version for row in records) != context.context_version
        ):
            return _failure("STALE_SOURCE", "EXPECTED_CONTEXT_VERSION_STALE")
        try:
            version_snapshot = OrderContextRecord.model_validate(matching_versions[0].snapshot)
        except Exception:
            return _failure("STALE_SOURCE", "CURRENT_CONTEXT_SNAPSHOT_INVALID")
        if version_snapshot.model_dump(mode="json") != context.model_dump(mode="json"):
            return _failure("STALE_SOURCE", "CURRENT_CONTEXT_SNAPSHOT_MISMATCH")
        if any(
            row.tenant_id != tenant_id or row.context_id != context_id
            for row in snapshot.context_reviews
        ):
            return _failure("REVIEW_REQUIRED", "P1_REVIEW_BINDING_UNVERIFIED")
        if any(
            message.raw.tenant_id != tenant_id
            or message.message_id not in context.source_message_ids
            for message in snapshot.source_messages
        ):
            return _failure("REVIEW_REQUIRED", "P1_MESSAGE_BINDING_UNVERIFIED")
        if any(
            row.tenant_id != tenant_id or row.message_id not in context.source_message_ids
            for row in snapshot.associations
        ):
            return _failure("REVIEW_REQUIRED", "P1_ASSOCIATION_BINDING_UNVERIFIED")
        if any(
            (row.verified_customer is not None and row.verified_customer.tenant_id != tenant_id)
            or (row.verified_order is not None and row.verified_order.tenant_id != tenant_id)
            for row in snapshot.associations
        ):
            return _failure("REVIEW_REQUIRED", "P1_ASSOCIATION_BINDING_UNVERIFIED")
        if any(
            row.tenant_id != tenant_id or row.message_id not in context.source_message_ids
            for row in snapshot.extraction_attempts
        ):
            return _failure("REVIEW_REQUIRED", "P1_EXTRACTION_BINDING_UNVERIFIED")

        # Missing original message rows have an explicit incomplete outcome in
        # the mapper. Do not claim evidence currentness when records are absent.
        if set(message.message_id for message in snapshot.source_messages) == set(
            context.source_message_ids
        ):
            if not _source_evidence_is_current(snapshot):
                return _failure("REVIEW_REQUIRED", "SOURCE_EVIDENCE_PROVENANCE_UNVERIFIED")

        candidate = map_order_context(
            context,
            current_version=matching_versions[0],
            source_messages=snapshot.source_messages,
            associations=snapshot.associations,
            reviews=snapshot.context_reviews,
            # No approved commercial/disclosure reader exists in this slice.
            commercial_terms=None,
            existing_core_terms=None,
        )
        return P1SourceReadResult(
            status=candidate.readiness_status,
            candidate=candidate,
            reason_codes=candidate.validation_reason_codes,
        )
