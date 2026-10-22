"""Optional P1 observation service; never publishes authoritative terms.

Operational repositories may invoke this service when explicitly configured.
Schema/source validity does not prove correct semantics or GPU execution.
"""
import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import Literal, Sequence
from decimal import Decimal
import re

from ..deterministic_extraction import (
    ProductAlias,
    UNIT_NORMALIZATION,
    extract_explicit_fields,
    ORDER_RE,
    DEADLINE_PRE_RE,
    DEADLINE_POST_RE,
)
from ..extraction import ExtractionResult
from ..ingestion_schemas import StoredMessage
from ..schemas import ExtractedField, FieldEvidence, P1Model
from ..request_intent import request_intent
from .protocol import InferenceFailure, InferenceInput, InferenceOutput, MODEL_CONFIG, Observation, SourceText, validate_evidence

NON_ORDER_PATTERNS = re.compile(
    r"\b(do you do delivery|do you deliver|available tak|what is the price|how much|can you send(?: the)? menu|"
    r"is there delivery|any delivery|thanks for yesterday|quality was great|received yesterday|"
    r"might need|planning to|will confirm later|tentatively|"
    r"ada penghantaran.*tak|ada delivery.*tak|berapa harga|boleh tanya|terima kasih.*semalam|dah sampai semalam|"
    r"mungkin nak|akan confirm nanti|belum pasti)\b|"
    r"(?:请问.*多少|支持.*吗|有没有送|如何收费|起订量|送来的.*很新鲜|谢谢.*评价很好|昨天送的|可能要订|过两天再跟你确认|还未确定)",
    re.IGNORECASE,
)

PAST_DATE_PATTERNS = re.compile(
    r"\b(yesterday|semalam|tadi|last week|sebelum ini)\b|(?:昨天|刚才|上次)",
    re.IGNORECASE,
)

DATE_TIME_PATTERNS = re.compile(
    r"\b(tomorrow|yesterday|today|tonight|morning|afternoon|evening|night|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"esok|lusa|pagi|petang|malam|pukul|hari|sabtu|ahad|isnin|selasa|rabu|khamis|jumaat|"
    r"noon|am|pm|\d{1,2}:\d{2})\b|(?:\d+月\d+日|明天|后天|大后天|今天|周[一二三四五六日天]|星期[一二三四五六日天]|\d+点)",
    re.IGNORECASE,
)

CONFLICT_PATTERNS = re.compile(
    r"\b(or|atau|或者|not|bukan|jangan|别|不要|sorry|maaf|make that|tukar|instead)\b",
    re.IGNORECASE,
)


class ProposalResult(P1Model):
    rules: ExtractionResult
    reviewed_fields: list[ExtractedField]
    candidates: list[ExtractedField]
    outcomes: dict[str, str]
    conflicts: list[str]
    telemetry: dict[str, dict] = {}
    manual_review_required: Literal[True] = True
    routing_reasons: dict[str, str] = {}
    worker_request_count: int = 0


