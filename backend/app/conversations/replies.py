"""Authorized factual reply preparation, with no transport or lifecycle effects.

Only trusted server-side adapters may construct policies and source facts. This
is deliberately not an API accepting client assertions of public approval.
P4 remains the sole send/receipt owner; Replit integration is unverified.
"""

from datetime import datetime
from typing import Literal, Protocol, Sequence

from pydantic import AwareDatetime

from app.orders.terms import ImmutableContract, Text

PublicField = Literal["faq_answer", "fixed_price", "business_hours", "business_address"]


class PublicKnowledgePolicy(ImmutableContract):
    tenant_id: Text
    policy_version: Text
    allowed_fields: frozenset[PublicField]


class KnowledgeFact(ImmutableContract):
    tenant_id: Text
    fact_id: Text
    field: Text
    value: Text
    visibility: Literal["PUBLIC", "PRIVATE"]
    approval_ref: Text | None
    source_version: Text | None
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    evidence_refs: tuple[Text, ...]


class AuthorizedReplyContext(ImmutableContract):
    tenant_id: Text
    policy_version: Text
    facts: tuple[KnowledgeFact, ...]


class DraftResult(ImmutableContract):
    state: Literal["DRAFT", "REVIEW_REQUIRED"]
    text: str | None = None
    provider: Literal["TEMPLATE", "REPLIT", "NONE"]
    policy_version: Text
    evidence_refs: tuple[Text, ...] = ()
    transport_state: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"
    reason: Text | None = None


class ReplyGenerator(Protocol):
    async def generate(self, context: AuthorizedReplyContext) -> DraftResult: ...


class TemplateGenerator:
    async def generate(self, context: AuthorizedReplyContext) -> DraftResult:
        return DraftResult(state="DRAFT", text="\n".join(fact.value for fact in context.facts),
                           provider="TEMPLATE", policy_version=context.policy_version,
                           evidence_refs=tuple(sorted({ref for fact in context.facts
                                                       for ref in fact.evidence_refs})))


class ReplitGenerator:
    """Unavailable seam until endpoint/auth/privacy/timeout tests and owner policy exist."""

    async def generate(self, context: AuthorizedReplyContext) -> DraftResult:
        raise RuntimeError("INFERENCE_PROVIDER_UNAVAILABLE")


async def prepare_factual_reply(policy: PublicKnowledgePolicy, facts: Sequence[KnowledgeFact], *,
                                now: datetime, risk_flags: Sequence[str] = (),
                                generator: ReplyGenerator | None = None) -> DraftResult:
    """Filter before generation; uncertain/commercial requests require review.

    Optional generator is an injected, separately verified adapter. Until a
    wording validator/policy is ratified, altered factual copy always falls back
    to the exact approved template; no permissive LLM promise classifier.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Offset-aware evaluation time required")

    def review(reason):
        return DraftResult(state="REVIEW_REQUIRED", provider="NONE",
                           policy_version=policy.policy_version, reason=reason)

    if risk_flags:
        return review("RISK_REQUIRES_HUMAN_REVIEW")
    allowed = tuple(fact for fact in facts if (
        fact.tenant_id == policy.tenant_id and fact.field in policy.allowed_fields
        and fact.visibility == "PUBLIC" and fact.approval_ref and fact.source_version
        and fact.evidence_refs and fact.observed_at <= now < fact.valid_until
    ))
    if not allowed:
        return review("INSUFFICIENT_AUTHORIZED_KNOWLEDGE")
    by_field: dict[str, str] = {}
    for fact in allowed:
        if fact.field in by_field and by_field[fact.field] != fact.value:
            return review("CONFLICTING_KNOWLEDGE")
        by_field[fact.field] = fact.value
    context = AuthorizedReplyContext(tenant_id=policy.tenant_id,
                                     policy_version=policy.policy_version, facts=allowed)
    baseline = await TemplateGenerator().generate(context)
    if generator is None:
        return baseline
    try:
        candidate = await generator.generate(context)
    except (TimeoutError, ConnectionError, RuntimeError):
        return baseline.model_copy(update={"reason": "PROVIDER_UNAVAILABLE_TEMPLATE_FALLBACK"})
    if (candidate.state != "DRAFT" or candidate.text != baseline.text
            or candidate.policy_version != baseline.policy_version
            or candidate.evidence_refs != baseline.evidence_refs):
        return baseline.model_copy(update={"reason": "UNVERIFIED_WORDING_TEMPLATE_FALLBACK"})
    return candidate
