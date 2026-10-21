"""Read-only fixture loader. No authentication, DB, deduplication or writes."""

from pathlib import Path

from .fixture_models import FixtureCatalog, InboxPreview


def load_catalog() -> FixtureCatalog:
    return FixtureCatalog.model_validate_json(Path(__file__).with_name("fixtures").joinpath("scenarios.json").read_text(encoding="utf-8"))


def load_preview() -> InboxPreview:
    catalog = load_catalog()
    return InboxPreview(mode=catalog.mode, business_timezone=catalog.business_timezone,
                        records=[r for r in catalog.records if r.message.raw.tenant_id == "synthetic_tenant_a"])
