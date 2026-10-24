"""Real Alembic chain in a newly-created, uniquely-named disposable PG DB."""
import os
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def migrated_database(monkeypatch):
    configured=os.getenv('P1_TEST_DATABASE_URL')
    if not configured:
        pytest.skip('P1_TEST_DATABASE_URL absent; disposable migration NOT RUN')
    url=make_url(configured)
    assert url.drivername.startswith('postgresql') and url.database.endswith('_test')
    name=f'p1_migrate_{uuid4().hex}_test'
    admin=create_engine(url, isolation_level='AUTOCOMMIT', hide_parameters=True)
    child=None; created=False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created=True
        child_url=url.set(database=name)
        monkeypatch.setenv('DATABASE_URL',child_url.render_as_string(hide_password=False))
        root=Path(__file__).resolve().parents[3]
        config=Config(str(root/'alembic.ini'))
        config.set_main_option('script_location',str(root/'migrations'))
        config.set_main_option('sqlalchemy.url',child_url.render_as_string(hide_password=False).replace('%','%%'))
        command.upgrade(config,'head')
        child=create_engine(child_url,hide_parameters=True)
        yield child,config
    finally:
        if child is not None:
            child.dispose()
        if created:
            assert name.startswith('p1_migrate_') and name.endswith('_test') and name != url.database
            with admin.connect() as connection:
                connection.execute(text('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>pg_backend_pid()'),{'name':name})
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


def test_clean_chain_supports_p1_persistence_review_core_replay_and_owned_rollback(migrated_database):
    from app.context.postgres_repository import P1Base,PostgresMessageRepository
    from app.context.tests.test_deterministic_extraction import stored
    from app.context.tests.test_core_publisher import make_valid_context
    from app.context.order_context_schemas import RequestedItem,ContextReviewRequest
    from app.context.core_publisher import CoreContextPublisher
    from app.core.dependencies import RequestContext
    from app.core.models import OutboxEventRecord
    engine,config=migrated_database
    assert set(inspect(engine).get_table_names(schema='p1_dev'))=={t.name for t in P1Base.metadata.sorted_tables}
    repo=PostgresMessageRepository(engine)
    raw=stored('Need 7 pcs burgers tomorrow before 3pm').raw
    saved=repo.ingest(raw,raw.received_at).message
    processed=repo.process(raw.tenant_id,saved.message_id)
    assert repo.list_extraction_attempts(raw.tenant_id,saved.message_id)[0].fields==processed.attempt.fields
    assert repo.ingest(raw,raw.received_at).duplicate
    command.upgrade(config,'head')  # Revision tracking; no repeated table creation.
    assert repo.get(raw.tenant_id,saved.message_id).raw==raw

    context=make_valid_context(raw.tenant_id,'migration_context')
    context.requested_items=[RequestedItem(sku='BURGER',quantity='7',unit='pcs')]
    context.source_message_ids=[saved.message_id]
    context.field_evidence={f.field_name:[e.model_dump(mode='json') for e in f.evidence] for f in processed.attempt.fields if f.evidence}
    context=repo.save_order_context(context)
    reviewed=repo.apply_context_review(context.tenant_id,context.context_id,
        ContextReviewRequest(expected_context_version=1,action='EDIT_FIELD',
            field_edits={'requested_items':[{'sku':'BURGER','quantity':'8','unit':'pcs'}]}),'user_staff_01','STAFF')
    assert reviewed.context_version==2
    assert len(repo.list_context_versions(context.tenant_id,context.context_id))==2
    assert len(repo.list_context_reviews(context.tenant_id,context.context_id))==1
    publisher=CoreContextPublisher()
    request=RequestContext(context.tenant_id,'user_staff_01','STAFF','migration')
    with Session(engine) as session:
        first=publisher.publish_to_core(session,request,reviewed)
        before=session.scalar(select(func.count()).select_from(OutboxEventRecord))
        again=publisher.publish_to_core(session,request,repo.get_order_context(context.tenant_id,context.context_id))
        assert again.commitment_id==first.commitment_id
        assert session.scalar(select(func.count()).select_from(OutboxEventRecord))==before
    command.downgrade(config,'0015_p4_followup')  # This disposable database only.
    assert inspect(engine).get_table_names(schema='p1_dev')==[]
    assert 'commitments' in inspect(engine).get_table_names()
    command.upgrade(config,'head')
    assert len(inspect(engine).get_table_names(schema='p1_dev'))==8


