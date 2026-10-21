"""Customer and Order Directory interface for P1 identity association.

Note on Integration:
Reuses approved customer/order interfaces. Because P5 does not currently provide
a standalone customer master directory API in Core, this module provides a
strictly typed SyntheticCustomerDirectory behind a replaceable interface.
Shared Core integration for Customer Directory is recorded as: INCOMPLETE (provisional synthetic adapter).
"""

from __future__ import annotations

from typing import Protocol

from .association_schemas import CustomerAccount, OrderReference


class CustomerDirectory(Protocol):
    def get_customer(self, tenant_id: str, customer_id: str) -> CustomerAccount | None: ...
    def find_by_sender(self, tenant_id: str, channel: str, sender_identity_id: str) -> CustomerAccount | None: ...
    def get_order(self, tenant_id: str, order_id: str) -> OrderReference | None: ...
    def list_customer_orders(self, tenant_id: str, customer_id: str) -> list[OrderReference]: ...


class SyntheticCustomerDirectory:
    """Provisional synthetic directory for development and evaluation."""

    def __init__(self) -> None:
        self._customers: dict[tuple[str, str], CustomerAccount] = {
            ("synthetic_tenant_a", "cust_bk"): CustomerAccount(
                customer_id="cust_bk",
                tenant_id="synthetic_tenant_a",
                legal_name="Burger King MY Sdn Bhd",
                display_name="Burger King",
                active=True,
                verified_channels=["+60123456789"],
            ),
            ("synthetic_tenant_a", "cust_mcd"): CustomerAccount(
                customer_id="cust_mcd",
                tenant_id="synthetic_tenant_a",
                legal_name="Golden Arches Enterprise",
                display_name="McDonalds MY",
                active=True,
                verified_channels=["+60198765432"],
            ),
            ("synthetic_tenant_a", "cust_subway"): CustomerAccount(
                customer_id="cust_subway",
                tenant_id="synthetic_tenant_a",
                legal_name="Sub Fast Food Sdn Bhd",
                display_name="Subway",
                active=True,
                verified_channels=["+60111222333"],
            ),
            ("synthetic_tenant_b", "cust_other"): CustomerAccount(
                customer_id="cust_other",
                tenant_id="synthetic_tenant_b",
                legal_name="Other Tenant Customer Ltd",
                display_name="Other Tenant Co",
                active=True,
                verified_channels=["+60155555555"],
            ),
        }

        self._orders: dict[tuple[str, str], OrderReference] = {
            ("synthetic_tenant_a", "ORD-1001"): OrderReference(
                order_id="ORD-1001",
                customer_id="cust_bk",
                tenant_id="synthetic_tenant_a",
                status="ACTIVE",
                description="Weekly recurring patties",
            ),
            ("synthetic_tenant_a", "ORD-1002"): OrderReference(
                order_id="ORD-1002",
                customer_id="cust_bk",
                tenant_id="synthetic_tenant_a",
                status="CONFIRMED",
                description="Emergency buns delivery",
            ),
            ("synthetic_tenant_a", "ORD-2001"): OrderReference(
                order_id="ORD-2001",
                customer_id="cust_mcd",
                tenant_id="synthetic_tenant_a",
                status="ACTIVE",
                description="Quarterly standard lot",
            ),
            ("synthetic_tenant_b", "ORD-9001"): OrderReference(
                order_id="ORD-9001",
                customer_id="cust_other",
                tenant_id="synthetic_tenant_b",
                status="ACTIVE",
                description="Cross-tenant isolated order",
            ),
        }

    def get_customer(self, tenant_id: str, customer_id: str) -> CustomerAccount | None:
        return self._customers.get((tenant_id, customer_id))

    def find_by_sender(self, tenant_id: str, channel: str, sender_identity_id: str) -> CustomerAccount | None:
        for (t_id, _), customer in self._customers.items():
            if t_id == tenant_id and sender_identity_id in customer.verified_channels:
                return customer
        return None

    def get_order(self, tenant_id: str, order_id: str) -> OrderReference | None:
        return self._orders.get((tenant_id, order_id))

    def list_customer_orders(self, tenant_id: str, customer_id: str) -> list[OrderReference]:
        return [
            order
            for (t_id, _), order in self._orders.items()
            if t_id == tenant_id and order.customer_id == customer_id
        ]


DEFAULT_DIRECTORY = SyntheticCustomerDirectory()
