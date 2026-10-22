"""Optional P1 observation service; never publishes authoritative terms.

Operational repositories may invoke this service when explicitly configured.
Schema/source validity does not prove correct semantics or GPU execution.
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
    telemetry: dict[str, dict] = {}
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
        # Metadata/identity requirements cannot be solved by guessing with a
        # model. Missing units alone also do not authorize unit invention.
        needs_interpretation = any(f.field_name in {"sku", "quantity"}
            and f.validation_status != "VALID" for f in rules.fields)
        for engine in self.stages:
            if not needs_interpretation:
                result.outcomes[engine] = "not_needed"
                continue
            # One persisted message/tenant only; no identities, attachments,
            # raw envelope, customer data, headers or credentials leave P1.
            try:
                request = InferenceInput(engine=engine, messages=[SourceText(id="m1", text=message.raw.text)])
                result.telemetry[engine] = {"attempted": True, "succeeded": False}
                answer = validate_evidence(await self.endpoint.infer(request), request)
                result.telemetry[engine].update(succeeded=True, model=answer.model_id, revision=answer.revision,
                    device=answer.gpu_name, dtype=answer.dtype, peak_gpu_bytes=answer.peak_gpu_bytes,
                    inference_seconds=answer.inference_seconds, load_seconds=answer.load_seconds)
                for observation in answer.fields:
                    candidate = self._candidate(observation, message, catalog, answer.model_id, answer.revision)
                    candidate.metadata["runtime_versions_reported"] = __import__('json').dumps(answer.runtime_versions, sort_keys=True)
                    protected = [f for f in rules.fields if f.validation_status == "VALID"] + reviewed
                    same = [f for f in protected if f.field_name == candidate.field_name]
                    if candidate.metadata.get("domain_supported") != "true":
                        candidate.metadata["disposition"] = "rejected"
                    elif any(f.value == candidate.value for f in same):
                        candidate.metadata["disposition"] = "duplicate"
                    elif same:
                        candidate.validation_status = "CONFLICT"
                        result.conflicts.append(candidate.evidence[0].evidence_id)
                        candidate.metadata["disposition"] = "conflict"
                    else:
                        candidate.metadata["disposition"] = "proposal"
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
        supported = False
        subspan = None
        if observation.field == "product":
            matches = []
            for p in catalog:
                if p.tenant_id != message.raw.tenant_id:
                    continue
                for alias in p.aliases:
                    m = re.fullmatch(r"(?:[0-9]+(?:\s+(?:pcs|pieces|个))?\s+)?(?P<alias>" + re.escape(alias) + r")", quote, re.IGNORECASE)
                    if m:
                        matches.append((p, m.span("alias")))
            if len({(p.sku, p.unit) for p, _ in matches}) == 1:
                value = matches[0][0].sku
                subspan = matches[0][1]
                supported = True
            else:
                reason = "Unknown or ambiguous SKU alias; model cannot establish catalog membership"
        elif observation.field == "unit":
            value = UNIT_NORMALIZATION.get(quote.lower(), quote)
            if quote.lower() not in UNIT_NORMALIZATION:
                status, reason = "INVALID", "Unsupported unit token; no automatic conversion"
            else:
                sku_fields = [f.value for f in extract_explicit_fields(message, catalog=catalog).fields
                              if f.field_name == "sku" and f.validation_status == "VALID"]
                supported = len(set(sku_fields)) == 1 and any(p.sku == sku_fields[0] and p.unit == value
                    and p.tenant_id == message.raw.tenant_id for p in catalog)
                if not supported:
                    status, reason = "INVALID", "Unit/SKU compatibility is unproven"
        elif observation.field == "quantity":
            # Delegate meaning/association to L0, then accept only its exact
            # quantity subspan inside this observation. Never pick first digit.
            quantities = [f for f in extract_explicit_fields(message, catalog=catalog).fields
                if f.field_name == "quantity" and f.validation_status == "VALID" and f.evidence
                and observation.start <= f.evidence[0].start < f.evidence[0].end <= observation.end]
            if len(quantities) == 1:
                q = quantities[0]
                value = q.value
                subspan = (q.evidence[0].start - observation.start, q.evidence[0].end - observation.start)
                supported = True
            elif not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", quote) or Decimal(quote) <= 0:
                status, reason = "INVALID", "Quantity must be an explicit positive ASCII decimal"
            else:
                reason = "Literal number only; item association is unproven"
        elif observation.field == "delivery":
            reason = "Raw delivery expression only; model cannot normalize or override date safety rules"
        evidence = FieldEvidence(evidence_id=f"model:{message.message_id}:{observation.start}:{observation.end}:{observation.field}",
                                 message_id=message.message_id, quote=quote, start=observation.start, end=observation.end,
                                 method="MODEL", method_version=f"{model_id}@{revision}")
        # Do not mark numeric/unit/model associations VALID just because they
        # pass schema or quote checks. TASK 2B validators remain authoritative.
        evidence_list = [evidence]
        if subspan and subspan != (0, len(quote)):
            start, end = observation.start + subspan[0], observation.start + subspan[1]
            evidence_list.append(FieldEvidence(evidence_id=f"normalized:{message.message_id}:{start}:{end}",
                message_id=message.message_id, quote=message.raw.text[start:end], start=start, end=end,
                method="MODEL", method_version=f"{model_id}@{revision}"))
        return ExtractedField(field_name=name, value=value, validation_status=status, evidence=evidence_list,
                              metadata={"reason": reason, "group_id": observation.group_id or "", "model_id": model_id,
                                        "model_revision": revision, "provisional": "true",
                                        "domain_supported": str(supported).lower(),
                                        "normalization": "catalog_and_l0_subspan_v1"})
