"""0008 마이그레이션: 앱 계정은 감사 기록을 읽지 못해도 사용량 집계 함수만은 실행할 수 있다."""

import io
from datetime import UTC, datetime, timedelta

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


def test_upgrade_creates_definer_function_for_app_role_only() -> None:
    upgrade = _render_sql("0007:0008")

    assert "CREATE FUNCTION llm_usage_since(p_login text, p_since timestamptz)" in upgrade
    assert "SECURITY DEFINER" in upgrade
    assert "SET search_path = pg_catalog, public" in upgrade
    assert "REVOKE ALL ON FUNCTION llm_usage_since(text, timestamptz) FROM PUBLIC" in upgrade
    assert f"GRANT EXECUTE ON FUNCTION llm_usage_since(text, timestamptz) TO {APP_ROLE}" in upgrade
    assert "DROP FUNCTION llm_usage_since(text, timestamptz)" in _render_sql(
        "0008:0007", downgrade=True
    )


INSERT = (
    "INSERT INTO audit_log (request_id, user_login, user_department, user_role,"
    " user_clearance_level, question_sha256, question_chars, outcome, context_files,"
    " cited_files, retrieval_ms, total_ms, cost_usd, created_at)"
    " VALUES ('r', :login, '개발팀', '사원', 1, 'h', 1, 'answered', '{}', '{}', 1, 1, :cost, :at)"
)
USAGE = "SELECT user_requests, total_cost_usd FROM llm_usage_since('kim', :since)"


def test_app_role_gets_only_the_aggregates(db_engine: Engine) -> None:
    now = datetime.now(UTC)
    since = now - timedelta(hours=1)
    with db_engine.connect() as connection, connection.begin() as transaction:
        connection.execute(text("TRUNCATE audit_log"))
        for login, cost, at in [
            ("kim", 0.5, now),
            ("kim", None, now),
            ("lee", 0.25, now),
            ("kim", 9.0, now - timedelta(days=1)),  # 기준 시각 이전은 세지 않는다
        ]:
            connection.execute(text(INSERT), {"login": login, "cost": cost, "at": at})
        connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        usage = connection.execute(text(USAGE), {"since": since}).one()
        denied = pytest.raises(ProgrammingError, match="permission denied")
        with denied, connection.begin_nested():
            connection.execute(text("SELECT question FROM audit_log"))
        transaction.rollback()

    assert tuple(usage) == (2, 0.75)


def test_auditor_role_cannot_run_the_usage_function(db_engine: Engine) -> None:
    with db_engine.connect() as connection, connection.begin() as transaction:
        connection.execute(text(f"SET LOCAL ROLE {AUDITOR_ROLE}"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text(USAGE), {"since": datetime.now(UTC)})
        transaction.rollback()
