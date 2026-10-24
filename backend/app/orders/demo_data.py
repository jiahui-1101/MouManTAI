"""Versioned shared synthetic requests. No DB writes or inferred business decisions."""
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class DemoContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemoItem(DemoContract):
    sku: str = Field(min_length=1)
    quantity: str = Field(pattern=r"^[1-9][0-9]*$")
    unit: str = Field(min_length=1)


class DemoOrder(DemoContract):
    order_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    customer_display_name: str = Field(min_length=1)
    requested_items: tuple[DemoItem, ...] = Field(min_length=1)
    requested_delivery_at: AwareDatetime
    received_at: AwareDatetime
    lifecycle_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_channel: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class DemoDataset(DemoContract):
    schema_version: Literal["orders-demo-v1"]
    tenant_id: Literal["tenant_demo_01"]
    integration_mode: Literal["SYNTHETIC"]
    evidence_tier: Literal["DEMO-ONLY"]
    source: str
    source_at: AwareDatetime
    coverage: Literal["partial"]
    orders: tuple[DemoOrder, ...]

    @model_validator(mode="after")
    def unique_identities(self):
        for key in ("order_id", "commitment_id"):
            values = [getattr(row, key) for row in self.orders]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {key}")
        return self


def load_demo_dataset() -> DemoDataset:
    return DemoDataset.model_validate_json(
        Path(__file__).with_name("fixtures").joinpath("orders_demo_v1.json").read_text(encoding="utf-8")
    )
