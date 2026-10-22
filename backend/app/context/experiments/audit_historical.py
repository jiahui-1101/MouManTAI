"""Read-only current-tenant Inbox evidence inventory, never reprocess/publish.

Differences from current rules are review findings, not automatic gold labels.
Historical call necessity is unknown without historical routing/config evidence.
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.postgres_repository import (
    InboundMessage, ExtractionAttempt, OrderContext, ContextReview, OrderContextVersion, stored,
)


def audit(engine, tenant_id):
    with engine.connect() as connection, connection.begin():
        connection.execute(text('SET TRANSACTION READ ONLY'))
        with Session(bind=connection) as session:
            messages = session.scalars(select(InboundMessage).where(InboundMessage.tenant_id == tenant_id)).all()
            attempts = session.scalars(select(ExtractionAttempt).where(ExtractionAttempt.tenant_id == tenant_id)).all()
            contexts = session.scalars(select(OrderContext).where(OrderContext.tenant_id == tenant_id)).all()
            rows = []
            for row in messages:
                message = stored(row)
                current = extract_explicit_fields(message, catalog=PROVISIONAL_PRODUCTS)
                history = sorted((a for a in attempts if a.message_id == row.message_id), key=lambda a: a.started_at)
                latest = history[-1] if history else None
                old_valid = {(f['field_name'], f.get('value')) for f in latest.fields
                             if f.get('validation_status') == 'VALID'} if latest else set()
                new_valid = {(f.field_name, f.value) for f in current.fields if f.validation_status == 'VALID'}
                unresolved = [f.field_name for f in current.fields if f.validation_status != 'VALID']
                associated = [c for c in contexts if row.message_id in c.source_message_ids]
                diagnostics = []
                for attempt in history:
                    try:
                        diagnostic = json.loads(attempt.diagnostic or '{}')
                    except (ValueError, TypeError):
                        diagnostic = {'unparseable': True}
                    diagnostics.append({'attempt_id': attempt.attempt_id, 'version': attempt.extractor_version,
                                        'diagnostic': diagnostic})
                rows.append({'message': message.model_dump(mode='json'),
                    'current_l0': current.model_dump(mode='json'), 'historical_attempts': diagnostics,
                    'latest_stored_fields': latest.fields if latest else [],
                    'valid_pairs_changed': latest is not None and old_valid != new_valid,
                    'unresolved_current_fields': unresolved,
                    'contexts': [{'context_id': c.context_id, 'version': c.context_version,
                        'status': c.status, 'identity': c.customer_identity_status,
                        'items': c.requested_items, 'missing_fields': c.missing_fields,
                        'conflicts': c.conflicts} for c in associated],
                    'historical_call_necessity': 'UNVERIFIED: current rules are not the historical configuration',
                    'semantic_verdict': 'MANUAL_REVIEW_REQUIRED: no independently labelled historical gold'})
            counts = {}
            for model, name in ((ContextReview, 'reviews'), (OrderContextVersion, 'context_versions')):
                counts[name] = len(session.scalars(select(model).where(model.tenant_id == tenant_id)).all())
            return {'tenant_id': tenant_id, 'read_only_transaction': True, 'model_calls': 0,
                'accessible_messages': len(messages), 'audited_records': len(rows),
                'changed_valid_pairs': sum(r['valid_pairs_changed'] for r in rows),
                'unresolved_current_messages': sum(bool(r['unresolved_current_fields']) for r in rows),
                'semantic_accuracy': 'UNVERIFIED', 'contexts': len(contexts), **counts, 'messages': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite audit evidence')
    from app.context import dev_app  # existing private env; no server startup
    from app.context.dependencies import development_context
    from app.context.dev_database import create_p1_engine
    engine = create_p1_engine()
    try:
        result = audit(engine, development_context().tenant_id)
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('messages', 'tenant_id')}))


if __name__ == '__main__':
    main()
