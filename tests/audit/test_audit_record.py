"""감사 기록 만들기(원문 저장 설정), 저장, 보관 기간 삭제, 관리 명령 테스트."""

import hashlib
import runpy
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.generate import Answer, Citation
from rag_service.answer.llm import Completion
from rag_service.api.auth import CurrentUser
from rag_service.audit import cli
from rag_service.audit.models import AuditLog
from rag_service.audit.record import (
    AskResult,
    AuditPolicy,
    Outcome,
    build_entry,
    purge,
    write_entry,
)
from rag_service.config import Settings
from tests.fixtures.db import db_engine

__all__ = ["db_engine"]

USER = CurrentUser("kim", "김사원", "개발팀", "사원", 1)
QUESTION = "출장비 정산 기한은?"
ANSWER = Answer(
    text="7일 이내입니다. [1]",
    refused=False,
    reason=None,
    citations=(Citation(1, 10, "travel.md", "출장비 규정", "정산", None),),
    invalid_citations=(),
    context=(),
    completion=Completion("7일 이내입니다. [1]", "claude-sonnet-5-5", 1000, 50),
)


def _result(answer: Answer | None = ANSWER, outcome: Outcome = "answered") -> AskResult:
    return AskResult(
        outcome=outcome,
        answer=answer,
        verified=True if answer else None,
        context_files=("travel.md", "faq.md"),
        retrieval_ms=120,
        first_token_ms=900,
        total_ms=2100,
    )


def _entry(policy: AuditPolicy, result: AskResult | None = None) -> AuditLog:
    return build_entry(
        request_id="req-1",
        client_ip="10.0.0.5",
        user=USER,
        question=QUESTION,
        result=result or _result(),
        policy=policy,
    )


def test_entry_keeps_user_snapshot_sources_usage_and_text() -> None:
    entry = _entry(AuditPolicy())

    assert (entry.user_login, entry.user_department, entry.user_clearance_level) == (
        "kim",
        "개발팀",
        1,
    )
    assert (entry.question, entry.answer) == (QUESTION, "7일 이내입니다. [1]")
    assert (entry.context_files, entry.cited_files) == (["travel.md", "faq.md"], ["travel.md"])
    assert (entry.model, entry.input_tokens, entry.output_tokens) == ("claude-sonnet-5-5", 1000, 50)
    assert entry.cost_usd == pytest.approx((1000 * 2 + 50 * 10) / 1_000_000)
    assert (entry.retrieval_ms, entry.first_token_ms, entry.total_ms) == (120, 900, 2100)


def test_text_can_be_turned_off_keeping_length_and_hash() -> None:
    entry = _entry(AuditPolicy(store_text=False))

    assert (entry.question, entry.answer) == (None, None)
    assert entry.question_chars == len(QUESTION)
    assert entry.question_sha256 == hashlib.sha256(QUESTION.encode("utf-8")).hexdigest()


def test_failed_request_has_no_answer_or_usage() -> None:
    entry = _entry(AuditPolicy(), _result(answer=None, outcome="error"))

    assert (entry.outcome, entry.answer, entry.refusal_reason) == ("error", None, None)
    assert (entry.cited_files, entry.model, entry.cost_usd) == ([], None, None)


@pytest.fixture
def sessions(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log RESTART IDENTITY"))
    yield sessionmaker(db_engine)
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log RESTART IDENTITY"))


def _store(sessions: sessionmaker[Session], *ages_in_days: int) -> None:
    now = datetime.now(UTC)
    for days in ages_in_days:
        entry = _entry(AuditPolicy())
        entry.created_at = now - timedelta(days=days)
        write_entry(sessions, entry)


def _count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return session.scalar(select(func.count()).select_from(AuditLog)) or 0


def test_write_entry_saves_row_with_server_time(sessions: sessionmaker[Session]) -> None:
    write_entry(sessions, _entry(AuditPolicy()))

    with sessions() as session:
        row = session.scalars(select(AuditLog)).one()
    assert (row.request_id, row.outcome, row.question) == ("req-1", "answered", QUESTION)
    assert abs(datetime.now(UTC) - row.created_at) < timedelta(minutes=5)


def test_purge_deletes_only_rows_older_than_retention(sessions: sessionmaker[Session]) -> None:
    _store(sessions, 1, 89, 91, 400)

    with sessions.begin() as session:
        deleted = purge(session, older_than_days=90)

    assert (deleted, _count(sessions)) == (2, 2)


def test_purge_rejects_non_positive_days(sessions: sessionmaker[Session]) -> None:
    with sessions() as session, pytest.raises(ValueError, match="1일 이상"):
        purge(session, older_than_days=0)


def test_cli_purge_uses_days_argument(
    sessions: sessionmaker[Session], db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    _store(sessions, 1, 40)

    assert cli.main(["purge", "--days", "30"], engine=db_engine) == 0

    assert "감사 기록 1건 삭제" in capsys.readouterr().out
    assert _count(sessions) == 1


def test_cli_purge_defaults_to_retention_setting(
    sessions: sessionmaker[Session], db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(sessions, 5, 15)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(audit_retention_days=10))

    cli.main(["purge"], engine=db_engine)

    assert _count(sessions) == 1


def test_module_entry_point_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 3)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("rag_service.audit", run_name="__main__")

    assert excinfo.value.code == 3
