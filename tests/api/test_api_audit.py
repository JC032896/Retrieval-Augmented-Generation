"""POST /ask의 감사 기록과 운영 로그: 요청마다 한 행, 원문 저장 설정, 실패·연결 끊김도 남는다."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from rag_service.api import ask as ask_module
from rag_service.api.auth import CurrentUser
from rag_service.api.services import Services, get_services
from rag_service.audit.models import AuditLog
from rag_service.audit.record import AskResult, AuditPolicy
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.logs import JsonFormatter
from rag_service.main import app
from rag_service.retrieval.hits import SearchHit
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.logs import captured_logs, fields
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

QUESTION = "출장비 정산 기한은?"
REPLY = ["7일 이내에 ", "정산을 신청합니다. [1]"]


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def services(
    tmp_path: Path, db_engine: Engine, db_session: Session, tokenizer: KoreanTokenizer
) -> Iterator[Services]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log RESTART IDENTITY"))
    yield build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=tokenizer,
        llm=FakeStreamingLLM(REPLY),
    )
    app.dependency_overrides.clear()


def _ask(services: Services, question: str = QUESTION, user: str | None = "kim") -> httpx2.Response:
    app.dependency_overrides[get_services] = lambda: services
    headers = {} if user is None else {"X-User-Id": user}
    return TestClient(app).post("/ask", json={"question": question}, headers=headers)


def _row(engine: Engine, response: httpx2.Response) -> AuditLog:
    with Session(engine) as session:
        query = select(AuditLog).where(AuditLog.request_id == response.headers["x-request-id"])
        return session.scalars(query).one()


def test_answer_is_audited_under_the_response_request_id(
    services: Services, db_engine: Engine
) -> None:
    row = _row(db_engine, _ask(services))

    assert (row.user_login, row.user_department, row.user_clearance_level) == ("kim", "개발팀", 1)
    assert (row.outcome, row.question, row.answer) == ("answered", QUESTION, "".join(REPLY))
    assert (row.context_files, row.cited_files, row.verified) == (
        ["travel.md"],
        ["travel.md"],
        True,
    )
    assert row.model == "fake"
    assert row.first_token_ms is not None
    assert row.retrieval_ms <= row.first_token_ms <= row.total_ms


def test_text_storage_can_be_turned_off(services: Services, db_engine: Engine) -> None:
    row = _row(db_engine, _ask(replace(services, audit=AuditPolicy(store_text=False))))

    assert (row.question, row.answer, row.question_chars) == (None, None, len(QUESTION))


def test_llm_failure_is_audited_as_error(services: Services, db_engine: Engine) -> None:
    failing = replace(services, llm=FakeStreamingLLM(REPLY, fail_after=1))

    row = _row(db_engine, _ask(failing))

    assert (row.outcome, row.answer, row.context_files) == ("error", None, ["travel.md"])


def test_operation_log_has_metrics_but_no_question_text(services: Services) -> None:
    with captured_logs("rag_service.api.ask") as records:
        response = _ask(services)

    [record] = [r for r in records if r.getMessage() == "ask"]
    assert fields(record)["request_id"] == response.headers["x-request-id"]
    assert fields(record)["outcome"] == "answered"
    line = JsonFormatter().format(record)
    assert QUESTION not in line
    assert "정산을 신청합니다" not in line


@pytest.mark.parametrize(
    ("user", "expected"),
    [(None, {"reason": "X-User-Id 헤더가 없습니다"}), ("nobody", {"reason": "unregistered"})],
)
def test_auth_failures_are_logged(
    services: Services, user: str | None, expected: dict[str, Any]
) -> None:
    with captured_logs("rag_service.api.ask") as records:
        assert _ask(services, user=user).status_code == 401

    [record] = [r for r in records if r.getMessage() == "auth_failed"]
    assert expected.items() <= fields(record).items()


def test_audit_write_failure_does_not_break_the_answer(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_write(*args: object) -> None:
        raise RuntimeError("DB 다운")

    monkeypatch.setattr(ask_module, "write_entry", broken_write)

    with captured_logs("rag_service.api.ask") as records:
        response = _ask(services)

    assert response.status_code == 200
    assert "event: done" in response.text
    assert any(r.getMessage() == "audit_write_failed" for r in records)


HIT = SearchHit(1, "travel.md", "출장비 규정", "정산", None, "7일 이내에 정산한다.", 0.9)


def test_disconnect_mid_answer_is_reported_as_cancelled(tokenizer: KoreanTokenizer) -> None:
    results: list[AskResult] = []
    events = ask_module.answer_events(
        QUESTION,
        [HIT],
        llm=FakeStreamingLLM(REPLY),
        tokenizer=tokenizer,
        on_finish=results.append,
    )

    next(events)
    events.close()  # 클라이언트가 연결을 끊으면 서버가 생성기를 닫는다

    [result] = results
    assert (result.outcome, result.answer, result.context_files) == (
        "cancelled",
        None,
        ("travel.md",),
    )


def test_record_ask_logs_without_text(services: Services) -> None:
    user = CurrentUser("kim", "김사원", "개발팀", "사원", 1)
    result = AskResult("refused", None, None, (), 5, None, 9)

    with captured_logs("rag_service.api.ask") as records:
        ask_module.record_ask(
            services, request_id="r1", client_ip=None, user=user, question=QUESTION, result=result
        )

    [record] = records
    assert fields(record)["outcome"] == "refused"
    assert fields(record)["first_token_ms"] is None
