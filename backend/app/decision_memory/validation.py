"""Structural checks on a snapshot supplied by an owner-controlled reader."""

from .models import CaseInput, Event, SourceManifest, SourceMode


class HistoryValidationError(ValueError):
    pass


def validate_source(
    manifest: SourceManifest, cases: tuple[CaseInput, ...]
) -> tuple[CaseInput, ...]:
    if (
        not manifest.pagination_complete
        or not manifest.source_population_complete
        or manifest.missing_source_names
        or not manifest.provenance_refs
    ):
        raise HistoryValidationError("SOURCE_INCOMPLETE")
    if not (
        manifest.covered_time_start
        <= manifest.covered_time_end
        <= manifest.source_watermark
        <= manifest.as_of
    ):
        raise HistoryValidationError("INVALID_WATERMARK")
    seen_cases = {}
    logical = set()
    result = []
    for case in cases:
        if case.tenant_id != manifest.tenant_id:
            raise HistoryValidationError("TENANT_MISMATCH")
        if case.memory_case_id in seen_cases:
            if seen_cases[case.memory_case_id] != case:
                raise HistoryValidationError("CONFLICTING_CASE_REPLAY")
            continue
        seen_cases[case.memory_case_id] = case
        events = deduplicate_events(case.events)
        if not events:
            raise HistoryValidationError("MISSING_EVENTS")
        evidence = {e.evidence_id: e for e in case.evidence}
        if len(evidence) != len(case.evidence):
            raise HistoryValidationError("DUPLICATE_EVIDENCE")
        for proof in case.evidence:
            if proof.source_version > manifest.source_version:
                raise HistoryValidationError("SUPERSEDED_SOURCE_VERSION")
            if proof.corrects_id and proof.corrects_id not in evidence:
                raise HistoryValidationError("ORPHAN_EVIDENCE_CORRECTION")
        snapshot = {(e.source_snapshot_id, e.source_snapshot_version) for e in events}
        if snapshot != {(manifest.source_snapshot_id, manifest.source_snapshot_version)}:
            raise HistoryValidationError("SNAPSHOT_MISMATCH")
        ids = {e.event_id for e in events}
        for event in events:
            if event.tenant_id != case.tenant_id or event.commitment_id != case.commitment_id:
                raise HistoryValidationError("EVENT_ASSOCIATION_MISMATCH")
            if event.recovery_case_id != case.recovery_case_id:
                raise HistoryValidationError("RECOVERY_ASSOCIATION_MISMATCH")
            if event.occurred_at > manifest.source_watermark or event.occurred_at > manifest.as_of:
                raise HistoryValidationError("FUTURE_EVENT")
            if not manifest.covered_time_start <= event.occurred_at <= manifest.covered_time_end:
                raise HistoryValidationError("EVENT_OUTSIDE_COVERAGE")
            if event.corrects_id and event.corrects_id not in ids:
                raise HistoryValidationError("ORPHAN_CORRECTION")
            for eid in event.evidence_ids:
                proof = evidence.get(eid)
                if proof is None or proof.subject_id != (event.subject_id or case.commitment_id):
                    raise HistoryValidationError("EVIDENCE_ASSOCIATION_MISMATCH")
                if proof.occurred_at > manifest.source_watermark:
                    raise HistoryValidationError("FUTURE_EVIDENCE")
        if manifest.integration_mode == SourceMode.LIVE and any(
            e.owner == "SYNTHETIC" for e in evidence.values()
        ):
            raise HistoryValidationError("MIXED_SYNTHETIC_LIVE")
        decisions = [e for e in events if e.kind == "DECISION"]
        if len(decisions) == 1:
            if not decisions[0].evidence_ids:
                raise HistoryValidationError("DECISION_PROVENANCE_MISSING")
            identity = (case.tenant_id, decisions[0].event_id)
            if identity in logical:
                raise HistoryValidationError("DUPLICATE_LOGICAL_DECISION")
            logical.add(identity)
        result.append(case.model_copy(update={"events": events}))
    return tuple(result)


def deduplicate_events(events: tuple[Event, ...]) -> tuple[Event, ...]:
    found = {}
    for event in events:
        previous = found.get(event.event_id)
        if previous is not None and previous != event:
            raise HistoryValidationError("CONFLICTING_EVENT_REPLAY")
        found[event.event_id] = event
    return tuple(sorted(found.values(), key=lambda e: (e.occurred_at, e.event_id)))
