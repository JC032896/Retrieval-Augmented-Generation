"""0002 마이그레이션(documents.status) 테스트."""

import io

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from tests.fixtures.db import ALEMBIC_INI, db_engine, migrate

__all__ = ["db_engine"]

TRUNCATE = text("TRUNCATE documents, users RESTART IDENTITY CASCADE")


def _render_sql(revision_range: str, *, downgrade: bool = False) -> str:
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def test_upgrade_adds_status_with_current_default() -> None:
    sql = _render_sql("0001:0002")

    assert "ALTER TABLE documents ADD COLUMN status TEXT DEFAULT 'current' NOT NULL" in sql
    assert "status IN ('current', 'superseded')" in sql


def test_downgrade_drops_status() -> None:
    sql = _render_sql("0002:0001", downgrade=True)

    assert "DROP CONSTRAINT ck_documents_status" in sql
    assert "ALTER TABLE documents DROP COLUMN status" in sql


def test_existing_documents_become_current(db_engine: Engine) -> None:
    migrate(db_engine, "0001", downgrade=True)
    try:
        with db_engine.begin() as connection:
            connection.execute(TRUNCATE)
            connection.execute(
                text(
                    "INSERT INTO documents (title, source_path, security_level)"
                    " VALUES ('가', 'a.md', 0)"
                )
            )
        migrate(db_engine)

        with db_engine.connect() as connection:
            status = connection.scalar(text("SELECT status FROM documents"))
        assert status == "current"
    finally:
        migrate(db_engine)
        with db_engine.begin() as connection:
            connection.execute(TRUNCATE)
