"""Rebuild hand-labelled P1-00 examples. This is NOT an extraction engine.

Run from backend: python app/context/fixtures/author_fixtures.py
Dates and expected labels are deliberately fixed; no wall clock/model is used.
"""

import hashlib
import json
from pathlib import Path

TENANT = "synthetic_tenant_a"
DELIVERY = "2026-10-21T15:00:00+08:00"


def record(key, title, text, *, channel="WHATSAPP", readiness="READY", identity="LINK_VERIFIED",
           order=None, quantity=None, delivery=None, missing=None, conflicts=None, annotations=(),
           provider=None, reply=None, processing="PROCESSED"):
    message_id = f"msg_{key}"
    fields = []
    for name, value, quote in annotations:
        start = text.index(quote)
        fields.append(dict(field_name=name, value=value, validation_status="VALID", confidence=None,
                           evidence=[dict(evidence_id=f"ev_{key}_{name}", message_id=message_id,
                           quote=quote, start=start, end=start + len(quote), method="FIXTURE", method_version="p1-00-hand-labelled-v1")]))
    for name in missing or []:
        fields.append(dict(field_name=name, value=None, validation_status="MISSING", evidence=[]))
    return dict(scenario_id=key, title=title, message=dict(message_id=message_id,
        raw=dict(tenant_id=TENANT, channel=channel, provider_message_id=provider or f"provider_{key}",
                 sender_identity_id="synthetic_identity_a", sender_alias="Demo buyer A", received_at="2026-10-20T10:00:00+08:00",
                 business_timezone="Asia/Kuala_Lumpur", text=text, attachments=[], language="en",
                 thread_ref="synthetic_thread_a", reply_to_provider_message_id=reply, adapter_mode="SYNTHETIC"),
        content_sha256=hashlib.sha256(text.encode()).hexdigest(), processing_status=processing, fields=fields,
        diagnostic="Model unavailable; manual review required" if processing == "PROCESSING_FAILED" else None),
        context=dict(tenant_id=TENANT, context_id=f"ctx_{key}", source_message_ids=[message_id],
            customer_id="synthetic_customer_a" if identity == "LINK_VERIFIED" else None,
            customer_identity_status=identity, order_id=order,
            requested_items=[dict(sku="BURGER", quantity=quantity, unit="pcs")] if quantity else [],
            requested_delivery_at=delivery, field_evidence={f["field_name"]: [f["evidence"][0]["evidence_id"]] for f in fields if f["evidence"]},
            conflicts=conflicts or [], missing_fields=missing or [], context_version=1, status=readiness),
        review=dict(tenant_id=TENANT, context_id=f"ctx_{key}", review_id=f"review_{key}", expected_context_version=1,
                    status="PENDING", note="Hand-labelled fixture; no processing or review action has run"))