def test_scoped_message_migration_preserves_legacy_unknown_provenance(migrated_database):
    from app.context.postgres_repository import PostgresMessageRepository

    engine, config = migrated_database
    command.downgrade(config, '0017_p1_real_channel_provenance')
    received = '2026-10-24T05:00:00+00:00'
    legacy_raw = {
        'tenant_id': 'legacy-tenant',
        'channel': 'TELEGRAM',
        'provider_message_id': 'tg_42_7',
        'sender_identity_id': '42',
        'sender_alias': 'Legacy customer',
        'received_at': received,
        'message_at': received,
        'business_timezone': None,
        'text': 'Legacy message with an unscoped reply reference',
        'attachments': [],
        'thread_ref': '42',
        'reply_to_provider_message_id': '6',
        'language': None,
        'adapter_mode': 'SYNTHETIC',
    }
    with engine.begin() as connection:
        connection.execute(text('''
            INSERT INTO p1_dev.inbound_messages (
                message_id, tenant_id, channel, provider_message_id, synthetic_provider,
                provider, raw, immutable_fingerprint, content_sha256, processing_status,
                ingested_at, updated_at
            ) VALUES (
                'legacy-row', 'legacy-tenant', 'TELEGRAM', 'tg_42_7', 'SYNTHETIC_TELEGRAM',
                'SYNTHETIC', CAST(:raw AS JSONB), :fingerprint, :digest, 'RECEIVED',
                CAST(:received AS TIMESTAMPTZ), CAST(:received AS TIMESTAMPTZ)
            )
        '''), {
            'raw': json.dumps(legacy_raw),
            'fingerprint': 'a' * 64,
            'digest': 'b' * 64,
            'received': received,
        })

    command.upgrade(config, 'head')
    repository = PostgresMessageRepository(engine)
    legacy = repository.get('legacy-tenant', 'legacy-row')

    assert legacy is not None
    assert legacy.raw.reply_to_provider_message_id == '6'
    assert legacy.raw.provider_account_id is None
    assert legacy.raw.provider_native_message_id is None
    assert legacy.raw.source_authenticity == 'UNVERIFIED'
    assert repository.resolve_exact_parent('legacy-tenant', 'legacy-row').state == 'LEGACY_UNKNOWN'


def test_scoped_delivery_collision_blocks_downgrade_without_data_loss(migrated_database):
    from app.context.postgres_repository import PostgresMessageRepository
    from app.context.tests.test_c1_completion_persistence import NOW, real_message

    engine, config = migrated_database
    repository = PostgresMessageRepository(engine)
    legacy_key = "shared-provider-message-id"
    first_raw = real_message("native-1", account="phone-a", channel="WHATSAPP").model_copy(
        update={"provider_message_id": legacy_key}
    )
    second_raw = real_message("native-2", account="phone-b", channel="WHATSAPP").model_copy(
        update={"provider_message_id": legacy_key}
    )

    first = repository.ingest(first_raw, NOW)
    second = repository.ingest(second_raw, NOW)
    assert not first.duplicate
    assert not second.duplicate

    with pytest.raises(RuntimeError, match="Cannot downgrade 0018"):
        command.downgrade(config, "0017_p1_real_channel_provenance")

    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        rows = (
            connection.execute(
                text("""
                SELECT provider_account_id, provider_native_message_id, provider_message_id,
                       source_authenticity, raw
                FROM p1_dev.inbound_messages
                WHERE tenant_id = 'tenant-a' AND provider_message_id = :legacy_key
                ORDER BY provider_account_id
            """),
                {"legacy_key": legacy_key},
            )
            .mappings()
            .all()
        )

    indexes = {
        index["name"] for index in inspect(engine).get_indexes("inbound_messages", schema="p1_dev")
    }
    assert version == "0024_merge_c1_ah"
    assert {"uq_p1_delivery_legacy", "uq_p1_delivery_scoped"} <= indexes
    assert len(rows) == 2
    assert {row["provider_account_id"] for row in rows} == {"phone-a", "phone-b"}
    assert {row["provider_native_message_id"] for row in rows} == {"native-1", "native-2"}
    assert {row["provider_message_id"] for row in rows} == {legacy_key}
    assert {row["source_authenticity"] for row in rows} == {"VERIFIED"}
    assert all(row["raw"]["provider_message_id"] == legacy_key for row in rows)


@pytest.mark.parametrize("starting_head", ["0020_merge_c1_p4", "0023_mock_memory_history"])
def test_c1_ah_merge_upgrades_either_history_and_preserves_source_rows(
    migrated_database, starting_head
):
    engine, config = migrated_database
    command.downgrade(config, "0017_p1_real_channel_provenance")
    command.upgrade(config, starting_head)
    # Both histories already contain P1's immutable source table. Insert a
    # legacy row before crossing the merge, without asserting new provenance.
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO p1_dev.inbound_messages (
                message_id, tenant_id, channel, provider_message_id,
                synthetic_provider, provider, raw, immutable_fingerprint,
                content_sha256, processing_status, ingested_at, updated_at
            ) VALUES (
                'merge-source', 'merge-tenant', 'TELEGRAM', 'merge-native',
                'SYNTHETIC_TELEGRAM', 'SYNTHETIC', '{}', :fingerprint,
                :digest, 'RECEIVED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {"fingerprint": "c" * 64, "digest": "d" * 64})
    command.upgrade(config, "head")
    expected_tables = {
        "order_requests", "p4_orders", "mock_supplier_datasets",
        "mock_forecast_datasets", "mock_optimization_datasets", "mock_memory_datasets",
    }
    assert expected_tables <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        before = connection.execute(text(
            "SELECT * FROM p1_dev.inbound_messages WHERE message_id = 'merge-source'"
        )).mappings().one()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0024_merge_c1_ah"
        )
    # Replaying the join applies neither parent's DDL again.
    command.upgrade(config, "head")
    with engine.connect() as connection:
        after = connection.execute(text(
            "SELECT * FROM p1_dev.inbound_messages WHERE message_id = 'merge-source'"
        )).mappings().one()
    assert dict(after) == dict(before)
