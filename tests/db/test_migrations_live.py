"""실제 Postgres에 마이그레이션을 적용해 본다 (offline SQL 검사는 test_migrations.py)."""

from sqlalchemy import Engine, inspect, text

from tests.fixtures.db import db_engine, migrate

__all__ = ["db_engine"]

TABLES = {"documents", "document_acl", "chunks", "users"}


def test_downgrade_and_upgrade_round_trip(db_engine: Engine) -> None:
    migrate(db_engine, "base", downgrade=True)
    assert TABLES.isdisjoint(inspect(db_engine).get_table_names())

    migrate(db_engine)
    assert set(inspect(db_engine).get_table_names()) >= TABLES


def test_vector_extension_is_installed(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        version = connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    assert version is not None
