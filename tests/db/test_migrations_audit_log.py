"""0004 마이그레이션(audit_log) 테스트."""

import io

from alembic import command
from alembic.config import Config

from tests.fixtures.db import ALEMBIC_INI


def _render_sql(revision_range: str, *, downgrade: bool = False) -> str:
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def test_upgrade_creates_audit_log_with_indexes() -> None:
    sql = _render_sql("0003:0004")

    assert "CREATE TABLE audit_log " in sql
    assert "CONSTRAINT ck_audit_log_outcome CHECK" in sql
    assert "CREATE INDEX ix_audit_log_created_at ON audit_log (created_at)" in sql
    assert "CREATE INDEX ix_audit_log_user_login ON audit_log (user_login, created_at)" in sql


def test_downgrade_drops_audit_log() -> None:
    assert "DROP TABLE audit_log" in _render_sql("0004:0003", downgrade=True)
