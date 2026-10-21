"""Tests for Mock Resource Inventory and Concurrent Reservation Lock Primitive.

Verifies:
- SAF-4 / Invariant 8: No over-allocation under concurrent requests; P2 stays read-only, P3 acquires lock
- Read-only snapshot query does not mutate rows or bump version
- Sequential & thread-concurrent reservations prevent over-allocation (exactly one succeeds, second raises InsufficientResourceError)
- Idempotency on retry with same idempotency_key returns existing reservation without double-deduction (E2E-08, E2E-10)
- Release and consume lifecycle transitions
- REST API endpoints for resource snapshot and reservation
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import DomainError, InsufficientResourceError
from app.core.models import AuditEventRecord, ResourceReservationRecord, ResourceStockRecord
from app.core.reservations import (
    consume_reservation,
    get_available_stock,
    get_resource_snapshot,
    release_reservation,
    reserve_resource,
    seed_resource_stock,
)


def _headers(actor: str = "user_manager_01", tenant: str = "tenant_demo_01") -> dict[str, str]:
    return {
        "X-Tenant-ID": tenant,
        "X-Actor-ID": actor,
        "X-Correlation-ID": "corr_test_reservations",
    }


# =============================================================================
# 1. Read-Only Query Tests
# =============================================================================

def test_read_only_snapshot_does_not_mutate(session: Session) -> None:
    """Calling get_resource_snapshot leaves reserved_quantity and snapshot_version unchanged."""
    tenant = "tenant_test_readonly"
    stock = seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="PACKAGING",
        total_quantity=Decimal("100"),
        reserved_quantity=Decimal("20"),
        unit="pcs",
        snapshot_version=5,
    )

    initial_reserved = stock.reserved_quantity
    initial_version = stock.snapshot_version

    # Call get_resource_snapshot
    snapshots = get_resource_snapshot(session, tenant, ["PACKAGING"])
    assert len(snapshots) == 1
    snap = snapshots[0]

    assert snap.resource_id == "PACKAGING"
    assert snap.total_quantity == Decimal("100")
    assert snap.reserved_quantity == Decimal("20")
    assert snap.available == Decimal("80")
    assert snap.available_quantity == Decimal("80")
    assert snap.snapshot_version == 5
    assert snap["available"] == Decimal("80")

    # Convenience helper
    avail = get_available_stock(session, tenant, "PACKAGING")
    assert avail == Decimal("80")

    # Verify database row was NOT mutated
    session.expire_all()
    db_stock = session.scalar(
        select(ResourceStockRecord).where(
            ResourceStockRecord.tenant_id == tenant,
            ResourceStockRecord.resource_id == "PACKAGING",
        )
    )
    assert db_stock is not None
    assert db_stock.reserved_quantity == initial_reserved
    assert db_stock.snapshot_version == initial_version


# =============================================================================
# 2. Concurrency & Over-Allocation Prevention (SAF-4, Invariant 8)
# =============================================================================

def test_concurrent_reservations_prevent_overallocation(session: Session) -> None:
    """Seed PACKAGING with available = 100.

    Attempt two reservations of 60 units each sequentially:
    Assert exactly one succeeds (reserved = 60, available = 40)
    and the second fails with InsufficientResourceError (zero over-allocation, SAF-4).
    """
    tenant = "tenant_test_overallocation"
    seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="PACKAGING",
        total_quantity=Decimal("100"),
        reserved_quantity=Decimal("0"),
        unit="pcs",
    )

    # 1. First reservation of 60 units succeeds
    res1 = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_test_01",
        plan_id="plan_a",
        action_id="act_01",
        idempotency_key="idemp_first_60",
        resource_id="PACKAGING",
        quantity=Decimal("60"),
        actor_id="user_manager_01",
    )
    assert res1.reservation_id.startswith("res_")
    assert res1.quantity == Decimal("60")
    assert res1.status == "ACTIVE"

    # Verify stock after first reservation
    avail_after_first = get_available_stock(session, tenant, "PACKAGING")
    assert avail_after_first == Decimal("40")

    # 2. Second reservation of 60 units must fail deterministically with InsufficientResourceError
    with pytest.raises(InsufficientResourceError) as exc_info:
        reserve_resource(
            session,
            tenant_id=tenant,
            commitment_id="com_test_02",
            plan_id="plan_b",
            action_id="act_02",
            idempotency_key="idemp_second_60",
            resource_id="PACKAGING",
            quantity=Decimal("60"),
            actor_id="user_manager_01",
        )

    err = exc_info.value
    assert err.status_code == 409
    assert err.code == "INSUFFICIENT_RESOURCE"
    assert "available 40" in str(err)
    assert err.details["available_quantity"] == "40"
    assert err.details["requested_quantity"] == "60"

    # 3. Verify final stock state has zero over-allocation
    session.expire_all()
    final_stock = session.scalar(
        select(ResourceStockRecord).where(
            ResourceStockRecord.tenant_id == tenant,
            ResourceStockRecord.resource_id == "PACKAGING",
        )
    )
    assert final_stock is not None
    assert final_stock.total_quantity == Decimal("100")
    assert final_stock.reserved_quantity == Decimal("60")
    assert (final_stock.total_quantity - final_stock.reserved_quantity) == Decimal("40")


def test_thread_concurrent_reservations_prevent_overallocation(test_engine) -> None:
    """Concurrent multi-threaded execution attempting to reserve 60 from 100.

    Spawns two concurrent threads with independent sessions.
    Asserts exactly one succeeds and one fails with InsufficientResourceError; zero over-allocation.
    """
    tenant = "tenant_test_threads"
    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    # Seed 100 units
    init_db = session_factory()
    try:
        seed_resource_stock(
            init_db,
            tenant_id=tenant,
            resource_id="BURGER_PATTY",
            total_quantity=Decimal("100"),
            unit="pcs",
        )
    finally:
        init_db.close()

    results: list[str] = []
    errors: list[Exception] = []

    def _worker(idemp_key: str, plan_id: str) -> None:
        db = session_factory()
        try:
            res = reserve_resource(
                db,
                tenant_id=tenant,
                commitment_id="com_thread",
                plan_id=plan_id,
                action_id="act_thread",
                idempotency_key=idemp_key,
                resource_id="BURGER_PATTY",
                quantity=Decimal("60"),
                actor_id="user_manager_01",
            )
            results.append(res.reservation_id)
        except Exception as e:
            errors.append(e)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        t1 = executor.submit(_worker, "thread_key_1", "plan_thread_1")
        t2 = executor.submit(_worker, "thread_key_2", "plan_thread_2")
        t1.result()
        t2.result()

    # Exactly 1 success and 1 failure
    assert len(results) == 1, f"Expected exactly 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 error, got {len(errors)}"
    assert isinstance(errors[0], InsufficientResourceError)

    # Verify zero over-allocation in DB
    verify_db = session_factory()
    try:
        avail = get_available_stock(verify_db, tenant, "BURGER_PATTY")
        assert avail == Decimal("40")
    finally:
        verify_db.close()


# =============================================================================
# 3. Idempotency on Retry Tests (E2E-08, E2E-10)
# =============================================================================

def test_reservation_idempotency_on_retry(session: Session) -> None:
    """Retrying reserve_resource with the same idempotency_key returns the existing reservation

    and deducts 60 only once (E2E-08, E2E-10).
    """
    tenant = "tenant_test_idempotency"
    seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="PACKAGING",
        total_quantity=Decimal("100"),
        unit="pcs",
    )

    # Initial reservation
    res1 = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_idemp_01",
        plan_id="plan_idemp_1",
        action_id="act_idemp_1",
        idempotency_key="idemp_retry_key_441",
        resource_id="PACKAGING",
        quantity=Decimal("60"),
        actor_id="user_manager_01",
    )
    initial_res_id = res1.reservation_id

    # Verify stock after initial deduction
    assert get_available_stock(session, tenant, "PACKAGING") == Decimal("40")

    # Retry with identical idempotency_key
    res2 = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_idemp_01",
        plan_id="plan_idemp_1",
        action_id="act_idemp_1",
        idempotency_key="idemp_retry_key_441",
        resource_id="PACKAGING",
        quantity=Decimal("60"),
        actor_id="user_manager_01",
    )

    # Must return identical reservation
    assert res2.reservation_id == initial_res_id

    # Available stock must remain 40 (NOT double-deducted to -20 or 0!)
    assert get_available_stock(session, tenant, "PACKAGING") == Decimal("40")


# =============================================================================
# 4. Release and Consume Lifecycle Tests
# =============================================================================

def test_release_reservation_restores_stock(session: Session) -> None:
    """Releasing an active reservation restores reserved stock."""
    tenant = "tenant_test_release"
    seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="CHEESE",
        total_quantity=Decimal("50"),
        unit="kg",
    )

    res = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_rel_01",
        plan_id="plan_rel",
        action_id="act_rel",
        idempotency_key="idemp_rel_01",
        resource_id="CHEESE",
        quantity=Decimal("30"),
        actor_id="user_manager_01",
    )
    assert get_available_stock(session, tenant, "CHEESE") == Decimal("20")

    # Release reservation
    released = release_reservation(
        session,
        tenant_id=tenant,
        reservation_id=res.reservation_id,
        reason="Plan cancelled by manager",
    )
    assert released.status == "RELEASED"

    # Stock available is restored to 50
    assert get_available_stock(session, tenant, "CHEESE") == Decimal("50")

    # Audit event recorded
    audit = session.scalar(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant,
            AuditEventRecord.event_type == "resource.released",
        )
    )
    assert audit is not None
    assert audit.reason == "Plan cancelled by manager"


def test_consume_reservation_decrements_total_stock(session: Session) -> None:
    """Consuming an active reservation decrements total_quantity upon execution."""
    tenant = "tenant_test_consume"
    seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="SAUCE",
        total_quantity=Decimal("80"),
        unit="bottles",
    )

    res = reserve_resource(
        session,
        tenant_id=tenant,
        commitment_id="com_con_01",
        plan_id="plan_con",
        action_id="act_con",
        idempotency_key="idemp_con_01",
        resource_id="SAUCE",
        quantity=Decimal("30"),
        actor_id="user_manager_01",
    )

    consumed = consume_reservation(
        session,
        tenant_id=tenant,
        reservation_id=res.reservation_id,
        reason="Action executed and materials used",
    )
    assert consumed.status == "CONSUMED"

    session.expire_all()
    stock = session.scalar(
        select(ResourceStockRecord).where(
            ResourceStockRecord.tenant_id == tenant,
            ResourceStockRecord.resource_id == "SAUCE",
        )
    )
    assert stock is not None
    assert stock.total_quantity == Decimal("50")
    assert stock.reserved_quantity == Decimal("0")
    assert stock.total_quantity - stock.reserved_quantity == Decimal("50")


def test_reserve_nonexistent_resource_raises_404(session: Session) -> None:
    """Attempting to reserve an unseeded resource raises 404 RESOURCE_NOT_FOUND."""
    with pytest.raises(DomainError) as exc:
        reserve_resource(
            session,
            tenant_id="tenant_unknown",
            commitment_id="com_unk",
            plan_id="plan_unk",
            action_id="act_unk",
            idempotency_key="idemp_unk",
            resource_id="NONEXISTENT_ITEM",
            quantity=Decimal("10"),
        )
    assert exc.value.status_code == 404
    assert exc.value.code == "RESOURCE_NOT_FOUND"


# =============================================================================
# 5. REST API Endpoints Tests
# =============================================================================

def test_api_resource_snapshot_and_reserve(client: TestClient, session: Session) -> None:
    """Test REST API endpoints /v1/resources/snapshot and /v1/resources/reserve."""
    tenant = "tenant_demo_01"
    seed_resource_stock(
        session,
        tenant_id=tenant,
        resource_id="BURGER_BUN",
        total_quantity=Decimal("200"),
        unit="pcs",
    )

    # 1. GET snapshot
    get_res = client.get("/v1/resources/snapshot?resource_id=BURGER_BUN", headers=_headers())
    assert get_res.status_code == 200
    stocks = get_res.json()
    assert len(stocks) == 1
    assert stocks[0]["resource_id"] == "BURGER_BUN"
    assert stocks[0]["available_quantity"] == "200.0000"

    # 2. POST reserve 80 units
    reserve_res = client.post(
        "/v1/resources/reserve",
        headers=_headers(),
        json={
            "commitment_id": "com_api_01",
            "plan_id": "plan_api_1",
            "action_id": "act_api_1",
            "idempotency_key": "idemp_api_01",
            "resource_id": "BURGER_BUN",
            "quantity": "80",
        },
    )
    assert reserve_res.status_code == 201
    body = reserve_res.json()
    assert body["status"] == "ACTIVE"
    assert Decimal(body["quantity"]) == Decimal("80")

    # 3. GET snapshot confirms 120 available
    get_res2 = client.get("/v1/resources/snapshot?resource_id=BURGER_BUN", headers=_headers())
    assert get_res2.status_code == 200
    assert Decimal(get_res2.json()[0]["available_quantity"]) == Decimal("120")

    # 4. POST reserve 150 units fails with 409 Conflict (INSUFFICIENT_RESOURCE)
    excess_res = client.post(
        "/v1/resources/reserve",
        headers=_headers(),
        json={
            "commitment_id": "com_api_02",
            "plan_id": "plan_api_2",
            "action_id": "act_api_2",
            "idempotency_key": "idemp_api_02",
            "resource_id": "BURGER_BUN",
            "quantity": "150",
        },
    )
    assert excess_res.status_code == 409
    assert excess_res.json()["code"] == "INSUFFICIENT_RESOURCE"
