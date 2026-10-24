"""Phase 2: Independent Unseen Accuracy Acceptance Runner.

Executes genuinely unseen customer messages against the real P1 AI pipeline
with live RunPod GPU inference (GLiNER + Qwen3) and PostgreSQL persistence.
"""
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Ensure app imports work
repo_root = Path(__file__).resolve().parents[5]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.context.dev_app import _load_env_if_present
_load_env_if_present()

# Ensure catalog path is configured
catalog_path = Path(__file__).resolve().parents[2] / "catalogs" / "catalog.json"
if catalog_path.is_file():
    os.environ["P1_PRODUCT_CATALOG_PATH"] = str(catalog_path)

from app.context.context_service import ContextService
from app.context.dev_database import create_p1_engine
from app.context.postgres_repository import PostgresMessageRepository
from app.context.product_catalog import load_product_catalog
from app.context.schemas import RawMessageEnvelope


def load_unseen_fixtures():
    fixtures_file = Path(__file__).with_name("unseen_fixtures.json")
    return json.loads(fixtures_file.read_text(encoding="utf-8"))


def evaluate_unseen_acceptance():
    data = load_unseen_fixtures()
    catalog = load_product_catalog()
    engine = create_p1_engine()
    repo = PostgresMessageRepository(engine, catalog=catalog)

    proposal_svc = repo.proposal_service
    print("=" * 80)
    print("P1 REAL RUNPOD GPU INFERENCE & UNSEEN ACCURACY ACCEPTANCE")
    print("=" * 80)
    print(f"Catalog loaded: {len(catalog)} SKUs: {[p.sku for p in catalog]}")
    print(f"AI Pipeline Enabled: {proposal_svc.enabled}")
    print(f"AI Stages: {proposal_svc.stages}")
    endpoint = getattr(proposal_svc, "endpoint", None)
    if endpoint:
        print(f"Endpoint Mode: {endpoint.config.mode}")
        print(f"Endpoint URL: {endpoint.config.url}")
    print(f"Total Unseen Cases: {len(data['cases'])}")
    print("=" * 80)

    results = []
    
    # Metric accumulators
    prod_tp = prod_fp = prod_fn = 0
    qty_tp = qty_fp = qty_fn = 0
    unit_total = unit_correct = 0
    del_total = del_correct = 0
    multi_total = multi_correct = 0
    msg_exact_matches = 0
    unsafe_auto_accepts = 0
    routing_correct = 0

    gpu_telemetry = []

    for idx, case in enumerate(data["cases"], 1):
        case_id = case["id"]
        category = case["category"]
        text = case["text"]
        ref_dt = datetime.fromisoformat(data["reference_timestamp"])
        tenant_id = data["tenant_id"]

        print(f"\n[{idx}/{len(data['cases'])}] Running case: {case_id} ({category})")
        print(f"  Input: {text!r}")

        # Ingest envelope
        envelope = RawMessageEnvelope(
            tenant_id=tenant_id,
            channel="WHATSAPP",
            provider_message_id=f"prov_{case_id}_{uuid4().hex[:6]}",
            sender_identity_id="+60123456789",
            sender_alias="Burger King",
            received_at=ref_dt,
            message_at=ref_dt,
            business_timezone=data["business_timezone"],
            text=text,
        )
        ingest_res = repo.ingest(envelope, ref_dt)
        message_id = ingest_res.message.message_id

        # Process with AI pipeline
        proc_res = repo.process(tenant_id, message_id, reprocess=True, now=ref_dt)
        attempt = proc_res.attempt

        # Parse diagnostics
        diag = {}
        if attempt.diagnostic:
            try:
                diag = json.loads(attempt.diagnostic)
            except Exception:
                diag = {"raw": attempt.diagnostic}

        model_outcomes = diag.get("model_outcomes", {})
        runtime_reported = diag.get("runtime_reported", {})
        accepted_model_fields = diag.get("accepted_model_fields", 0)
        extractor_version = attempt.extractor_version

        # Build / update context
        ctx_svc = ContextService(repo)
        ctx = ctx_svc.create_or_update_from_message(tenant_id, message_id)

        # Telemetry collection
        if runtime_reported:
            gpu_telemetry.append({
                "case_id": case_id,
                "runtime_reported": runtime_reported,
                "model_outcomes": model_outcomes,
            })

        # Extract predicted items
        predicted_items = []
        for it in ctx.requested_items:
            predicted_items.append({
                "sku": it.sku,
                "quantity": str(int(it.quantity)) if it.quantity == int(it.quantity) else str(it.quantity),
                "unit": it.unit,
            })

        # Extract predicted delivery
        predicted_delivery_str = None
        if ctx.requested_delivery_at:
            # ISO local format without tz for comparison
            predicted_delivery_str = ctx.requested_delivery_at.strftime("%Y-%m-%dT%H:%M:%S")

        expected_items = case["expected_items"]
        expected_delivery = case["expected_delivery_date"]
        requires_review = case["requires_review"]
        context_status = ctx.status

        # 1. Product Evaluation
        exp_skus = Counter(it["sku"] for it in expected_items)
        pred_skus = Counter(it["sku"] for it in predicted_items)
        case_prod_tp = sum((exp_skus & pred_skus).values())
        case_prod_fp = sum((pred_skus - exp_skus).values())
        case_prod_fn = sum((exp_skus - pred_skus).values())
        prod_tp += case_prod_tp
        prod_fp += case_prod_fp
        prod_fn += case_prod_fn

        # 2. Quantity Evaluation
        exp_qtys = Counter(it["quantity"] for it in expected_items)
        pred_qtys = Counter(it["quantity"] for it in predicted_items)
        case_qty_tp = sum((exp_qtys & pred_qtys).values())
        case_qty_fp = sum((pred_qtys - exp_qtys).values())
        case_qty_fn = sum((exp_qtys - pred_qtys).values())
        qty_tp += case_qty_tp
        qty_fp += case_qty_fp
        qty_fn += case_qty_fn

        # 3. Unit Evaluation
        exp_units = [it["unit"] for it in expected_items]
        pred_units = [it["unit"] for it in predicted_items]
        for eu in exp_units:
            unit_total += 1
            if eu in pred_units:
                unit_correct += 1
                pred_units.remove(eu)

        # 4. Delivery Date Evaluation
        case_del_match = False
        if expected_delivery is None:
            del_total += 1
            if predicted_delivery_str is None or requires_review:
                del_correct += 1
                case_del_match = True
        else:
            del_total += 1
            if predicted_delivery_str == expected_delivery:
                del_correct += 1
                case_del_match = True

        # 5. Multi-Item Exact Match
        case_multi_match = None
        if len(expected_items) > 1:
            multi_total += 1
            exp_item_tuples = sorted((it["sku"], it["quantity"], it["unit"]) for it in expected_items)
            pred_item_tuples = sorted((it["sku"], it["quantity"], it["unit"]) for it in predicted_items)
            case_multi_match = (exp_item_tuples == pred_item_tuples)
            if case_multi_match:
                multi_correct += 1

        # 6. Message-Level Exact Match
        exp_item_tuples_all = sorted((it["sku"], it["quantity"], it["unit"]) for it in expected_items)
        pred_item_tuples_all = sorted((it["sku"], it["quantity"], it["unit"]) for it in predicted_items)
        msg_exact = (exp_item_tuples_all == pred_item_tuples_all and case_del_match)
        if msg_exact:
            msg_exact_matches += 1

        # 7. Unsafe Auto-Accept & Routing
        # If requires_review is True, status MUST NOT be INFORMATION_READY
        is_unsafe = (requires_review and context_status == "INFORMATION_READY")
        if is_unsafe:
            unsafe_auto_accepts += 1

        # Correct routing: if requires_review -> status in (CONFLICT, INFORMATION_PARTIAL)
        # if not requires_review -> status == INFORMATION_READY
        is_routing_correct = (requires_review == (context_status != "INFORMATION_READY"))
        if is_routing_correct:
            routing_correct += 1

        print(f"  Extractor: {extractor_version} | Models: {model_outcomes} | Accepted: {accepted_model_fields}")
        print(f"  Status: {context_status} (requires_review={requires_review})")
        print(f"  Predicted Items: {predicted_items} | Expected: {expected_items}")
        print(f"  Predicted Delivery: {predicted_delivery_str} | Expected: {expected_delivery}")
        print(f"  Match: Prod TP={case_prod_tp} Qty TP={case_qty_tp} Del={case_del_match} MsgExact={msg_exact} Unsafe={is_unsafe}")

        results.append({
            "case_id": case_id,
            "category": category,
            "text": text,
            "extractor_version": extractor_version,
            "model_outcomes": model_outcomes,
            "accepted_model_fields": accepted_model_fields,
            "predicted_items": predicted_items,
            "expected_items": expected_items,
            "predicted_delivery": predicted_delivery_str,
            "expected_delivery": expected_delivery,
            "context_status": context_status,
            "requires_review": requires_review,
            "msg_exact": msg_exact,
            "is_unsafe": is_unsafe,
            "is_routing_correct": is_routing_correct,
            "conflicts": ctx.conflicts,
            "missing_fields": ctx.missing_fields,
        })

    # Summary Metrics Calculation
    prod_prec = prod_tp / (prod_tp + prod_fp) if (prod_tp + prod_fp) > 0 else 1.0
    prod_rec = prod_tp / (prod_tp + prod_fn) if (prod_tp + prod_fn) > 0 else 1.0
    prod_f1 = 2 * prod_prec * prod_rec / (prod_prec + prod_rec) if (prod_prec + prod_rec) > 0 else 0.0

    qty_prec = qty_tp / (qty_tp + qty_fp) if (qty_tp + qty_fp) > 0 else 1.0
    qty_rec = qty_tp / (qty_tp + qty_fn) if (qty_tp + qty_fn) > 0 else 1.0
    qty_f1 = 2 * qty_prec * qty_rec / (qty_prec + qty_rec) if (qty_prec + qty_rec) > 0 else 0.0

    unit_acc = unit_correct / unit_total if unit_total > 0 else 1.0
    del_acc = del_correct / del_total if del_total > 0 else 1.0
    multi_match_acc = multi_correct / multi_total if multi_total > 0 else 1.0
    msg_exact_acc = msg_exact_matches / len(data["cases"])
    routing_acc = routing_correct / len(data["cases"])

    summary = {
        "total_cases": len(data["cases"]),
        "product_metrics": {
            "tp": prod_tp, "fp": prod_fp, "fn": prod_fn,
            "precision": round(prod_prec, 4),
            "recall": round(prod_rec, 4),
            "f1": round(prod_f1, 4),
        },
        "quantity_metrics": {
            "tp": qty_tp, "fp": qty_fp, "fn": qty_fn,
            "precision": round(qty_prec, 4),
            "recall": round(qty_rec, 4),
            "f1": round(qty_f1, 4),
        },
        "unit_accuracy": {
            "correct": unit_correct, "total": unit_total,
            "rate": round(unit_acc, 4),
        },
        "delivery_accuracy": {
            "correct": del_correct, "total": del_total,
            "rate": round(del_acc, 4),
        },
        "multi_item_exact_match": {
            "correct": multi_correct, "total": multi_total,
            "rate": round(multi_match_acc, 4),
        },
        "message_level_exact_match": {
            "correct": msg_exact_matches, "total": len(data["cases"]),
            "rate": round(msg_exact_acc, 4),
        },
        "unsafe_auto_accept": {
            "count": unsafe_auto_accepts,
            "rate": round(unsafe_auto_accepts / len(data["cases"]), 4),
        },
        "human_review_routing": {
            "correct": routing_correct, "total": len(data["cases"]),
            "rate": round(routing_acc, 4),
        },
        "gpu_telemetry_samples": gpu_telemetry[:5],
    }

    print("\n" + "=" * 80)
    print("FINAL EVALUATION METRICS REPORT")
    print("=" * 80)
    print(json.dumps(summary, indent=2))

    # Save output to file
    out_path = Path(__file__).with_name("unseen_acceptance_results.json")
    out_path.write_text(json.dumps({"summary": summary, "cases": results}, indent=2), encoding="utf-8")
    print(f"\nSaved full results to: {out_path}")
    return summary


if __name__ == "__main__":
    evaluate_unseen_acceptance()
