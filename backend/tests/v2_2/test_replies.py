import asyncio
from datetime import datetime, timedelta, UTC

import pytest


NOW = datetime(2026, 10, 23, tzinfo=UTC)


def policy():
    from app.conversations.replies import PublicKnowledgePolicy
    return PublicKnowledgePolicy(tenant_id="a", policy_version="1", allowed_fields={"faq_answer", "fixed_price"})


def fact(**updates):
    from app.conversations.replies import KnowledgeFact
    return KnowledgeFact.model_validate(dict(
        tenant_id="a", fact_id="faq_a", field="faq_answer", value="Open Monday to Friday.",
        visibility="PUBLIC", approval_ref="approval_faq_v1", source_version="2",
        observed_at=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=1),
        evidence_refs=["faq_evidence"],
    ) | updates)


def generate(facts, **kwargs):
    from app.conversations.replies import prepare_factual_reply
    return asyncio.run(prepare_factual_reply(policy(), facts, now=NOW, **kwargs))


def test_approved_factual_faq_is_a_draft_not_a_sent_message():
    result = generate([fact()])
    assert result.state == "DRAFT"
    assert result.provider == "TEMPLATE"
    assert result.transport_state == "NOT_REQUESTED"
    assert result.text == "Open Monday to Friday."
    assert result.evidence_refs == ("faq_evidence",)
    assert result.policy_version == "1"


def test_fixed_published_price_allowed_without_inventing_quote():
    result = generate([fact(field="fixed_price", value="MYR 2.00 per cup (catalog v2)")])
    assert result.state == "DRAFT"
    assert "MYR 2.00" in result.text


@pytest.mark.parametrize("changes", [
    {"field": "internal_margin"}, {"field": "supplier_bank_account"},
    {"tenant_id": "b"}, {"visibility": "PRIVATE"}, {"approval_ref": None},
    {"valid_until": NOW}, {"observed_at": NOW + timedelta(seconds=1)},
    {"evidence_refs": []}, {"source_version": None},
])
def test_restricted_stale_missing_evidence_and_cross_tenant_facts_never_reach_generator(changes):
    class MustNotRun:
        async def generate(self, context):
            pytest.fail("Unapproved information reached external generator")
    result = generate([fact(**changes)], generator=MustNotRun())
    assert result.state == "REVIEW_REQUIRED"
    assert result.text is None
    assert result.evidence_refs == ()


@pytest.mark.parametrize("risk", ["CUSTOM_QUOTE", "DISCOUNT", "DELIVERY_GUARANTEE", "IDENTITY_UNVERIFIED"])
def test_consequential_inquiry_is_review_even_when_public_facts_present(risk):
    result = generate([fact()], risk_flags=[risk])
    assert result.state == "REVIEW_REQUIRED"
    assert result.text is None


def test_allowlist_removes_private_fields_before_any_external_call_and_falls_back_on_timeout():
    seen = []
    class TimeoutGenerator:
        async def generate(self, context):
            seen.append(context)
            raise TimeoutError()
    result = generate([fact(), fact(fact_id="private", field="internal_margin", value="SECRET")],
                      generator=TimeoutGenerator())
    assert "SECRET" not in seen[0].model_dump_json()
    assert result.state == "DRAFT"
    assert result.provider == "TEMPLATE"
    assert result.reason == "PROVIDER_UNAVAILABLE_TEMPLATE_FALLBACK"


def test_generator_cannot_change_factual_output_in_unratified_wording_mode():
    from app.conversations.replies import DraftResult
    class InventsPromise:
        async def generate(self, context):
            return DraftResult(state="DRAFT", text="Guaranteed free delivery tomorrow", provider="REPLIT",
                               policy_version="1", evidence_refs=["faq_evidence"])
    result = generate([fact()], generator=InventsPromise())
    assert result.provider == "TEMPLATE"
    assert result.text == "Open Monday to Friday."
    assert result.reason == "UNVERIFIED_WORDING_TEMPLATE_FALLBACK"


def test_unconfigured_replit_has_no_endpoint_and_no_silent_qwen_fallback():
    from app.conversations.replies import ReplitGenerator
    result = generate([fact()], generator=ReplitGenerator())
    assert result.provider == "TEMPLATE"
    assert result.reason == "PROVIDER_UNAVAILABLE_TEMPLATE_FALLBACK"


def test_conflicting_facts_require_review_instead_of_choosing_a_price():
    result = generate([fact(field="fixed_price", value="MYR 2"),
                       fact(fact_id="other", field="fixed_price", value="MYR 3")])
    assert result.state == "REVIEW_REQUIRED"
    assert result.reason == "CONFLICTING_KNOWLEDGE"
