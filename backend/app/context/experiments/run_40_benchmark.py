"""Evaluation runner for the 40-case multilingual extraction benchmark."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Add backend directory to sys.path if not present
backend_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.context.deterministic_extraction import extract_explicit_fields, PROVISIONAL_PRODUCTS, ProductAlias
from app.context.schemas import RawMessageEnvelope
from app.context.ingestion_schemas import StoredMessage

BENCHMARK_CATALOG = (
    ProductAlias("synthetic_tenant_a", "BURGER", ("burger", "burgers", "beef burger", "beef burgers", "chicken burger", "chicken burgers", "汉堡", "汉堡包", "roti burger"), "pcs"),
    ProductAlias("synthetic_tenant_a", "BREAD", ("bread", "buns", "bun", "面包"), "pcs"),
)


def load_cases():
    data_path = Path(__file__).parent / "benchmark_40_cases.json"
    return json.loads(data_path.read_text(encoding="utf-8"))


def evaluate_benchmark():
    data = load_cases()
    base_ts = datetime.fromisoformat(data["base_timestamp"])
    cases = data["cases"]
    
    total_cases = len(cases)
    field_counts = {"sku": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
                    "quantity": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
                    "requested_delivery_at": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
                    "unit": {"tp": 0, "fp": 0, "fn": 0, "tn": 0}}
    
    false_acceptances = []
    routing_stats = {"l0_sufficient": 0, "needs_ai": 0}
    failures = []

    for c in cases:
        case_id = c["id"]
        text = c["text"]
        lang = c["language"]
        expected = c.get("expected", {})

        raw = RawMessageEnvelope(
            tenant_id="synthetic_tenant_a",
            channel="WHATSAPP",
            adapter_mode="SYNTHETIC",
            provider_message_id=f"msg_{case_id}",
            sender_identity_id="+60123456789",
            sender_alias="Benchmark User",
            received_at=base_ts,
            message_at=base_ts,
            text=text,
            business_timezone="Asia/Kuala_Lumpur",
            attachments=[],
        )
        stored_msg = StoredMessage(
            message_id=f"stored_{case_id}",
            raw=raw,
            synthetic_provider="SYNTHETIC_WHATSAPP",
            processing_status="RECEIVED",
            content_sha256="abc",
            ingested_at=base_ts,
            updated_at=base_ts,
        )

        res = extract_explicit_fields(stored_msg, catalog=BENCHMARK_CATALOG)
        extracted = {}
        for f in res.fields:
            extracted[f.field_name] = f

        # Routing decision: True if L0 has missing/unresolved sku or quantity
        needs_ai = any(f.field_name in {"sku", "quantity"} and f.validation_status != "VALID" for f in res.fields)
        if needs_ai:
            routing_stats["needs_ai"] += 1
        else:
            routing_stats["l0_sufficient"] += 1

        # Check each field in expected
        for fname, exp_spec in expected.items():
            ext = extracted.get(fname)
            actual_status = ext.validation_status if ext else "MISSING"
            actual_val = ext.value if ext else None
            actual_qual = ext.qualifier if ext else None

            exp_status = exp_spec.get("status")
            exp_val = exp_spec.get("value")
            exp_qual = exp_spec.get("qualifier")

            # Check false acceptance (e.g. expected UNRESOLVED/MISSING but got VALID)
            if exp_status in ("UNRESOLVED", "MISSING", "INVALID") and actual_status == "VALID":
                false_acceptances.append({
                    "case_id": case_id,
                    "field": fname,
                    "reason": f"Expected {exp_status} but got VALID '{actual_val}'",
                    "text": text,
                })

            # Check precision & recall on VALID fields
            if exp_status == "VALID":
                if actual_status == "VALID" and (exp_val is None or actual_val == exp_val) and (exp_qual is None or actual_qual == exp_qual):
                    field_counts.setdefault(fname, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})["tp"] += 1
                else:
                    field_counts.setdefault(fname, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})["fn"] += 1
                    failures.append({
                        "case_id": case_id,
                        "field": fname,
                        "expected": f"VALID {exp_val} ({exp_qual})",
                        "actual": f"{actual_status} {actual_val} ({actual_qual})",
                        "text": text,
                    })
            else:
                # Expected UNRESOLVED or MISSING
                if actual_status == exp_status:
                    field_counts.setdefault(fname, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})["tn"] += 1
                else:
                    if actual_status == "VALID":
                        field_counts.setdefault(fname, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})["fp"] += 1
                    failures.append({
                        "case_id": case_id,
                        "field": fname,
                        "expected": f"{exp_status}",
                        "actual": f"{actual_status} {actual_val}",
                        "text": text,
                    })

    # Calculate metrics
    metrics = {}
    for fname, cnt in field_counts.items():
        tp = cnt["tp"]
        fp = cnt["fp"]
        fn = cnt["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 1.0
        metrics[fname] = {
            "precision": round(precision * 100, 1),
            "recall": round(recall * 100, 1),
            "f1": round(f1 * 100, 1),
            "tp": tp, "fp": fp, "fn": fn, "tn": cnt["tn"],
        }

    report = {
        "benchmark_cases": total_cases,
        "routing": routing_stats,
        "false_acceptance_count": len(false_acceptances),
        "false_acceptances": false_acceptances,
        "metrics": metrics,
        "failures_count": len(failures),
        "failures": failures,
    }

    # Print with ensure_ascii=True to avoid Windows terminal cp1252 encoding errors
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    evaluate_benchmark()