class ModelProposalService:
    def __init__(self, endpoint=None, *, enabled=False, stages=("gliner",)):
        if any(stage not in {"gliner", "qwen"} for stage in stages):
            raise ValueError("Unsupported model stage")
        if len(set(stages)) != len(stages) or ("gliner" in stages and "qwen" in stages and stages.index("qwen") < stages.index("gliner")):
            raise ValueError("Stages must be unique and run L1 before L2")
        self.endpoint = endpoint
        self.enabled = enabled
        self.stages = stages
        self._inference_cache = OrderedDict()
        self._inflight = {}
        self.cache_ttl_seconds = 60.0
        self.cache_max_entries = 128
        self.worker_request_count: int = 0
        self.request_timeout_seconds = min(180.0, getattr(getattr(endpoint, 'config', None), 'timeout_seconds', 125.0) + 3.0)

    async def extract_stored(self, message: StoredMessage, *, catalog: Sequence[ProductAlias],
                             reviewed_fields: Sequence[ExtractedField] = ()) -> ProposalResult:
        rules = extract_explicit_fields(message, catalog=catalog)
        reviewed = [f.model_copy(deep=True) for f in reviewed_fields]
        reviewed_names = {f.field_name for f in reviewed}
        for field in reviewed:
            if not field.evidence or not all(e.method == "HUMAN" and e.message_id == message.message_id
                    and message.raw.text[e.start:e.end] == e.quote for e in field.evidence):
                raise ValueError("Reviewed fields require current-message HUMAN provenance")
        result = ProposalResult(
            rules=rules,
            reviewed_fields=reviewed,
            candidates=[],
            outcomes={},
            conflicts=[],
            routing_reasons={},
            worker_request_count=0,
        )
        if not self.enabled or self.endpoint is None:
            result.outcomes["models"] = "disabled"
            result.routing_reasons["models"] = "Model extraction disabled or endpoint unconfigured"
            return result

        rule_sku_valid = any(f.field_name == "sku" and f.validation_status == "VALID" for f in rules.fields)
        rule_qty_valid = any(f.field_name == "quantity" and f.validation_status == "VALID" for f in rules.fields)
        rule_del_valid = any(f.field_name == "requested_delivery_at" and f.validation_status == "VALID" for f in rules.fields)
        has_date_keywords = bool(DATE_TIME_PATTERNS.search(message.raw.text)) or any(
            f.field_name == 'requested_delivery_at' and f.evidence for f in rules.fields)
        unresolved_items = any(f.field_name in {'sku', 'quantity', 'unit'}
            and f.validation_status in {'UNRESOLVED', 'CONFLICT', 'INVALID'} and f.evidence for f in rules.fields)
        is_non_order = request_intent(message.raw.text) != 'UNCLASSIFIED' or bool(NON_ORDER_PATTERNS.search(message.raw.text))
        missing_tz_only = (rule_sku_valid and rule_qty_valid and not unresolved_items and not message.raw.business_timezone)

        has_only_unsupported_unit = (
            rule_sku_valid and (not has_date_keywords or rule_del_valid)
            and any(f.field_name == "unit" and f.metadata.get("raw_unit") and f.metadata.get("domain_supported") == "false" for f in rules.fields)
            and any(f.field_name == "quantity" and f.value is not None and f.value.isdigit() for f in rules.fields)
            and not any(f.field_name == "quantity" and f.value is None for f in rules.fields)
            and not any(f.field_name == "sku" and f.validation_status != "VALID" for f in rules.fields)
            and not any(f.field_name == "requested_delivery_at" and f.metadata.get("rescheduling") == "true" for f in rules.fields)
        )

        # Evaluate deterministic sufficiency before calling any model
        if missing_tz_only:
            needs_l1 = False
            l0_reason = "Metadata/timezone uncertainty cannot be resolved by model inference"
        elif is_non_order:
            needs_l1 = False
            l0_reason = "Non-order inquiry or feedback detected; no candidate generation required"
        elif has_only_unsupported_unit:
            needs_l1 = False
            l0_reason = "Missing catalog conversion data or incompatible unit requires authorized review; not escalated to GPU"
        elif rule_sku_valid and rule_qty_valid and not unresolved_items and (not has_date_keywords or rule_del_valid):
            needs_l1 = False
            l0_reason = "L0 deterministic rules safely resolved all relevant order terms"
        else:
            needs_l1 = True
            l0_reason = "L0 deterministic rules could not resolve all required terms (missing SKU, quantity, or delivery)"

        for engine in self.stages:
            if engine == "gliner":
                if not needs_l1:
                    result.outcomes[engine] = "not_needed"
                    result.routing_reasons[engine] = l0_reason
                    continue

                result.routing_reasons[engine] = l0_reason
                try:
                    answer = await self._infer_observations(engine, message, result)

                    observations_to_process = list(answer.fields)
                    # Check for adjacent/separated date and time observations to combine
                    del_obs = [o for o in answer.fields if o.field == "delivery"]
                    if len(del_obs) >= 2:
                        del_obs_sorted = sorted(del_obs, key=lambda o: o.start)
                        first, last = del_obs_sorted[0], del_obs_sorted[-1]
                        span_text = message.raw.text[first.start:last.end]
                        if (last.end - first.start) <= 60 and not PAST_DATE_PATTERNS.search(span_text):
                            observations_to_process.append(
                                Observation(
                                    field="delivery",
                                    message_id="m1",
                                    quote=span_text,
                                    start=first.start,
                                    end=last.end,
                                )
                            )

                    has_existing_quantity = any(
                        f.field_name == "quantity" and f.validation_status == "VALID"
                        for f in rules.fields
                    ) or any(f.field_name == "quantity" for f in reviewed)

                    for observation in observations_to_process:
                        candidate = self._candidate(
                            observation, message, catalog, answer.model_id, answer.revision, has_existing_quantity
                        )
                        candidate.metadata["runtime_versions_reported"] = __import__('json').dumps(
                            answer.runtime_versions, sort_keys=True
                        )
                        protected = [f for f in rules.fields if f.validation_status == "VALID" and f.field_name not in reviewed_names] + reviewed
                        cand_gid = candidate.metadata.get("group_id") or ""
                        if cand_gid:
                            same = [
                                f for f in protected
                                if f.field_name == candidate.field_name
                                and (f.metadata.get("group_id") == cand_gid or (not f.metadata.get("group_id") and cand_gid in ("g1", "default", "")))
                            ]
                        else:
                            same = [f for f in protected if f.field_name == candidate.field_name]

                        if candidate.metadata.get("domain_supported") != "true":
                            candidate.metadata["disposition"] = "rejected"
                        elif any(f.value == candidate.value for f in same):
                            candidate.metadata["disposition"] = "duplicate"
                        elif self._same_literal_delivery(candidate, rules):
                            candidate.metadata["disposition"] = "duplicate"
                        elif same:
                            candidate.validation_status = "CONFLICT"
                            result.conflicts.append(candidate.evidence[0].evidence_id)
                            candidate.metadata["disposition"] = "conflict"
                        else:
                            candidate.metadata["disposition"] = "proposal"
                        result.candidates.append(candidate)

                        # Extract unit if embedded in quantity quote (e.g. 15个 -> unit 个 -> pcs)
                        if observation.field == "quantity" and candidate.metadata.get("domain_supported") == "true":
                            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", observation.quote)
                            if m:
                                unit_tail = observation.quote[m.end(1):].strip()
                                if unit_tail in ("个", "pcs", "pieces", "biji", "bungkus"):
                                    unit_norm = UNIT_NORMALIZATION.get(unit_tail.lower(), "pcs")
                                    u_start = observation.start + m.end(1)
                                    u_end = observation.end
                                    u_cand = ExtractedField(
                                        field_name="unit",
                                        value=unit_norm,
                                        validation_status="UNRESOLVED",
                                        evidence=[
                                            FieldEvidence(
                                                evidence_id=f"model:{message.message_id}:{u_start}:{u_end}:unit",
                                                message_id=message.message_id,
                                                quote=message.raw.text[u_start:u_end],
                                                start=u_start,
                                                end=u_end,
                                                method="MODEL",
                                                method_version=f"{answer.model_id}@{answer.revision}",
                                            )
                                        ],
                                        metadata={
                                            "domain_supported": "true",
                                            "disposition": "proposal",
                                            "provisional": "true",
                                            "reason": "Derived from quantity observation unit suffix",
                                        },
                                    )
                                    result.candidates.append(u_cand)

                    result.outcomes[engine] = "proposals_only"

                except InferenceFailure as error:
                    result.outcomes[engine] = str(error)
                    result.routing_reasons[engine] = f"Worker inference failure: {error}"
                except Exception:
                    result.outcomes[engine] = "invalid_context_or_candidate"
                    result.routing_reasons[engine] = "Worker exception or validation error"

            elif engine == "qwen":
                if not needs_l1:
                    result.outcomes[engine] = "not_needed"
                    result.routing_reasons[engine] = l0_reason
                    continue

                reason = self._l2_escalation_reason(message, result)
                if reason is None:
                    result.outcomes[engine] = "l1_sufficient"
                    result.routing_reasons[engine] = "No remaining supported interpretation need; retain missing metadata and human review"
                    continue

                # Qwen is invoked only when meaningful ambiguity remains
                result.routing_reasons[engine] = reason
                try:
                    answer = await self._infer_observations(engine, message, result)

                    has_existing_quantity = any(
                        f.field_name == "quantity" and f.validation_status == "VALID"
                        for f in rules.fields
                    ) or any(f.field_name == "quantity" for f in reviewed)

                    for observation in answer.fields:
                        candidate = self._candidate(
                            observation, message, catalog, answer.model_id, answer.revision, has_existing_quantity
                        )
                        candidate.metadata["runtime_versions_reported"] = __import__('json').dumps(
                            answer.runtime_versions, sort_keys=True
                        )
                        protected = [f for f in rules.fields if f.validation_status == "VALID" and f.field_name not in reviewed_names] + reviewed
                        cand_gid = candidate.metadata.get("group_id") or ""
                        if cand_gid:
                            same = [
                                f for f in protected
                                if f.field_name == candidate.field_name
                                and (f.metadata.get("group_id") == cand_gid or (not f.metadata.get("group_id") and cand_gid in ("g1", "default", "")))
                            ]
                        else:
                            same = [f for f in protected if f.field_name == candidate.field_name]
                        if candidate.metadata.get("domain_supported") != "true":
                            candidate.metadata["disposition"] = "rejected"
                        elif any(f.value == candidate.value for f in same):
                            candidate.metadata["disposition"] = "duplicate"
                        elif self._same_literal_delivery(candidate, rules):
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
                    result.routing_reasons[engine] = f"Worker inference failure: {error}"
                except Exception:
                    result.outcomes[engine] = "invalid_context_or_candidate"
                    result.routing_reasons[engine] = "Worker exception or validation error"

        return result

    @staticmethod
    def _same_literal_delivery(candidate, rules):
        return candidate.field_name == 'requested_delivery_at' and bool(candidate.evidence) and all(
            any(f.field_name == 'requested_delivery_at' and
                any(ev.message_id == source.message_id and ev.start <= source.start < source.end <= ev.end
                    for ev in f.evidence) for f in rules.fields)
            for source in candidate.evidence)

    @staticmethod
    def _l2_escalation_reason(message, result):
        """Interpret literal ambiguity, never fill absent facts or trusted metadata."""
        reviewed_names = {f.field_name for f in result.reviewed_fields}
        protected = [f for f in result.rules.fields if f.validation_status == 'VALID' and f.field_name not in reviewed_names] + result.reviewed_fields
        proposals = [c for c in result.candidates if c.metadata.get('domain_supported') == 'true'
                     and c.metadata.get('disposition') in {'proposal', 'duplicate'}]
        if result.conflicts:
            return 'Meaningful source disagreement remains after L1; L2 proposals require review'
        for name in ('sku', 'quantity'):
            if len({f.value for f in protected if f.field_name == name}) > 1:
                return 'Multiple explicit item/value associations require interpretation and human review'
            if any(f.field_name == name for f in protected):
                continue
            observations = [f for f in result.rules.fields if f.field_name == name]
            if any(f.validation_status == 'UNRESOLVED' and f.evidence for f in observations):
                if any(f.metadata.get('disposition') == 'unverified_association' for f in observations):
                    continue
                return f'Meaningful {name} association remains unresolved after L1'
            values = {f.value for f in proposals if f.field_name == name}
            if len(values) > 1:
                return 'Multiple item/value associations remain after L1; never collapse to the first item'
            if values:
                continue
            if name == 'sku' and re.search(r'\b(?:need|order|prepare|send|nak|pesan|hantar)\b|要|订', message.raw.text, re.I):
                return 'Requested product is unknown or not grounded in the catalog; interpretation remains provisional'
        # A delivery expression is meaningful only when it is not already an
        # explicit metadata/calendar/DST problem that a model cannot solve.
        for field in result.rules.fields:
            if field.field_name != 'requested_delivery_at' or field.validation_status != 'UNRESOLVED' or not field.evidence:
                continue
            if field.metadata.get('rescheduling') == 'true' or field.metadata.get('correction') == 'true':
                return 'Complex temporal delivery rescheduling request requires semantic interpretation and human review'
            if field.metadata.get('date_range') == 'true':
                return 'Delivery date window range requires semantic interpretation and operator confirmation'
            if field.metadata.get('multiple_delivery_dates') == 'true':
                return 'Multiple conflicting delivery dates require semantic interpretation and human review'
            if field.metadata.get('approximate') == 'true':
                continue
            if field.metadata.get('meal_period') or field.metadata.get('unconfirmed_time') == 'true':
                continue
            reason = field.metadata.get('reason', '')
            if message.raw.business_timezone and not re.search(r'timezone|year|timestamp|past|DST|nonexistent|ambiguous local|lower.bound|after ', reason, re.I):
                return 'Literal delivery association remains unresolved; L2 cannot invent a normalized instant'
        return None

    async def _infer_observations(self, engine, message, result):
        """Cache raw, grounded observations only; current domain/review gates run again.

        Cache hits/coalesced calls do not claim a new worker invocation. Failures
        count as requests but are never cached. Bounds prevent stale, unbounded
        cross-message retention in the long-lived development repository.
        """
        request = InferenceInput(engine=engine, messages=[SourceText(id="m1", text=message.raw.text)])
        config = getattr(self.endpoint, "config", None)
        key = (message.raw.tenant_id, engine, id(self.endpoint), getattr(config, "url", ""),
               MODEL_CONFIG[engine], "grounded-observations-v2",
               hashlib.sha256(request.model_dump_json().encode()).hexdigest())
        now = time.monotonic()
        cached = self._inference_cache.get(key)
        result.telemetry[engine] = {"attempted": False, "succeeded": False, "cached": False}
        if cached and now - cached[0] < self.cache_ttl_seconds:
            answer = validate_evidence(cached[1].model_copy(deep=True), request)
            self._inference_cache.move_to_end(key)
            result.telemetry[engine]["cached"] = True
            result.routing_reasons[engine] = "Retrieved grounded observations from idempotency cache (0 worker network calls)"
        else:
            self._inference_cache.pop(key, None)
            flight_key = (asyncio.get_running_loop(), key)
            task = self._inflight.get(flight_key)
            if task is not None:
                answer = validate_evidence((await asyncio.shield(task)).model_copy(deep=True), request)
                result.telemetry[engine]["coalesced"] = True
            else:
                result.telemetry[engine]["attempted"] = True
                self.worker_request_count += 1
                result.worker_request_count += 1

                async def invoke():
                    try:
                        async with asyncio.timeout(self.request_timeout_seconds):
                            raw = await self.endpoint.infer(request)
                        # Revalidate even injected/custom adapters, not just HTTP.
                        answer = InferenceOutput.model_validate(raw.model_dump() if isinstance(raw, InferenceOutput) else raw)
                        return validate_evidence(answer, request)
                    except TimeoutError:
                        raise InferenceFailure('timeout') from None
                    except (ValueError, TypeError):
                        raise InferenceFailure('invalid_structured_output') from None

                task = asyncio.create_task(invoke())
                self._inflight[flight_key] = task
                try:
                    answer = await task
                finally:
                    self._inflight.pop(flight_key, None)
                self._inference_cache[key] = (time.monotonic(), answer.model_copy(deep=True))
                while len(self._inference_cache) > self.cache_max_entries:
                    self._inference_cache.popitem(last=False)
        result.telemetry[engine].update(
            succeeded=True, model=answer.model_id, revision=answer.revision,
            device=answer.gpu_name, dtype=answer.dtype, peak_gpu_bytes=answer.peak_gpu_bytes,
            inference_seconds=answer.inference_seconds if result.telemetry[engine]["attempted"] else 0.0,
            load_seconds=answer.load_seconds if result.telemetry[engine]["attempted"] else 0.0,
        )
        return answer

    @staticmethod
    def _candidate(observation: Observation, message, catalog, model_id, revision, has_existing_quantity: bool = False):
        name = {
            "product": "sku",
            "quantity": "quantity",
            "unit": "unit",
            "delivery": "requested_delivery_at",
            "order_reference": "order_id",
        }[observation.field]
        quote = observation.quote
        value = quote
        reason = "Model proposal only; independent semantic/domain review required"
        status = "UNRESOLVED"
        supported = False
        subspan = None
        qualifier = None
        is_non_order = request_intent(message.raw.text) != 'UNCLASSIFIED' or bool(NON_ORDER_PATTERNS.search(message.raw.text))

        if observation.field == "product":
            matches = []
            units = '|'.join(re.escape(u) for u in UNIT_NORMALIZATION)
            for p in catalog:
                if p.tenant_id != message.raw.tenant_id:
                    continue
                for alias in p.aliases:
                    m = re.fullmatch(
                        r'\s*(?:(?:[0-9]+(?:\.[0-9]+)?\s*)?(?:(?:' + units + r')\s*)?)?(?P<alias>' + re.escape(alias) + r')\s*',
                        quote, re.IGNORECASE,
                    )
                    if m:
                        matches.append((p, m.span("alias")))
            if matches:
                max_len = max(span[1] - span[0] for _, span in matches)
                matches = [m for m in matches if (m[1][1] - m[1][0]) == max_len]
            if len({(p.sku, p.unit) for p, _ in matches}) == 1:
                value = matches[0][0].sku
                subspan = matches[0][1]
                supported = not is_non_order
                if is_non_order:
                    reason = "Product mentioned in non-order inquiry or customer feedback"
            else:
                reason = "Unknown or ambiguous SKU alias; model cannot establish catalog membership"

        elif observation.field == "unit":
            norm = UNIT_NORMALIZATION.get(quote.lower(), quote)
            value = norm
            if quote.lower() not in UNIT_NORMALIZATION:
                status, reason = "INVALID", "Unsupported unit token; no automatic conversion"
            else:
                supported = not is_non_order
                if model_id == MODEL_CONFIG['qwen'][0]:
                    known = {f.value for f in extract_explicit_fields(message, catalog=catalog).fields
                             if f.field_name == 'sku' and f.validation_status == 'VALID'}
                    supported = supported and any(p.tenant_id == message.raw.tenant_id and p.sku in known and p.unit == norm for p in catalog)
                    if not supported:
                        reason = 'Unit/SKU compatibility is unverified or incompatible; human review required'

        elif observation.field == "quantity":
            # Delegate meaning/association to L0, then accept only its exact
            # quantity subspan inside this observation. Never pick first digit.
            quantities = [
                f for f in extract_explicit_fields(message, catalog=catalog).fields
                if f.field_name == "quantity" and f.validation_status == "VALID" and f.evidence
                and observation.start <= f.evidence[0].start < f.evidence[0].end <= observation.end
            ]
            if len(quantities) == 1:
                q = quantities[0]
                value = q.value
                subspan = (q.evidence[0].start - observation.start, q.evidence[0].end - observation.start)
                supported = True
            elif is_non_order:
                status, reason = "INVALID", "Number mentioned in non-order inquiry or feedback"
            elif CONFLICT_PATTERNS.search(message.raw.text):
                status, reason = "INVALID", "Conflicting or tentative quantity expression; cannot resolve single number"
            elif has_existing_quantity:
                status, reason = "UNRESOLVED", "Literal number only; existing valid or reviewed quantity takes precedence"
                supported = False
            else:
                units = '|'.join(re.escape(u) for u in UNIT_NORMALIZATION)
                aliases = '|'.join(re.escape(a) for p in catalog if p.tenant_id == message.raw.tenant_id for a in p.aliases)
                m = re.fullmatch(r'\s*([0-9]+)\s*(?:(?:' + units + r')\s*)?' +
                                 (r'(?:(?:' + aliases + r')\s*)?' if aliases else '') + r'\s*', quote, re.I)
                if m and Decimal(m.group(1)) > 0:
                    value = m.group(1)
                    subspan = (m.start(1), m.end(1))
                    supported = True
                    reason = "Model proposed quantity candidate pending human review"
                else:
                    status, reason = "INVALID", "Quantity must be an explicit positive ASCII decimal"

        elif observation.field == "delivery":
            # Guard against model proposing the superseded moved-from date in a rescheduling clause
            preceding = message.raw.text[max(0, observation.start - 25):observation.start].lower()
            is_superseded_date = bool(re.search(r'\b(?:from|dari|not\s+on|instead\s+of|bukan|daripada|sebelum ini)\s*$', preceding)) or bool(re.search(r'\s*(?:从)\s*$', preceding))
            if is_non_order or PAST_DATE_PATTERNS.search(quote):
                status, reason = "INVALID", "Time expression mentioned in non-order inquiry or past context"
                supported = False
            elif is_superseded_date:
                status, reason = "INVALID", "Superseded or cancelled delivery date in rescheduling clause; model proposal rejected"
                supported = False
            else:
                supported = True
                reason = "Raw delivery expression only; model cannot normalize or override date safety rules"
                if DEADLINE_PRE_RE.search(quote) or DEADLINE_POST_RE.search(quote):
                    qualifier = "DEADLINE"

        elif observation.field == "order_reference":
            m = ORDER_RE.search(quote)
            if m:
                value = m.group()
                subspan = (m.start(), m.end())
                supported = True
                reason = "Model proposed order reference pending human review"
            else:
                supported = False
                status, reason = "INVALID", "Extracted order reference does not match expected format"

        evidence = FieldEvidence(
            evidence_id=f"model:{message.message_id}:{observation.start}:{observation.end}:{observation.field}",
            message_id=message.message_id,
            quote=quote,
            start=observation.start,
            end=observation.end,
            method="MODEL",
            method_version=f"{model_id}@{revision}",
        )
        evidence_list = [evidence]
        if subspan and subspan != (0, len(quote)):
            start, end = observation.start + subspan[0], observation.start + subspan[1]
            evidence_list.append(
                FieldEvidence(
                    evidence_id=f"normalized:{message.message_id}:{start}:{end}",
                    message_id=message.message_id,
                    quote=message.raw.text[start:end],
                    start=start,
                    end=end,
                    method="MODEL",
                    method_version=f"{model_id}@{revision}",
                )
            )

        return ExtractedField(
            field_name=name,
            value=value,
            validation_status=status,
            evidence=evidence_list,
            qualifier=qualifier,
            metadata={
                "reason": reason,
                "group_id": observation.group_id or "",
                "model_id": model_id,
                "model_revision": revision,
                "provisional": "true",
                "domain_supported": str(supported).lower(),
                "normalization": "catalog_and_l0_subspan_v3",
            },
        )

