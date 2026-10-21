from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from .schemas import SourceFeature, TimelineEntry

SENSITIVE_KEYS = {
    "customer_contact",
    "contact_phone",
    "contact_email",
    "phone",
    "email",
    "financial_margin",
    "internal_notes",
    "profit_margin",
    "raw_cost",
    "margin",
    "restricted_notes",
    "approval_notes",
    "cost_breakdown",
}

EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
PHONE_REGEX = re.compile(r"\+?\d[\d\s-]{7,}\d")
FINANCIAL_REGEX = re.compile(
    r"(?i)\b(margin|markup|profit|internal cost|raw cost|discount rate|confidential)\b[^;,\.\n]*"
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def redact_text(text: str | None, role: str) -> str | None:
    if role != "STAFF" or not text:
        return text

    sanitized = text
    if "[CONFIDENTIAL]" in sanitized or "[RESTRICTED]" in sanitized:
        return "[REDACTED: Manager approval notes restricted for Staff role]"

    sanitized = EMAIL_REGEX.sub("[REDACTED_CONTACT]", sanitized)
    sanitized = PHONE_REGEX.sub("[REDACTED_CONTACT]", sanitized)
    sanitized = FINANCIAL_REGEX.sub("[REDACTED_FINANCIAL_NOTE]", sanitized)
    return sanitized


def redact_payload(data: Any, role: str) -> Any:
    if role != "STAFF" or data is None:
        return data

    if isinstance(data, dict):
        redacted_dict: dict[str, Any] = {}
        for key, value in data.items():
            lowered_key = key.lower()
            if lowered_key in SENSITIVE_KEYS or any(
                sub in lowered_key for sub in ["margin", "profit", "contact_phone", "contact_email", "confidential"]
            ):
                redacted_dict[key] = "[REDACTED_FOR_STAFF]"
            elif isinstance(value, (dict, list)):
                redacted_dict[key] = redact_payload(value, role)
            elif isinstance(value, str):
                redacted_dict[key] = redact_text(value, role)
            else:
                redacted_dict[key] = value
        return redacted_dict

    if isinstance(data, list):
        return [redact_payload(item, role) for item in data]

    if isinstance(data, str):
        return redact_text(data, role)

    return data


def _extract_link_id(prefix: str, *sources: Any) -> str | None:
    key_name = prefix.rstrip("_")
    candidate_keys = {f"{key_name}_id", key_name}
    if key_name == "comm":
        candidate_keys.add("communication_id")
    elif key_name in ("asm", "assess"):
        candidate_keys.add("assessment_id")
    elif key_name in ("rec", "plan"):
        candidate_keys.add("recovery_case_id")
        candidate_keys.add("plan_id")
    elif key_name == "ctx":
        candidate_keys.add("context_id")
    elif key_name == "prop":
        candidate_keys.add("proposal_id")

    for source in sources:
        if not source:
            continue
        if isinstance(source, dict):
            for k in candidate_keys:
                v = source.get(k)
                if isinstance(v, str) and v:
                    return v
            for v in source.values():
                if isinstance(v, str) and v.startswith(prefix):
                    return v
        elif isinstance(source, list):
            for item in source:
                if isinstance(item, str) and item.startswith(prefix):
                    return item
        elif isinstance(source, str) and source.startswith(prefix):
            return source
    return None


def _determine_source_feature(
    event_type: str,
    payload: dict[str, Any] | None,
    context_id: str | None,
    assessment_id: str | None,
    recovery_case_id: str | None,
    communication_id: str | None,
) -> SourceFeature:
    lowered = event_type.lower()
    if lowered.startswith("context.") or lowered.startswith("f1.") or (context_id and "context" in lowered):
        return SourceFeature.F1_CONTEXT
    if lowered.startswith("feasibility.") or lowered.startswith("f2.") or (assessment_id and "feasibility" in lowered):
        return SourceFeature.F2_FEASIBILITY
    if lowered.startswith("recovery.") or lowered.startswith("f3.") or (recovery_case_id and "recovery" in lowered):
        return SourceFeature.F3_RECOVERY
    if (
        lowered.startswith("communication.")
        or lowered.startswith("confirmation.")
        or lowered.startswith("f4.")
        or (communication_id and ("comm" in lowered or "confirm" in lowered))
    ):
        return SourceFeature.F4_COMMUNICATION

    # check payload hints
    if payload:
        sf = payload.get("source_feature")
        if sf in SourceFeature.__members__:
            return SourceFeature(sf)

    return SourceFeature.CORE


def build_timeline_entries(
    commitment: CommitmentRecord,
    audit_records: list[AuditEventRecord],
    outbox_records: list[OutboxEventRecord],
    role: str,
) -> list[TimelineEntry]:
    # Index outbox records by audit_id if present
    outbox_by_audit_id: dict[str, OutboxEventRecord] = {}
    remaining_outbox: list[OutboxEventRecord] = []

    for outbox in outbox_records:
        audit_ref = outbox.payload.get("audit_id") if isinstance(outbox.payload, dict) else None
        if audit_ref and isinstance(audit_ref, str):
            outbox_by_audit_id[audit_ref] = outbox
        else:
            remaining_outbox.append(outbox)

    entries: list[TimelineEntry] = []

    for audit in audit_records:
        outbox = outbox_by_audit_id.get(audit.audit_id)
        payload = outbox.payload if outbox and isinstance(outbox.payload, dict) else {}

        # Extract deep link pointers
        evidence_list = audit.evidence_refs or []
        context_id = _extract_link_id("ctx_", payload, evidence_list)
        assessment_id = _extract_link_id("asm_", payload, evidence_list) or _extract_link_id("assess_", payload, evidence_list)
        recovery_case_id = (
            _extract_link_id("rec_", payload, evidence_list)
            or _extract_link_id("plan_", payload, evidence_list)
            or payload.get("recovery_case_id")
            or payload.get("plan_id")
        )
        communication_id = (
            _extract_link_id("comm_", payload, evidence_list)
            or _extract_link_id("msg_", payload, evidence_list)
            or payload.get("communication_id")
        )
        proposal_id = (
            _extract_link_id("prop_", payload, evidence_list)
            or payload.get("proposal_id")
        )

        source_feature = _determine_source_feature(
            audit.event_type,
            payload,
            context_id,
            assessment_id,
            recovery_case_id,
            communication_id,
        )

        version = None
        if outbox and outbox.commitment_version is not None:
            version = outbox.commitment_version
        elif audit.new_state and isinstance(audit.new_state, dict):
            version = audit.new_state.get("commitment_version")

        entry = TimelineEntry(
            entry_id=f"entry_{audit.audit_id}",
            occurred_at=_aware(audit.occurred_at),
            actor_id=audit.actor_id,
            actor_role=audit.actor_role,
            source_feature=source_feature,
            event_type=audit.event_type,
            action=audit.reason or audit.event_type,
            previous_state=redact_payload(audit.previous_state, role),
            new_state=redact_payload(audit.new_state, role),
            commitment_version=version,
            correlation_id=audit.correlation_id,
            causation_id=audit.causation_id or (outbox.causation_id if outbox else None),
            approval_reason=redact_text(audit.reason, role),
            evidence_refs=audit.evidence_refs,
            context_id=context_id,
            assessment_id=assessment_id,
            recovery_case_id=recovery_case_id,
            communication_id=communication_id,
            proposal_id=proposal_id,
        )
        entries.append(entry)

    # Process remaining outbox events (events without audit counterpart)
    for outbox in remaining_outbox:
        payload = outbox.payload if isinstance(outbox.payload, dict) else {}
        evidence_list = payload.get("evidence_refs", []) if isinstance(payload.get("evidence_refs"), list) else []

        context_id = _extract_link_id("ctx_", payload, evidence_list)
        assessment_id = _extract_link_id("asm_", payload, evidence_list) or _extract_link_id("assess_", payload, evidence_list)
        recovery_case_id = (
            _extract_link_id("rec_", payload, evidence_list)
            or _extract_link_id("plan_", payload, evidence_list)
            or payload.get("recovery_case_id")
            or payload.get("plan_id")
        )
        communication_id = (
            _extract_link_id("comm_", payload, evidence_list)
            or _extract_link_id("msg_", payload, evidence_list)
            or payload.get("communication_id")
        )
        proposal_id = (
            _extract_link_id("prop_", payload, evidence_list)
            or payload.get("proposal_id")
        )

        source_feature = _determine_source_feature(
            outbox.event_type,
            payload,
            context_id,
            assessment_id,
            recovery_case_id,
            communication_id,
        )

        actor_id = payload.get("actor_id", "system")
        actor_role = payload.get("actor_role", "SYSTEM")
        reason = payload.get("reason") or payload.get("approval_reason")

        entry = TimelineEntry(
            entry_id=f"entry_{outbox.event_id}",
            occurred_at=_aware(outbox.occurred_at),
            actor_id=str(actor_id),
            actor_role=str(actor_role),
            source_feature=source_feature,
            event_type=outbox.event_type,
            action=str(reason or outbox.event_type),
            previous_state=None,
            new_state=redact_payload(payload, role),
            commitment_version=outbox.commitment_version,
            correlation_id=outbox.correlation_id,
            causation_id=outbox.causation_id,
            approval_reason=redact_text(str(reason), role) if reason else None,
            evidence_refs=evidence_list,
            context_id=context_id,
            assessment_id=assessment_id,
            recovery_case_id=recovery_case_id,
            communication_id=communication_id,
            proposal_id=proposal_id,
        )
        entries.append(entry)

    # Sort chronological
    entries.sort(key=lambda e: e.occurred_at)
    return entries
