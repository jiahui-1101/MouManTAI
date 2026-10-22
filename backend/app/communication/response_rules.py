"""Conservative full-message rules. No partial phrase ever proves acceptance."""
from dataclasses import dataclass
import json
import re

from pydantic import Field
from app.core.schemas import ContractModel, OffsetAwareDatetime
from .confirmation_schemas import ResponseIntent


class ProposedChanges(ContractModel):
    quantity: str | None = Field(default=None, max_length=40, pattern=r"^(?:[1-9]\d*|0)(?:\.\d+)?$")
    deadline: OffsetAwareDatetime | None = None
    special_instructions: str | None = Field(default=None, max_length=1000)


@dataclass(frozen=True)
class ClassifiedResponse:
    intent: ResponseIntent
    reason: str
    proposal_id: str | None = None
    proposal_version: int | None = None
    terms_digest: str | None = None
    changes: dict | None = None


def classify_response(text: str) -> ClassifiedResponse:
    # Exact grammar in EN/MS/ZH; mixed, contradictory and casual replies fail
    # to match the WHOLE message and remain UNKNOWN, including OK/sure/可以.
    text = text.strip()
    patterns = (
        ("ACCEPT", r"(?:ACCEPT|SAYA SETUJU|我接受) (\S+) v([1-9]\d*) terms:([0-9a-f]{64})"),
        ("REJECT", r"(?:REJECT|SAYA TOLAK|我拒绝) (\S+) v([1-9]\d*)"),
        ("COUNTEROFFER", r"(?:COUNTEROFFER|CADANGAN BALAS|反建议) (\S+) v([1-9]\d*) changes:(\{[^\n]{1,2048}\})"),
        ("CLARIFICATION", r"(?:CLARIFICATION|PENJELASAN|请澄清) (\S+) v([1-9]\d*): .{1,1000}"),
    )
    for intent, pattern in patterns:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        proposal, version = match.group(1), int(match.group(2))
        if intent == "COUNTEROFFER":
            try:
                # Duplicate JSON keys can obscure contradictory terms.
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result: raise ValueError("duplicate key")
                        result[key] = value
                    return result
                values = json.loads(match.group(3), object_pairs_hook=unique)
                changes = ProposedChanges.model_validate(values).model_dump(mode="json", exclude_none=True)
                if not changes or ("quantity" in changes and not any(c in "123456789" for c in changes["quantity"])):
                    raise ValueError("empty/nonpositive counteroffer")
            except (ValueError, TypeError, RecursionError):
                return ClassifiedResponse("UNKNOWN", "COUNTEROFFER_REQUIRES_CLARIFICATION")
            return ClassifiedResponse(intent, "EXPLICIT_BOUND_COUNTEROFFER", proposal, version, changes=changes)
        return ClassifiedResponse(intent, "EXPLICIT_BOUND_RESPONSE", proposal, version,
            match.group(3) if intent == "ACCEPT" else None)
    return ClassifiedResponse("UNKNOWN", "AMBIGUOUS_OR_UNBOUND_RESPONSE")
