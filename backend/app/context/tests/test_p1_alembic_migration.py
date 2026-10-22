"""Real Alembic chain in a newly-created, uniquely-named disposable PG DB."""
import os
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
    command.downgrade(config,'0011_p4_confirmations')  # This disposable database only.
    assert inspect(engine).get_table_names(schema='p1_dev')==[]
    assert 'commitments' in inspect(engine).get_table_names()
    command.upgrade(config,'head')
    assert len(inspect(engine).get_table_names(schema='p1_dev'))==8
