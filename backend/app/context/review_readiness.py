"""Recompute structural gaps after human review; client flags are not authority."""
from .review_catalog import review_item_errors
from .order_context_schemas import RequestedItem


def reviewed_missing_fields(record, edited_fields, catalog):
    missing = set(record.missing_fields or [])
    items = [RequestedItem.model_validate(i) for i in record.requested_items or []]
    valid_items = bool(items) and not review_item_errors(record.tenant_id, items, catalog)
    if 'requested_items' in edited_fields and valid_items:
        # Every item with source evidence needs a row; do not erase unknown lines
        # just because the reviewer mapped the first product.
        latest = record.source_message_ids[-1] if record.source_message_ids else None
        groups = set()
        for ev in (record.field_evidence or {}).get('sku', []):
            metadata = ev.get('normalization_metadata') or {}
            if isinstance(metadata, dict) and metadata.get('group_id') and ev.get('quote'):
                if not latest or ev.get('message_id') in (None, latest):
                    groups.add(metadata['group_id'])
        if len(items) >= len(groups):
            missing.difference_update({'requested_items', 'sku', 'quantity', 'unit', 'sku_mapping'})
        else:
            missing.add('sku_mapping')
    if not items:
        missing.add('requested_items')
    elif not valid_items:
        missing.add('sku_mapping')
    delivery = record.requested_delivery_at
    if delivery is None or delivery.tzinfo is None or delivery.utcoffset() is None:
        missing.add('requested_delivery_at')
    elif 'requested_delivery_at' in edited_fields or 'delivery_qualifier' in edited_fields:
        missing.discard('requested_delivery_at')
    if not record.customer_id or record.customer_identity_status != 'LINK_VERIFIED':
        missing.add('customer_identity')
    else:
        missing.discard('customer_identity')
    return sorted(missing)
