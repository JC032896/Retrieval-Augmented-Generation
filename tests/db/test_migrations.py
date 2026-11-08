"""DB 없이 마이그레이션을 검사한다 (Alembic offline 모드로 SQL만 생성)."""

import io
from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _render_sql(revision_range: str, *, downgrade: bool = False) -> str:
    buffer = io.StringIO()
    config = Config(str(ALEMBIC_INI), output_buffer=buffer)
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return buffer.getvalue()


def test_upgrade_creates_extension_tables_and_indexes() -> None:
    sql = _render_sql("head")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    for table in ("documents", "document_acl", "chunks", "users"):
        assert f"CREATE TABLE {table} " in sql, table
    assert "embedding VECTOR(1024) NOT NULL" in sql
    assert "USING hnsw (embedding vector_cosine_ops)" in sql


def test_downgrade_drops_all_tables() -> None:
    sql = _render_sql("0001:base", downgrade=True)

    for table in ("documents", "document_acl", "chunks", "users"):
        assert f"DROP TABLE {table}" in sql, table
