"""Build a case from exact stage references in one trusted read snapshot."""

from .models import CaseInput, DecisionMemoryCase, SourceManifest
from .outcome import reconcile_outcome
from .validation import HistoryValidationError, deduplicate_events


def assemble_case(case: CaseInput, manifest: SourceManifest) -> DecisionMemoryCase:
    events = deduplicate_events(case.events)
    by_kind = {
        kind: [e for e in events if e.kind == kind]
        for kind in ("SITUATION", "ALTERNATIVE", "DECISION", "APPROVAL", "EXECUTION", "OUTCOME")
    }
    if len(by_kind["SITUATION"]) != 1 or len(by_kind["DECISION"]) != 1:
        raise HistoryValidationError("DECISION_STAGES_MISSING_OR_AMBIGUOUS")
    situation, decision = by_kind["SITUATION"][0], by_kind["DECISION"][0]
    alternatives = by_kind["ALTERNATIVE"]
    if not decision.actor_ref or not decision.selected_ref or not alternatives:
        raise HistoryValidationError("UNVERIFIED_DECISION")
    refs = tuple(e.ref for e in alternatives)
    if len(set(refs)) != len(refs) or decision.selected_ref not in refs:
        raise HistoryValidationError("INVALID_ALTERNATIVES")
    if situation.occurred_at > decision.occurred_at or any(
        e.occurred_at > decision.occurred_at for e in alternatives
    ):
        raise HistoryValidationError("DECISION_CHRONOLOGY")
    if any(
        e.plan_id != decision.plan_id or e.plan_version != decision.plan_version
        for e in by_kind["APPROVAL"] + by_kind["EXECUTION"]
    ):
        raise HistoryValidationError("PLAN_VERSION_MISMATCH")
    approvals, executions = by_kind["APPROVAL"], by_kind["EXECUTION"]
    if len(approvals) > 1 or len(executions) > 1:
        raise HistoryValidationError("AMBIGUOUS_ACTION_STAGE")
    approval = approvals[0] if approvals else None
    execution = executions[0] if executions else None
    if approval and approval.occurred_at < decision.occurred_at:
        raise HistoryValidationError("APPROVAL_CHRONOLOGY")
    if execution and (not approval or execution.occurred_at < approval.occurred_at):
        raise HistoryValidationError("EXECUTION_CHRONOLOGY")
    outcomes = tuple(by_kind["OUTCOME"])
    if any(e.occurred_at < decision.occurred_at for e in outcomes):
        raise HistoryValidationError("OUTCOME_CHRONOLOGY")
    status, outcome, proof_refs = reconcile_outcome(case.domain, outcomes, case.evidence)
    if outcome and outcome.subject_id != (case.supplier_id or case.commitment_id):
        raise HistoryValidationError("OUTCOME_SUBJECT_MISMATCH")
    return DecisionMemoryCase(
        tenant_id=case.tenant_id,
        memory_case_id=case.memory_case_id,
        case_version=case.case_version,
        decision_domain=case.domain,
        commitment_id=case.commitment_id,
        order_id=case.order_id,
        supplier_id=case.supplier_id,
        recovery_case_id=case.recovery_case_id,
        situation_ref=situation.ref,
        situation_timestamp=situation.occurred_at,
        business_context_ref=case.business_context_ref,
        business_context_version=case.business_context_version,
        context_schema=case.context_schema,
        context=case.context,
        hard_constraints=case.hard_constraints,
        source_snapshot_id=manifest.source_snapshot_id,
        source_snapshot_version=manifest.source_snapshot_version,
        alternatives_refs=refs,
        selected_alternative_ref=decision.selected_ref,
        sme_actor_ref=decision.actor_ref,
        sme_decision_ref=decision.ref,
        decision_reason_ref=decision.evidence_ids[0] if decision.evidence_ids else None,
        decision_timestamp=decision.occurred_at,
        plan_id=decision.plan_id,
        plan_version=decision.plan_version,
        approval_ref=approval.ref if approval else None,
        approval_version=approval.plan_version if approval else None,
        approval_granted=bool(approval and approval.status == "APPROVED"),
        execution_ref=execution.ref if execution else None,
        execution_version=execution.plan_version if execution else None,
        execution_status=execution.status if execution and execution.status else "PENDING",
        outcome_ref=outcome.ref if outcome else None,
        outcome_evidence_refs=proof_refs,
        outcome_timestamp=outcome.occurred_at if outcome else None,
        outcome_verification_status=status,
        integration_mode=manifest.integration_mode,
        evidence_maturity=manifest.evidence_maturity,
        source_watermark=manifest.source_watermark,
        created_at=situation.occurred_at,
        observed_as_of=manifest.as_of,
        provenance_refs=manifest.provenance_refs,
    )
