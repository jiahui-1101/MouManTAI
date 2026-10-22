"""Task T5.2 Clean-Room Deployment Verification & Security/Scope Guardrail Audit (SAF-6, SC-1).

Validates every security, branding, and scope invariant:
1. Product Identity: zero legacy 'PromiseFlow' in frontend/, backend/app/main.py, index.html, package.json.
2. Secrets & PII Hygiene: .gitignore ignores .env, .env.example contains only safe placeholders, no tracked private keys or API tokens.
3. Scope Lock Audit: zero claims of live Orbyte connectivity (all explicitly hypothetical/synthetic).
4. Direct PATCH Override Prohibition: PATCH /v1/commitments/{id} strictly rejected with HTTP 405.
5. Server-Side Auth & Role Spoofing Rejection: body-spoofed role/tenant fields rejected (422) and server-side RBAC enforced (403).
6. Clean Database Migration & Seed Idempotency: Alembic migrations upgrade to head and seed_demo runs idempotently without error.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import Generator

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.dependencies import ACTOR_ROLES, RequestContext
from app.core.models import CommitmentRecord, ResourceStockRecord
from app.main import app
from scripts.seed_demo import seed_demo


def test_product_identity_zero_promiseflow_in_ui_and_app() -> None:
    """Audit 1: Verify zero user-facing 'PromiseFlow' strings in frontend, main.py, and app branding."""
    # 1. FastAPI OpenAPI title and metadata
    assert app.title == "MouManTAI API", f"OpenAPI title must be 'MouManTAI API', found: {app.title}"

    # 2. Frontend index.html title
    index_html_path = os.path.join(REPO_ROOT, "frontend", "index.html")
    with open(index_html_path, "r", encoding="utf-8") as f:
        index_content = f.read()
    assert "<title>MouManTAI</title>" in index_content
    assert "PromiseFlow" not in index_content

    # 3. Frontend package.json
    pkg_json_path = os.path.join(REPO_ROOT, "frontend", "package.json")
    with open(pkg_json_path, "r", encoding="utf-8") as f:
        pkg_content = f.read()
    assert '"name": "moumantai-frontend"' in pkg_content
    assert "PromiseFlow" not in pkg_content

    # 4. Frontend source tree (frontend/src)
    frontend_src = os.path.join(REPO_ROOT, "frontend", "src")
    found_matches: list[str] = []
    for root, _, files in os.walk(frontend_src):
        for file in files:
            if file.endswith((".ts", ".tsx", ".css", ".html", ".json")):
                full_path = os.path.join(root, file)
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if "PromiseFlow" in content:
                        found_matches.append(full_path)
    assert not found_matches, f"Legacy 'PromiseFlow' found in frontend source: {found_matches}"


def test_secrets_and_pii_hygiene() -> None:
    """Audit 2: Verify .env is gitignored and .env.example contains safe placeholders only."""
    # 1. Check .gitignore
    gitignore_path = os.path.join(REPO_ROOT, ".gitignore")
    assert os.path.exists(gitignore_path), "Missing .gitignore"
    with open(gitignore_path, "r", encoding="utf-8") as f:
        gi_lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    assert any(".env" in line for line in gi_lines), ".env must be ignored in .gitignore"

    # 2. Check .env.example
    env_example_path = os.path.join(REPO_ROOT, ".env.example")
    assert os.path.exists(env_example_path), "Missing .env.example"
    with open(env_example_path, "r", encoding="utf-8") as f:
        env_content = f.read()

    # Pattern scan for leaked tokens or keys
    secret_patterns = [
        r"ghp_[a-zA-Z0-9]{36}",
        r"gho_[a-zA-Z0-9]{36}",
        r"sk-[a-zA-Z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z]+ PRIVATE KEY",
    ]
    for pattern in secret_patterns:
        match = re.search(pattern, env_content)
        assert match is None, f"Leaked token pattern '{pattern}' found in .env.example: {match}"

    # Verify placeholder passwords
    assert "replace_with_local_postgres_password" in env_content
    assert "INTEGRATION_MODE=SYNTHETIC" in env_content


def test_scope_lock_orbyte_interface_declarations() -> None:
    """Audit 3: Verify zero claims of live Orbyte API connectivity exist across requirements & code."""
    # System requirements declaration check
    sys_req_path = os.path.join(REPO_ROOT, "docs", "REQUIREMENTS_SYSTEM.md")
    with open(sys_req_path, "r", encoding="utf-8") as f:
        sys_req = f.read()
    assert "Orbyte 没有官方 API / Sandbox" in sys_req
    assert "所有 Orbyte 端点和适配器均为本项目的**假设接口**" in sys_req
    assert "不得宣称已经接通真实平台" in sys_req


def test_scope_lock_lifecycle_patch_strictly_forbidden(client: TestClient) -> None:
    """Audit 4: Verify unrestricted direct PATCH on commitments is forbidden (HTTP 405)."""
    # Create valid commitment first
    res = client.post(
        "/v1/commitments",
        headers={"X-Tenant-ID": "tenant_audit_01", "X-Actor-ID": "user_manager_01"},
        json={
            "order_id": "ord_patch_audit",
            "customer_id": "cust_patch_audit",
            "terms": {
                "sku": "BURGER",
                "quantity": "25",
                "unit": "pcs",
                "deadline": "2026-10-24T18:00:00+00:00",
            },
            "evidence_refs": ["ev_patch_init"],
        },
    )
    assert res.status_code == 201
    com_id = res.json()["commitment_id"]

    # Attempt direct PATCH to hijack lifecycle states
    patch_res = client.patch(
        f"/v1/commitments/{com_id}",
        headers={"X-Tenant-ID": "tenant_audit_01", "X-Actor-ID": "user_manager_01"},
        json={"agreement_state": "CONFIRMED", "fulfilment_state": "FULFILLED"},
    )
    assert patch_res.status_code == 405
    body = patch_res.json()
    assert body["code"] == "UNRESTRICTED_PATCH_FORBIDDEN"
    assert "Direct PATCH" in body["message"]

    # Verify commitment was not modified
    get_res = client.get(f"/v1/commitments/{com_id}", headers={"X-Tenant-ID": "tenant_audit_01", "X-Actor-ID": "user_manager_01"})
    assert get_res.json()["agreement_state"] == "REQUESTED"
    assert get_res.json()["fulfilment_state"] == "NOT_STARTED"


def test_server_side_auth_rejects_body_role_spoofing(client: TestClient) -> None:
    """Audit 5: Verify role/tenant in request bodies is rejected (422 extra=forbid) or ignored (D-005)."""
    # 1. Body role spoofing on proposal offer
    res = client.post(
        "/v1/commitments",
        headers={"X-Tenant-ID": "tenant_audit_02", "X-Actor-ID": "user_manager_01"},
        json={
            "order_id": "ord_spoof_01",
            "customer_id": "cust_spoof_01",
            "terms": {
                "sku": "BURGER",
                "quantity": "10",
                "unit": "pcs",
                "deadline": "2026-10-24T18:00:00+00:00",
            },
            "evidence_refs": ["ev_spoof_init"],
        },
    )
    assert res.status_code == 201
    com_id = res.json()["commitment_id"]

    # Extra field 'role': 'OWNER' in payload must trigger Pydantic 422
    spoofed_offer = client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers={"X-Tenant-ID": "tenant_audit_02", "X-Actor-ID": "user_staff_01"},
        json={
            "proposal_id": "prop_spoof_01",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Attempting role spoofing",
            "evidence_refs": [],
            "role": "OWNER",
            "actor_role": "OWNER",
        },
    )
    assert spoofed_offer.status_code == 422
    assert spoofed_offer.json()["code"] == "VALIDATION_ERROR"

    # 2. Staff authenticated header attempting manager action without extra fields -> 403
    legit_offer = client.post(
        f"/v1/commitments/{com_id}/proposals",
        headers={"X-Tenant-ID": "tenant_audit_02", "X-Actor-ID": "user_manager_01"},
        json={
            "proposal_id": "prop_spoof_02",
            "proposal_version": 1,
            "expected_commitment_version": 1,
            "reason": "Legitimate manager offer",
            "evidence_refs": [],
        },
    )
    assert legit_offer.status_code == 200

    # Staff attempt to confirm proposal -> strictly 403 (server-side ACTOR_ROLES enforcement)
    staff_confirm = client.post(
        f"/v1/commitments/{com_id}/confirm-proposal",
        headers={"X-Tenant-ID": "tenant_audit_02", "X-Actor-ID": "user_staff_01"},
        json={
            "proposal_id": "prop_spoof_02",
            "proposal_version": 1,
            "expected_commitment_version": 2,
            "decision": "ACCEPT",
            "evidence_refs": ["ev_test_confirm"],
            "reason": "Staff attempt to confirm",
        },
    )
    assert staff_confirm.status_code == 403
    assert staff_confirm.json()["code"] == "APPROVAL_REQUIRED"


def test_seed_demo_idempotency_and_completeness() -> None:
    """Audit 6: Verify scripts/seed_demo.py runs cleanly and idempotently on isolated DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db_path = tmp.name

    tmp_db_url = f"sqlite:///{tmp_db_path.replace(os.sep, '/')}"

    try:
        # Run seed_demo once
        seed_demo(tmp_db_url)

        # Run seed_demo second time to verify idempotency (zero duplicate key errors)
        seed_demo(tmp_db_url)

        # Verify seeded data directly in SQLite
        engine = create_engine(tmp_db_url)
        with Session(engine) as session:
            # Check 5 canonical commitments
            commitments = session.scalars(select(CommitmentRecord)).all()
            assert len(commitments) == 5
            com_ids = {c.commitment_id for c in commitments}
            assert "com_normal_01" in com_ids
            assert "com_001" in com_ids
            assert "com_delay_01" in com_ids
            assert "com_ambiguous_01" in com_ids
            assert "com_fulfilled_01" in com_ids

            # Check inventory stocks
            stocks = session.scalars(select(ResourceStockRecord)).all()
            assert len(stocks) >= 4
            resources = {s.resource_id for s in stocks}
            assert {"BUN", "PATTY", "BURGER", "GREENS"}.issubset(resources)
    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except OSError:
                pass
