"""PromiseFlow P1 Comprehensive Evaluation Runner.

Evaluates extraction accuracy, robustness, and safety across:
- Mode 'rules': L0 deterministic rules only (runs offline)
- Mode 'qwen_only': Direct Qwen inference via GPU endpoint
- Mode 'full_pipeline': L0 + GLiNER + Qwen full pipeline
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# Add backend directory to sys.path
backend_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import InferenceFailure, InferenceInput
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import (
    ProductAlias,
    PROVISIONAL_PRODUCTS,
    extract_explicit_fields,
    UNIT_NORMALIZATION,
)
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import RawMessageEnvelope

EVAL_CATALOG = (
    ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers", "beef burger", "beef burgers", "chicken burger", "chicken burgers", "汉堡", "汉堡包", "roti burger"), "pcs"),
    ProductAlias("synthetic_tenant_a", "BREAD", ("bread", "buns", "bun", "面包", "roti"), "pcs"),
)


def load_dataset(dataset_path: Path) -> dict:
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def build_stored_message(case: dict, base_ts: datetime) -> StoredMessage:
    raw = RawMessageEnvelope(
        tenant_id="synthetic_tenant_a",
        channel="WHATSAPP",
        adapter_mode="SYNTHETIC",
        provider_message_id=f"msg_{case['id']}",
        sender_identity_id="+60123456789",
        sender_alias="Eval Customer",
        received_at=base_ts,
        message_at=base_ts,
        text=case["text"],
        business_timezone="Asia/Kuala_Lumpur",
        attachments=[],
    )
    return StoredMessage(
        message_id=f"stored_{case['id']}",
        raw=raw,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        processing_status="RECEIVED",
        content_sha256="abc",
        ingested_at=base_ts,
        updated_at=base_ts,
    )


def map_product_to_sku(quote: Optional[str]) -> Optional[str]:
    if not quote:
        return None
    q_lower = quote.lower().strip()
    for cat in EVAL_CATALOG:
        for alias in cat.aliases:
            if alias in q_lower or q_lower in alias:
                return cat.sku
    return quote.upper()


def extract_prediction_from_rules(rules) -> dict:
    sku_fields = [f for f in rules.fields if f.field_name == "sku" and f.validation_status == "VALID"]
    qty_fields = [f for f in rules.fields if f.field_name == "quantity" and f.validation_status == "VALID"]
    unit_fields = [f for f in rules.fields if f.field_name == "unit" and f.validation_status in ("VALID", "UNRESOLVED")]
    deliv_fields = [f for f in rules.fields if f.field_name == "requested_delivery_at" and f.validation_status == "VALID"]
    conflict_fields = [f for f in rules.fields if f.validation_status == "CONFLICT"]

    items = []
    # If single item matched
    if sku_fields and qty_fields:
        sku = sku_fields[0].value
        qty = qty_fields[0].value
        unit = unit_fields[0].value if unit_fields else "pcs"
        items.append({"sku": sku, "quantity": qty, "unit": unit})
    elif sku_fields:
        items.append({"sku": sku_fields[0].value, "quantity": None, "unit": "pcs"})
    elif qty_fields:
        items.append({"sku": None, "quantity": qty_fields[0].value, "unit": "pcs"})

    delivery = None
    if deliv_fields:
        f = deliv_fields[0]
        delivery = {"value": f.value, "qualifier": f.qualifier}

    has_conflicts = bool(conflict_fields)
    is_ready = bool(sku_fields and qty_fields and deliv_fields and not has_conflicts)
    
    if has_conflicts:
        readiness = "CONFLICT"
        routing = "MANUAL_REVIEW"
    elif is_ready:
        readiness = "READY"
        routing = "AUTO_ACCEPT"
    else:
        readiness = "PARTIAL"
        routing = "MANUAL_REVIEW"

    return {
        "items": items,
        "delivery": delivery,
        "readiness": readiness,
        "routing": routing,
        "has_conflicts": has_conflicts,
        "missing_fields": [f for f in ("sku", "quantity", "delivery") if (f == "sku" and not sku_fields) or (f == "quantity" and not qty_fields) or (f == "delivery" and not deliv_fields)],
    }


def evaluate_case(case: dict, pred: dict) -> dict:
    expected = case["expected"]
    exp_items = expected["items"]
    pred_items = pred["items"]

    # 1. Product/SKU Match
    exp_skus = [it["sku"] for it in exp_items if it.get("sku")]
    pred_skus = [it["sku"] for it in pred_items if it.get("sku")]

    sku_tp = len([s for s in pred_skus if s in exp_skus])
    sku_fp = len([s for s in pred_skus if s not in exp_skus])
    sku_fn = len([s for s in exp_skus if s not in pred_skus])

    # 2. Quantity Match
    exp_qtys = [str(it["quantity"]) for it in exp_items if it.get("quantity") is not None]
    pred_qtys = [str(it["quantity"]) for it in pred_items if it.get("quantity") is not None]

    qty_tp = len([q for q in pred_qtys if q in exp_qtys])
    qty_fp = len([q for q in pred_qtys if q not in exp_qtys])
    qty_fn = len([q for q in exp_qtys if q not in pred_qtys])

    # 3. Unit Match
    exp_units = [it["unit"] for it in exp_items if it.get("unit")]
    pred_units = [it["unit"] for it in pred_items if it.get("unit")]
    unit_match = (exp_units == pred_units) if exp_units else True

    # 4. Delivery Match
    exp_deliv = expected.get("delivery")
    pred_deliv = pred.get("delivery")
    deliv_match = False
    is_ambiguous_expected = (exp_deliv and exp_deliv.get("status") == "AMBIGUOUS")
    
    if not exp_deliv and not pred_deliv:
        deliv_match = True
    elif exp_deliv and pred_deliv:
        pred_val = str(pred_deliv.get("value", "")).lower()
        exp_iso = str(exp_deliv.get("iso", "")).lower()
        exp_q = str(exp_deliv.get("quote", "")).lower()
        if exp_iso == pred_val or (exp_q and exp_q in pred_val):
            deliv_match = True
        elif exp_deliv.get("qualifier") == "DATE_ONLY" and pred_val.startswith(exp_iso[:10]):
            deliv_match = True

    # 5. Multi-item Exact Match
    multi_item_exact = False
    if len(exp_items) > 1:
        if len(exp_items) == len(pred_items):
            matched = True
            for exp_it, pred_it in zip(exp_items, pred_items):
                if exp_it.get("sku") != pred_it.get("sku") or str(exp_it.get("quantity")) != str(pred_it.get("quantity")):
                    matched = False
                    break
            multi_item_exact = matched
    elif len(exp_items) == 1:
        multi_item_exact = (len(pred_items) == 1 and exp_items[0].get("sku") == pred_items[0].get("sku") and str(exp_items[0].get("quantity")) == str(pred_items[0].get("quantity")))
    else:
        multi_item_exact = (len(pred_items) == 0)

    # 6. Safety & Routing
    exp_routing = expected.get("routing", "MANUAL_REVIEW")
    pred_routing = pred.get("routing", "MANUAL_REVIEW")
    routing_correct = (exp_routing == pred_routing)

    # Unsafe Auto-Accept: expected was MANUAL_REVIEW or REJECT, but prediction was AUTO_ACCEPT
    unsafe_auto_accept = (exp_routing in ("MANUAL_REVIEW", "REJECT") and pred_routing == "AUTO_ACCEPT")

    # Hallucination on missing fields: expected was non-order or missing field, but prediction extracted non-empty valid item
    is_non_order = not expected.get("is_order", True)
    hallucination = (is_non_order and len(pred_skus) > 0) or (len(exp_skus) == 0 and len(pred_skus) > 0)

    return {
        "sku_tp": sku_tp, "sku_fp": sku_fp, "sku_fn": sku_fn,
        "qty_tp": qty_tp, "qty_fp": qty_fp, "qty_fn": qty_fn,
        "unit_match": unit_match,
        "deliv_match": deliv_match,
        "is_ambiguous_expected": is_ambiguous_expected,
        "multi_item_exact": multi_item_exact,
        "routing_correct": routing_correct,
        "unsafe_auto_accept": unsafe_auto_accept,
        "hallucination": hallucination,
    }


def aggregate_metrics(case_results: list) -> dict:
    total_cases = len(case_results)
    if total_cases == 0:
        return {}

    total_sku_tp = sum(r["metrics"]["sku_tp"] for r in case_results)
    total_sku_fp = sum(r["metrics"]["sku_fp"] for r in case_results)
    total_sku_fn = sum(r["metrics"]["sku_fn"] for r in case_results)

    sku_p = total_sku_tp / (total_sku_tp + total_sku_fp) if (total_sku_tp + total_sku_fp) > 0 else 0.0
    sku_r = total_sku_tp / (total_sku_tp + total_sku_fn) if (total_sku_tp + total_sku_fn) > 0 else 0.0
    sku_f1 = 2 * sku_p * sku_r / (sku_p + sku_r) if (sku_p + sku_r) > 0 else 0.0

    total_qty_tp = sum(r["metrics"]["qty_tp"] for r in case_results)
    total_qty_fp = sum(r["metrics"]["qty_fp"] for r in case_results)
    total_qty_fn = sum(r["metrics"]["qty_fn"] for r in case_results)

    qty_p = total_qty_tp / (total_qty_tp + total_qty_fp) if (total_qty_tp + total_qty_fp) > 0 else 0.0
    qty_r = total_qty_tp / (total_qty_tp + total_qty_fn) if (total_qty_tp + total_qty_fn) > 0 else 0.0
    qty_f1 = 2 * qty_p * qty_r / (qty_p + qty_r) if (qty_p + qty_r) > 0 else 0.0

    unit_acc = sum(1 for r in case_results if r["metrics"]["unit_match"]) / total_cases

    # Delivery accuracy: resolvable vs ambiguous
    resolvable_cases = [r for r in case_results if not r["metrics"]["is_ambiguous_expected"]]
    ambiguous_cases = [r for r in case_results if r["metrics"]["is_ambiguous_expected"]]

    deliv_resolvable_acc = (sum(1 for r in resolvable_cases if r["metrics"]["deliv_match"]) / len(resolvable_cases)) if resolvable_cases else 0.0
    deliv_ambiguous_correct = (sum(1 for r in ambiguous_cases if r["metrics"]["routing_correct"]) / len(ambiguous_cases)) if ambiguous_cases else 0.0

    multi_item_cases = [r for r in case_results if len(r["expected"]["items"]) > 1]
    multi_item_acc = (sum(1 for r in multi_item_cases if r["metrics"]["multi_item_exact"]) / len(multi_item_cases)) if multi_item_cases else 0.0

    hallucinations = sum(1 for r in case_results if r["metrics"]["hallucination"])
    hallucination_rate = hallucinations / total_cases

    routing_acc = sum(1 for r in case_results if r["metrics"]["routing_correct"]) / total_cases
    unsafe_accepts = sum(1 for r in case_results if r["metrics"]["unsafe_auto_accept"])
    unsafe_accept_rate = unsafe_accepts / total_cases

    return {
        "total_cases": total_cases,
        "sku": {"precision": round(sku_p, 4), "recall": round(sku_r, 4), "f1": round(sku_f1, 4), "tp": total_sku_tp, "fp": total_sku_fp, "fn": total_sku_fn},
        "quantity": {"precision": round(qty_p, 4), "recall": round(qty_r, 4), "f1": round(qty_f1, 4), "tp": total_qty_tp, "fp": total_qty_fp, "fn": total_qty_fn},
        "unit_accuracy": round(unit_acc, 4),
        "delivery_resolvable_accuracy": round(deliv_resolvable_acc, 4),
        "delivery_ambiguous_safety_routing": round(deliv_ambiguous_correct, 4),
        "multi_item_exact_match": round(multi_item_acc, 4),
        "multi_item_case_count": len(multi_item_cases),
        "missing_field_hallucination_rate": round(hallucination_rate, 4),
        "hallucination_count": hallucinations,
        "human_review_routing_accuracy": round(routing_acc, 4),
        "unsafe_auto_accept_rate": round(unsafe_accept_rate, 4),
        "unsafe_auto_accept_count": unsafe_accepts,
    }


async def run_case_inference(mode: str, case: dict, msg: StoredMessage, endpoint_adapter: Optional[EndpointAdapter], proposal_service: Optional[ModelProposalService]) -> tuple[dict, Optional[str]]:
    if mode == "rules":
        rules = extract_explicit_fields(msg, catalog=EVAL_CATALOG)
        return extract_prediction_from_rules(rules), None

    elif mode == "qwen_only":
        if not endpoint_adapter:
            raise RuntimeError("EndpointAdapter required for qwen_only")
        req = InferenceInput(engine="qwen", messages=[{"id": "m1", "text": case["text"]}])
        out = await endpoint_adapter.infer(req)
        
        # Group by group_id if present, else pair
        groups = {}
        deliv = None
        for f in out.fields:
            if f.field == "delivery":
                deliv = {"value": f.quote, "qualifier": "EXACT"}
                continue
            gid = f.group_id or "default"
            if gid not in groups:
                groups[gid] = {"sku": None, "quantity": None, "unit": "pcs"}
            if f.field == "product":
                groups[gid]["sku"] = map_product_to_sku(f.quote)
            elif f.field == "quantity":
                # extract digits
                m_dig = re.search(r"\d+(\.\d+)?", f.quote)
                groups[gid]["quantity"] = m_dig.group(0) if m_dig else f.quote
            elif f.field == "unit":
                u_norm = UNIT_NORMALIZATION.get(f.quote.lower(), "pcs")
                groups[gid]["unit"] = u_norm

        items = [v for v in groups.values() if v.get("sku") or v.get("quantity")]
        routing = "MANUAL_REVIEW" if len(items) == 0 or deliv is None else "AUTO_ACCEPT"
        return {"items": items, "delivery": deliv, "readiness": "READY" if routing == "AUTO_ACCEPT" else "PARTIAL", "routing": routing}, None

    elif mode == "full_pipeline":
        if not proposal_service:
            raise RuntimeError("ModelProposalService required for full_pipeline")
        rules = extract_explicit_fields(msg, catalog=EVAL_CATALOG)
        proposal = await proposal_service.observe(msg, rules, reviewed=[], catalog=EVAL_CATALOG)
        # Extract items and delivery from proposal candidates/rules
        all_fields = list(proposal.rules.fields) + list(proposal.candidates)
        sku_fields = [f for f in all_fields if f.field_name == "sku" and f.validation_status in ("VALID", "PROVISIONAL", "UNRESOLVED")]
        qty_fields = [f for f in all_fields if f.field_name == "quantity" and f.validation_status in ("VALID", "PROVISIONAL", "UNRESOLVED")]
        del_fields = [f for f in all_fields if f.field_name == "requested_delivery_at" and f.validation_status in ("VALID", "PROVISIONAL", "UNRESOLVED")]
        
        items = []
        if sku_fields and qty_fields:
            items.append({"sku": sku_fields[0].value, "quantity": qty_fields[0].value, "unit": "pcs"})
        elif sku_fields:
            items.append({"sku": sku_fields[0].value, "quantity": None, "unit": "pcs"})
            
        deliv = {"value": del_fields[0].value, "qualifier": del_fields[0].qualifier} if del_fields else None
        routing = "MANUAL_REVIEW" if (proposal.manual_review_required or proposal.conflicts) else "AUTO_ACCEPT"
        return {"items": items, "delivery": deliv, "readiness": "READY" if routing == "AUTO_ACCEPT" else "PARTIAL", "routing": routing}, None

    raise ValueError(f"Unknown mode {mode}")


async def run_evaluation_async(mode: str, dataset_file: Path, output_file: Path, endpoint_url_override: Optional[str] = None):
    print(f"=== Starting PromiseFlow P1 Evaluation (Mode: {mode}) ===")
    dataset = load_dataset(dataset_file)
    base_ts = datetime.fromisoformat(dataset["base_timestamp"])
    cases = dataset["cases"]
    print(f"Loaded {len(cases)} cases from {dataset_file}")

    # Load environment credentials if present
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip("\"'")

    if endpoint_url_override:
        os.environ["P1_AI_ENDPOINT_URL"] = endpoint_url_override

    endpoint_cfg = EndpointConfig.from_env_or_none()
    endpoint_adapter = None
    proposal_service = None

    if mode in ("qwen_only", "full_pipeline"):
        if not endpoint_cfg:
            print(f"BLOCKED: Mode '{mode}' requested, but no valid EndpointConfig configured in environment.")
            return None
        print(f"Configured endpoint: {endpoint_cfg.url} (mode: {endpoint_cfg.mode})")
        
        # Test endpoint connectivity probe before batch execution
        print("Probing GPU endpoint reachability...")
        probe_adapter = EndpointAdapter(endpoint_cfg)
        probe_req = InferenceInput(engine="gliner", messages=[{"id": "probe", "text": "ping"}])
        try:
            await probe_adapter.infer(probe_req)
            print("GPU endpoint probe successful!")
        except Exception as e:
            print("\n" + "="*80)
            print(f"CRITICAL: GPU ENDPOINT PROBE FAILED: {type(e).__name__}: {e}")
            print(f"Target URL: {endpoint_cfg.url}")
            print("BLOCKED: The configured real GPU endpoint is unavailable.")
            print("Rule enforcement: Do NOT use mocked model outputs, cached predictions, fabricated metrics, or synthetic substitutes for real inference.")
            print("="*80 + "\n")
            
            # Save BLOCKED status record
            deliverable = {
                "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "status": "BLOCKED",
                "endpoint_url": endpoint_cfg.url,
                "endpoint_mode": endpoint_cfg.mode,
                "error": str(e),
                "error_type": type(e).__name__,
                "reason": "Real GPU endpoint returned connection/HTTP failure during pre-flight probe. Execution aborted per zero-fabrication evaluation policy."
            }
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(deliverable, indent=2, ensure_ascii=False), encoding="utf-8")
            return deliverable

        endpoint_adapter = EndpointAdapter(endpoint_cfg)
        if mode == "full_pipeline":
            proposal_service = ModelProposalService(endpoint=endpoint_adapter, stages=("gliner", "qwen"))

    case_results = []
    latencies = []
    errors = []

    start_time = time.time()

    for idx, c in enumerate(cases, 1):
        msg = build_stored_message(c, base_ts)
        t0 = time.time()
        print(f"[{idx}/{len(cases)}] Processing {c['id']} ({c['category']}, {c['language']})...")

        try:
            pred, err = await run_case_inference(mode, c, msg, endpoint_adapter, proposal_service)
        except Exception as e:
            dur = time.time() - t0
            latencies.append(dur)
            errors.append({"case_id": c["id"], "error": str(e)})
            print(f"Error on case {c['id']}: {e}")
            continue

        dur = time.time() - t0
        latencies.append(dur)
        metrics = evaluate_case(c, pred)
        case_results.append({
            "id": c["id"],
            "category": c["category"],
            "language": c["language"],
            "text": c["text"],
            "expected": c["expected"],
            "prediction": pred,
            "metrics": metrics,
            "latency_seconds": round(dur, 4),
            "error": err,
        })

    total_duration = time.time() - start_time
    summary_metrics = aggregate_metrics(case_results)

    # Calculate per-category breakdown
    categories = sorted(list(set(c["category"] for c in cases)))
    category_breakdown = {}
    for cat in categories:
        cat_cases = [r for r in case_results if r["category"] == cat]
        category_breakdown[cat] = aggregate_metrics(cat_cases)

    # Calculate per-language breakdown
    languages = sorted(list(set(c["language"] for c in cases)))
    language_breakdown = {}
    for lang in languages:
        lang_cases = [r for r in case_results if r["language"] == lang]
        language_breakdown[lang] = aggregate_metrics(lang_cases)

    p50_latency = sorted(latencies)[len(latencies) // 2] if latencies else 0.0
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

    eval_deliverable = {
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "COMPLETED",
        "dataset_version": dataset["version"],
        "dataset_file": str(dataset_file),
        "total_cases_evaluated": len(case_results),
        "total_wall_seconds": round(total_duration, 4),
        "latency_p50_seconds": round(p50_latency, 4),
        "latency_p95_seconds": round(p95_latency, 4),
        "failure_count": len(errors),
        "metrics_summary": summary_metrics,
        "category_breakdown": category_breakdown,
        "language_breakdown": language_breakdown,
        "case_results": case_results,
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(eval_deliverable, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Evaluation complete! Saved machine-readable results to {output_file}")
    return eval_deliverable


def run_evaluation(mode: str, dataset_file: Path, output_file: Path, endpoint_url_override: Optional[str] = None):
    return asyncio.run(run_evaluation_async(mode, dataset_file, output_file, endpoint_url_override))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["rules", "qwen_only", "full_pipeline"], default="rules")
    parser.add_argument("--dataset", type=Path, default=Path("backend/app/context/experiments/dataset_130.json"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--endpoint-url", type=str, default=None, help="Override endpoint URL without modifying .env")
    args = parser.parse_args()

    out_file = args.output or Path(f".local/eval_results_{args.mode}.json")
    run_evaluation(args.mode, args.dataset, out_file, args.endpoint_url)
