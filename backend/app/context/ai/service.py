"""Prepared P1 service seam. Model stages remain disabled until evaluation.

This module does not publish BusinessContext, mutate persisted messages or bind
an operational route. No successful GPU integration is implied by its existence.
"""
from typing import Literal, Sequence
from decimal import Decimal
import re

from ..deterministic_extraction import ProductAlias, UNIT_NORMALIZATION, extract_explicit_fields
from ..extraction import ExtractionResult
from ..ingestion_schemas import StoredMessage
from ..schemas import ExtractedField, FieldEvidence, P1Model
from .protocol import InferenceFailure, InferenceInput, Observation, SourceText, validate_evidence


class ProposalResult(P1Model):
    rules: ExtractionResult
    reviewed_fields: list[ExtractedField]
    candidates: list[ExtractedField]
    outcomes: dict[str, str]
    conflicts: list[str]
    manual_review_required: Literal[True] = True


class ModelProposalService:
    def __init__(self, endpoint=None, *, enabled=False, stages=("gliner", "qwen")):
        if any(stage not in {"gliner", "qwen"} for stage in stages):
            raise ValueError("Unsupported model stage")
        self.endpoint = endpoint
        self.enabled = enabled
        self.stages = stages

    async def extract_stored(self, message: StoredMessage, *, catalog: Sequence[ProductAlias],
                             reviewed_fields: Sequence[ExtractedField] = ()) -> ProposalResult:
        rules = extract_explicit_fields(message, catalog=catalog)
        reviewed = [f.model_copy(deep=True) for f in reviewed_fields]
        for field in reviewed:
            if not field.evidence or not all(e.method == "HUMAN" and e.message_id == message.message_id
                    and message.raw.text[e.start:e.end] == e.quote for e in field.evidence):
                raise ValueError("Reviewed fields require current-message HUMAN provenance")
        result = ProposalResult(rules=rules, reviewed_fields=reviewed, candidates=[], outcomes={}, conflicts=[])
        if not self.enabled or self.endpoint is None:
            result.outcomes["models"] = "disabled"
            return result
        needs_interpretation = any(
            f.validation_status in {"UNRESOLVED", "CONFLICT", "INVALID"} and f.field_name != "order_id"
            for f in rules.fields
        ) or any(
            f.field_name in {"sku", "quantity"} and f.validation_status == "MISSING"
            for f in rules.fields
        )
        for engine in self.stages:
            if engine == "qwen" and not needs_interpretation:
                result.outcomes[engine] = "not_needed"
                continue
            # One persisted message/tenant only; no identities, attachments,
            # raw envelope, customer data, headers or credentials leave P1.
            try:
                request = InferenceInput(engine=engine, messages=[SourceText(id="m1", text=message.raw.text)])
                answer = validate_evidence(await self.endpoint.infer(request), request)
                for observation in answer.fields:
                    candidate = self._candidate(observation, message, catalog, answer.model_id, answer.revision)
                    protected = [f for f in rules.fields if f.validation_status == "VALID"] + reviewed
                    if any(f.field_name == candidate.field_name and f.value != candidate.value for f in protected):
                        candidate.validation_status = "CONFLICT"
                        result.conflicts.append(candidate.evidence[0].evidence_id)
                    result.candidates.append(candidate)
                result.outcomes[engine] = "proposals_only"
            except InferenceFailure as error:
                result.outcomes[engine] = str(error)
            except Exception:
                result.outcomes[engine] = "invalid_context_or_candidate"
        return result

    @staticmethod
    def _candidate(observation: Observation, message, catalog, model_id, revision):
        name = {"product": "sku", "quantity": "quantity", "unit": "unit", "delivery": "requested_delivery_at",
                "order_reference": "order_id"}[observation.field]
        quote = observation.quote
        value = quote
        reason = "Model proposal only; independent semantic/domain review required"
        status = "UNRESOLVED"
        if observation.field == "product":
            matches = {p.sku for p in catalog if p.tenant_id == message.raw.tenant_id
                       and quote.casefold() in {a.casefold() for a in p.aliases}}
            if len(matches) == 1:
                value = next(iter(matches))
            else:
                reason = "Unknown or ambiguous SKU alias; model cannot establish catalog membership"
        elif observation.field == "unit":
            value = UNIT_NORMALIZATION.get(quote.lower(), quote)
            if quote.lower() not in UNIT_NORMALIZATION:
                status, reason = "INVALID", "Unsupported unit token; no automatic conversion"
        elif observation.field == "quantity":
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", quote) or Decimal(quote) <= 0:
                status, reason = "INVALID", "Quantity must be an explicit positive ASCII decimal"
        elif observation.field == "delivery":
            reason = "Raw delivery expression only; model cannot normalize or override date safety rules"
        evidence = FieldEvidence(evidence_id=f"model:{message.message_id}:{observation.start}:{observation.end}:{observation.field}",
                                 message_id=message.message_id, quote=quote, start=observation.start, end=observation.end,
                                 method="MODEL", method_version=f"{model_id}@{revision}")
        # Do not mark numeric/unit/model associations VALID just because they
        # pass schema or quote checks. TASK 2B validators remain authoritative.
        return ExtractedField(field_name=name, value=value, validation_status=status, evidence=[evidence],
                              metadata={"reason": reason, "group_id": observation.group_id or "", "model_id": model_id,
                                        "model_revision": revision, "provisional": "true"})