def build():
    valid_text = "I need 100 burgers tomorrow before 3pm"
    annotations = [("sku", "BURGER", "burgers"), ("quantity", "100", "100"), ("unit", "pcs", "burgers"),
                   ("requested_delivery_at", DELIVERY, "tomorrow before 3pm")]
    records = [
        record("valid", "New customer request", valid_text, quantity="100", delivery=DELIVERY, annotations=annotations),
        record("missing", "Delivery time missing", "Please send 40 burgers", channel="EMAIL", readiness="PARTIAL",
               quantity="40", missing=["requested_delivery_at"], annotations=[("sku", "BURGER", "burgers"), ("quantity", "40", "40")]),
        record("duplicate", "Repeated provider delivery", valid_text, quantity="100", delivery=DELIVERY,
               annotations=annotations, provider="provider_valid"),
        record("followup", "Follow-up for order A-101", "For A-101, make it 120 burgers tomorrow before 3pm", order="synthetic_order_a101",
               quantity="120", delivery=DELIVERY, reply="provider_valid", annotations=[("order_id", "synthetic_order_a101", "A-101"),
               ("quantity", "120", "120"), ("sku", "BURGER", "burgers"), ("requested_delivery_at", DELIVERY, "tomorrow before 3pm")]),
        record("ambiguous", "Several possible orders", "Same as last time please", channel="TELEGRAM", readiness="UNRESOLVED", identity="AMBIGUOUS"),
        record("conflict", "Change to confirmed terms", "A-102: change 80 burgers to 150 tomorrow before 3pm", channel="EMAIL", readiness="CONFLICT",
               order="synthetic_order_a102", quantity="150", delivery=DELIVERY, conflicts=["Quantity differs from confirmed 80 pcs; propose amendment to Core"],
               annotations=[("quantity", "150", "150"), ("sku", "BURGER", "burgers"), ("requested_delivery_at", DELIVERY, "tomorrow before 3pm")]),
        record("cross_tenant", "Foreign order reference", "Please update B-201 to 100 burgers", readiness="UNRESOLVED", identity="UNVERIFIED"),
        record("unavailable", "Extraction unavailable", "See attached request details", channel="UNKNOWN", readiness="UNRESOLVED", processing="PROCESSING_FAILED"),
        record("multilingual", "Code-switching request", "Saya nak 100 burgers, esok sebelum 3pm", channel="TELEGRAM", quantity="100", delivery=DELIVERY,
               annotations=[("quantity", "100", "100"), ("sku", "BURGER", "burgers"), ("requested_delivery_at", DELIVERY, "esok sebelum 3pm")]),
    ]
    behaviors = {
        "valid": ("New request is information-ready, not a confirmed commitment", "REVIEW_REQUEST"),
        "missing": ("Absent delivery remains missing", "REQUEST_INFORMATION"),
        "duplicate": ("Future ingestion must deduplicate tenant/channel/provider key", "DEDUPLICATE_IN_P1_01"),
        "followup": ("Verified identity + explicit order may propose existing context update", "VERSIONED_UPDATE_IN_P1_01"),
        "ambiguous": ("Fuzzy wording must not auto-link either order", "MANUAL_ASSOCIATION"),
        "conflict": ("Preserve confirmed 80 pcs; route 150 pcs as proposed amendment", "PROPOSE_AMENDMENT"),
        "cross_tenant": ("Foreign order must not be linked or disclosed to sender", "DENY_FOREIGN_ASSOCIATION"),
        "unavailable": ("Unavailable extraction leaves unresolved information", "MANUAL_REVIEW"),
        "multilingual": ("Hand-labelled Malay/English date uses fixed message-local timezone", "REVIEW_REQUEST"),
    }
    expectations = []
    for row in records:
        key, context = row["scenario_id"], row["context"]
        behavior, action = behaviors[key]
        expectations.append(dict(scenario_id=key, behavior=behavior, expected_readiness=context["status"],
            expected_order_id=context["order_id"], expected_quantity=context["requested_items"][0]["quantity"] if context["requested_items"] else None,
            expected_delivery_at=context["requested_delivery_at"], expected_next_action=action,
            candidate_order_ids=["synthetic_order_a101", "synthetic_order_a102"] if key == "ambiguous" else [],
            duplicate_of="valid" if key == "duplicate" else None))
    return dict(mode="SYNTHETIC_FIXTURES", business_timezone="Asia/Kuala_Lumpur",
        customers=[dict(tenant_id=TENANT, customer_id="synthetic_customer_a", alias="Demo buyer A", verified_identity_ids=["synthetic_identity_a"]),
                   dict(tenant_id="synthetic_tenant_b", customer_id="synthetic_customer_b", alias="Demo buyer A", verified_identity_ids=["synthetic_identity_b"])],
        skus=[dict(tenant_id=t, sku="BURGER", label="Synthetic burger", unit="pcs") for t in [TENANT, "synthetic_tenant_b"]],
        orders=[dict(tenant_id=t, order_id=o, customer_id=c, items=[dict(sku="BURGER", quantity=q, unit="pcs")],
                     commitment_ref="synthetic_commitment_a102" if o.endswith("a102") else None,
                     agreement_state="CONFIRMED" if o.endswith("a102") else "REQUESTED")
                for t, o, c, q in [(TENANT, "synthetic_order_a101", "synthetic_customer_a", "100"),
                                  (TENANT, "synthetic_order_a102", "synthetic_customer_a", "80"),
                                  ("synthetic_tenant_b", "synthetic_order_b201", "synthetic_customer_b", "60")]],
        records=records, expectations=expectations)


if __name__ == "__main__":
    Path(__file__).with_name("scenarios.json").write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
