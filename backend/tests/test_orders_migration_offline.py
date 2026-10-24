"""SQL generation only: never opens a database connection or applies a migration."""
from io import StringIO
from pathlib import Path
from alembic import command
from alembic.config import Config


def test_orders_persistence_migration_generates_offline_sql(monkeypatch):
    backend = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://offline:unused@127.0.0.1:1/offline_only")
    output = StringIO()
    cfg = Config(str(backend / "alembic.ini"), output_buffer=output)
    cfg.set_main_option("script_location", str(backend / "migrations"))
    command.upgrade(cfg, "0018_mock_order_requests:0019_p4_orders_persistence", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE p4_orders" in sql
    assert "pk_p4_orders" in sql
    assert "0019_p4_orders_persistence" in sql
