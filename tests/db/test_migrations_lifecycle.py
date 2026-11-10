"""0005 마이그레이션(수명 관리 컬럼, chunk_snapshots, DB 역할) 테스트."""

import io

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from rag_service.audit.models import APP_ROLE, AUDITOR_ROLE
from tests.fixtures.db import ALEMBIC_INI, db_engine

__all__ = ["db_engine"]


def _render_sql(revision_range: str, *, downgrade: bool = False) -> str:
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def test_upgrade_adds_lifecycle_columns_snapshots_and_grants() -> None:
    sql = _render_sql("0004:0005")

    for column in ("content_sha256", "source_mtime", "embedding_model", "effective_from"):
        assert f"ALTER TABLE documents ADD COLUMN {column}" in sql
    assert "ALTER TABLE chunks ADD COLUMN chunk_key TEXT" in sql
    assert "ADD CONSTRAINT uq_chunks_document_key UNIQUE (document_id, chunk_key)" in sql
    assert "CREATE TABLE chunk_snapshots" in sql
    assert f"GRANT INSERT ON audit_log, chunk_snapshots TO {APP_ROLE}" in sql
    assert f"GRANT SELECT ON audit_log, chunk_snapshots TO {AUDITOR_ROLE}" in sql


def test_downgrade_removes_them() -> None:
    sql = _render_sql("0005:0004", downgrade=True)

    assert "DROP TABLE chunk_snapshots" in sql
    assert "ALTER TABLE chunks DROP COLUMN chunk_key" in sql
    assert "ALTER TABLE documents DROP COLUMN effective_to" in sql


def _run_as(engine: Engine, role: str, statement: str) -> None:
    """role 권한으로 문장을 실행하고 되돌린다 (테스트 DB 계정은 SET ROLE을 할 수 있는 관리자)."""
    with engine.connect() as connection, connection.begin() as transaction:
        connection.execute(text(f"SET LOCAL ROLE {role}"))
        connection.execute(text(statement))
        transaction.rollback()


INSERT_SNAPSHOT = "INSERT INTO chunk_snapshots (content_sha256, content) VALUES ('x', '본문')"


def test_app_role_writes_snapshots_but_cannot_read_them(db_engine: Engine) -> None:
    _run_as(db_engine, APP_ROLE, INSERT_SNAPSHOT)
    _run_as(db_engine, APP_ROLE, "SELECT count(*) FROM documents")

    for table in ("chunk_snapshots", "audit_log"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            _run_as(db_engine, APP_ROLE, f"SELECT count(*) FROM {table}")


def test_auditor_role_reads_snapshots_but_cannot_write_them(db_engine: Engine) -> None:
    _run_as(db_engine, AUDITOR_ROLE, "SELECT count(*) FROM chunk_snapshots")
    _run_as(db_engine, AUDITOR_ROLE, "SELECT count(*) FROM audit_log")

    with pytest.raises(ProgrammingError, match="permission denied"):
        _run_as(db_engine, AUDITOR_ROLE, INSERT_SNAPSHOT)
    with pytest.raises(ProgrammingError, match="permission denied"):
        _run_as(db_engine, AUDITOR_ROLE, "SELECT count(*) FROM documents")
