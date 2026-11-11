"""0007 마이그레이션(감사 재현 컬럼)과 앱 계정이 스냅샷을 읽지 않고 upsert할 수 있는지."""

import io

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from rag_service.audit.models import APP_ROLE
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


def test_upgrade_adds_replay_columns_and_downgrade_removes_them() -> None:
    upgrade = _render_sql("0006:0007")
    downgrade = _render_sql("0007:0006", downgrade=True)

    for column in ("prompt_template_version", "model_params", "context_chunks", "request_sha256"):
        assert f"ALTER TABLE audit_log ADD COLUMN {column}" in upgrade
        assert f"ALTER TABLE audit_log DROP COLUMN {column}" in downgrade
    assert "context_chunks JSONB" in upgrade


def test_app_role_upserts_snapshots_without_read_permission(db_engine: Engine) -> None:
    """대상 없는 ON CONFLICT DO NOTHING은 INSERT 권한만으로 된다 (rag_app은 읽을 수 없다)."""
    upsert = (
        "INSERT INTO chunk_snapshots (content_sha256, content) VALUES ('h', '본문') "
        "ON CONFLICT DO NOTHING"
    )
    with db_engine.connect() as connection, connection.begin() as transaction:
        connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        connection.execute(text(upsert))
        connection.execute(text(upsert))  # 두 번째는 충돌이라 건너뛴다
        connection.execute(text("RESET ROLE"))
        count = connection.scalar(
            text("SELECT count(*) FROM chunk_snapshots WHERE content = '본문'")
        )
        transaction.rollback()

    assert count == 1
