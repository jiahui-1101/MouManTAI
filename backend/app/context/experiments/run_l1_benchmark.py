"""Evaluation runner for L1 GLiNER candidate extraction across English, Chinese, Malay, and Code-switched messages.

Can run against:
1. Google Colab CPU worker (via tunnel URL)
2. RunPod GPU worker (via RunPod URL)
3. Direct HTTP worker (localhost:8000 or custom host)

Usage:
    python run_l1_benchmark.py --endpoint https://<worker-url>/infer --api-key <secret>
Or set environment variables:
    P1_AI_ENDPOINT_URL=https://<worker-url>/infer
    P1_AI_API_KEY=<secret>
    P1_AI_ENDPOINT_MODE=direct
    python run_l1_benchmark.py
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

# Ensure backend is on sys.path
backend_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import ProductAlias
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import RawMessageEnvelope

BENCHMARK_CATALOG = (
    ProductAlias(
        "synthetic_tenant_a",
        "BURGER",
        ("burger", "burgers", "beef burger", "beef burgers", "chicken burger", "chicken burgers", "汉堡", "汉堡包", "牛肉汉堡", "roti burger"),
        "pcs",
    ),
    ProductAlias(
        "synthetic_tenant_a",
        "BREAD",
        ("bread", "buns", "bun", "bun burger", "roti", "面包"),
        "pcs",
    ),
)


def load_l1_cases():
    data_path = Path(__file__).parent / "benchmark_l1_cases.json"
    return json.loads(data_path.read_text(encoding="utf-8"))


async def evaluate_l1(endpoint_url: str, api_key: str, mode: str = "direct"):
    data = load_l1_cases()
    base_ts = datetime.fromisoformat(data["base_timestamp"])
    cases = data["cases"]

    config = EndpointConfig(url=endpoint_url, api_key=api_key, mode=mode, timeout_seconds=120)
    endpoint = EndpointAdapter(config)
    service = ModelProposalService(endpoint=endpoint, enabled=True, stages=("gliner",))

    field_counts = {
        "product": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
        "quantity": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
        "unit": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
        "delivery": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
    }

    sku_resolution = {"correct": 0, "unknown_rejected": 0, "false_accept": 0, "missed": 0}
    lang_stats = {}
    failures = []
    latencies = []

    print(f"Running L1 benchmark across {len(cases)} cases against endpoint: {endpoint_url} (mode: {mode})...\n")

    for i, c in enumerate(cases, start=1):
        case_id = c["id"]
        text = c["text"]
        lang = c["language"]
        exp_entities = c.get("expected_entities", {})
        exp_sku = c.get("expected_sku")
        is_order = c.get("is_order", True)

        lang_stats.setdefault(lang, {"total": 0, "passed": 0})
        lang_stats[lang]["total"] += 1

        raw = RawMessageEnvelope(
            tenant_id="synthetic_tenant_a",
            channel="WHATSAPP",
            adapter_mode="SYNTHETIC",
            provider_message_id=f"msg_{case_id}",
            sender_identity_id="+60123456789",
            sender_alias="L1 Benchmark User",
            received_at=base_ts,
            message_at=base_ts,
            text=text,
            business_timezone="Asia/Kuala_Lumpur",
            attachments=[],
        )
        import hashlib
        stored_msg = StoredMessage(
            message_id=f"stored_{case_id}",
            raw=raw,
            synthetic_provider="SYNTHETIC_WHATSAPP",
            processing_status="RECEIVED",
            content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ingested_at=base_ts,
            updated_at=base_ts,
        )

        try:
            start_t = datetime.now(timezone.utc)
            proposal = await service.extract_stored(stored_msg, catalog=BENCHMARK_CATALOG)
            dur = (datetime.now(timezone.utc) - start_t).total_seconds()
            latencies.append(dur)
        except Exception as exc:
            failures.append({"case_id": case_id, "error": f"Extraction exception: {exc}", "text": text})
            continue

        # Extract observations from both rules (L0) and model proposals (L1)
        obs_by_field = {}
        # Include L0 rule-extracted fields that are valid
        for rf in proposal.rules.fields:
            if rf.validation_status == "VALID" and rf.value is not None:
                fname = {
                    "sku": "product",
                    "quantity": "quantity",
                    "unit": "unit",
                    "requested_delivery_at": "delivery",
                    "order_id": "order_reference",
                }.get(rf.field_name, rf.field_name)
                quote = rf.evidence[0].quote if rf.evidence else str(rf.value)
                obs_by_field.setdefault(fname, []).append({
                    "value": rf.value,
                    "quote": quote,
                    "source": "L0_RULE",
                    "disposition": "accepted",
                    "domain_supported": "true",
                })

        # Include L1 GLiNER candidates
        for cand in proposal.candidates:
            if cand.metadata.get("disposition") == "rejected":
                continue
            fname = {
                "sku": "product",
                "quantity": "quantity",
                "unit": "unit",
                "requested_delivery_at": "delivery",
                "order_id": "order_reference",
            }.get(cand.field_name, cand.field_name)
            quote = cand.evidence[0].quote if cand.evidence else cand.value
            obs_by_field.setdefault(fname, []).append({
                "value": cand.value,
                "quote": quote,
                "source": "L1_GLINER",
                "disposition": cand.metadata.get("disposition"),
                "domain_supported": cand.metadata.get("domain_supported"),
            })

        case_passed = True

        # Field-level Precision / Recall
        for field in ("product", "quantity", "unit", "delivery"):
            exp_val = exp_entities.get(field)
            actual_list = obs_by_field.get(field, [])

            if exp_val:
                # Expected entity present
                matched = any(exp_val.lower() in a["quote"].lower() or a["quote"].lower() in exp_val.lower() for a in actual_list)
                if matched:
                    field_counts[field]["tp"] += 1
                else:
                    field_counts[field]["fn"] += 1
                    case_passed = False
                    failures.append({
                        "case_id": case_id,
                        "field": field,
                        "expected": exp_val,
                        "actual": [a["quote"] for a in actual_list] or "NONE",
                        "text": text,
                    })
            else:
                # No entity expected
                if not actual_list:
                    field_counts[field]["tn"] += 1
                else:
                    field_counts[field]["fp"] += 1
                    # Only mark as failure if it was a non-order message incorrectly extracting
                    if not is_order:
                        case_passed = False
                        failures.append({
                            "case_id": case_id,
                            "field": field,
                            "expected": "NONE (non-order)",
                            "actual": [a["quote"] for a in actual_list],
                            "text": text,
                        })

        # SKU Resolution & Catalog Boundary check
        product_cands = obs_by_field.get("product", [])
        if exp_sku:
            supported = [c for c in product_cands if c.get("domain_supported") == "true" and c["value"] == exp_sku]
            if supported:
                sku_resolution["correct"] += 1
            else:
                sku_resolution["missed"] += 1
        else:
            # Unknown product or non-order: must NOT resolve as a supported catalog SKU
            false_supported = [c for c in product_cands if c.get("domain_supported") == "true"]
            if false_supported:
                sku_resolution["false_accept"] += 1
                case_passed = False
                failures.append({
                    "case_id": case_id,
                    "reason": f"False acceptance: unknown product accepted as {false_supported[0]['value']}",
                    "text": text,
                })
            else:
                sku_resolution["unknown_rejected"] += 1

        if case_passed:
            lang_stats[lang]["passed"] += 1

        print(f"[{i:02d}/{len(cases):02d}] {case_id} ({lang}): {'PASS' if case_passed else 'FAIL'} ({dur:.2f}s)")

    # Metrics calculation
    metrics = {}
    for f, cnt in field_counts.items():
        tp, fp, fn = cnt["tp"], cnt["fp"], cnt["fn"]
        prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 1.0
        metrics[f] = {
            "precision": round(prec * 100, 1),
            "recall": round(rec * 100, 1),
            "f1": round(f1 * 100, 1),
            "tp": tp, "fp": fp, "fn": fn, "tn": cnt["tn"],
        }

    report = {
        "benchmark": "benchmark-l1-multilingual-v1",
        "total_cases": len(cases),
        "endpoint": endpoint_url,
        "mode": mode,
        "sku_resolution": sku_resolution,
        "field_metrics": metrics,
        "language_breakdown": {
            lang: {
                "total": s["total"],
                "passed": s["passed"],
                "accuracy": round(s["passed"] / s["total"] * 100, 1) if s["total"] > 0 else 0.0,
            }
            for lang, s in lang_stats.items()
        },
        "latency_seconds": {
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "min": round(min(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "failures_count": len(failures),
        "failures": failures,
    }

    print("\n" + "=" * 60)
    print("L1 BENCHMARK REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="L1 GLiNER Multilingual Benchmark Runner")
    parser.add_argument("--endpoint", default=os.environ.get("P1_AI_ENDPOINT_URL"), help="Inference endpoint URL")
    parser.add_argument("--api-key", default=os.environ.get("P1_AI_API_KEY"), help="API authentication key")
    parser.add_argument("--mode", default=os.environ.get("P1_AI_ENDPOINT_MODE", "direct"), help="Endpoint mode (direct or runpod)")

    args = parser.parse_args()

    if not args.endpoint or not args.api_key:
        print("ERROR: Inference endpoint URL and API key required.")
        print("Either pass --endpoint and --api-key arguments, or set environment variables:")
        print("    export P1_AI_ENDPOINT_URL=https://<tunnel-or-runpod-url>/infer")
        print("    export P1_AI_API_KEY=<secret>")
        print("    export P1_AI_ENDPOINT_MODE=direct")
        sys.exit(1)

    asyncio.run(evaluate_l1(args.endpoint, args.api_key, args.mode))


if __name__ == "__main__":
    main()
