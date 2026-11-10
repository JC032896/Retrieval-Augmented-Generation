"""0003 마이그레이션(users.login) 테스트."""

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


def test_upgrade_adds_unique_not_null_login() -> None:
    sql = _render_sql("0002:0003")

    assert "ALTER TABLE users ADD COLUMN login TEXT" in sql
    assert "ALTER COLUMN login SET NOT NULL" in sql
    assert "ADD CONSTRAINT uq_users_login UNIQUE (login)" in sql


def test_downgrade_drops_login() -> None:
    sql = _render_sql("0003:0002", downgrade=True)

    assert "DROP CONSTRAINT uq_users_login" in sql
    assert "ALTER TABLE users DROP COLUMN login" in sql


def test_existing_users_get_a_placeholder_login(db_engine: Engine) -> None:
    migrate(db_engine, "0002", downgrade=True)
    try:
        with db_engine.begin() as connection:
            connection.execute(TRUNCATE)
            connection.execute(
                text(
                    "INSERT INTO users (name, department, role, clearance_level)"
                    " VALUES ('가', '개발팀', '사원', 1)"
                )
            )
        migrate(db_engine)

        with db_engine.connect() as connection:
            login = connection.scalar(text("SELECT login FROM users"))
        assert login == "legacy-1"
    finally:
        migrate(db_engine)
        with db_engine.begin() as connection:
            connection.execute(TRUNCATE)
