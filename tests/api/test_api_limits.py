"""POST /ask 사용 한도: 하루 질문 수, 전사 하루 비용, 동시 요청 수를 넘으면 LLM 없이 429."""

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from rag_service.api.limits import UsageLimits
from rag_service.api.services import Services, get_services
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.logs import captured_logs, fields
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

REPLY = ["7일 이내에 ", "정산을 신청합니다. [1]"]


@pytest.fixture
def services(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[Services]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log, chunk_snapshots RESTART IDENTITY"))
    yield build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(REPLY),
    )
    app.dependency_overrides.clear()


def _ask(services: Services, user: str = "kim") -> httpx2.Response:
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app).post(
        "/ask", json={"question": "출장비 정산 기한은?"}, headers={"X-User-Id": user}
    )


def _llm_calls(services: Services) -> int:
    assert isinstance(services.llm, FakeStreamingLLM)
    return len(services.llm.calls)


def test_daily_question_limit_is_per_user(services: Services) -> None:
    limited = replace(services, limits=UsageLimits(daily_requests_per_user=2))

    assert [_ask(limited).status_code for _ in range(2)] == [200, 200]
    with captured_logs("rag_service.api.ask") as records:
        blocked = _ask(limited)

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == (
        "오늘 질문 한도(2회)를 모두 썼습니다. 내일 0시(UTC+9)에 다시 쓸 수 있습니다."
    )
    assert 0 < int(blocked.headers["retry-after"]) <= 24 * 3600
    assert _llm_calls(services) == 2
    [record] = [r for r in records if r.getMessage() == "rate_limited"]
    assert (fields(record)["reason"], fields(record)["user"]) == ("daily_requests", "kim")
    assert _ask(limited, user="boss").status_code == 200  # 다른 사용자는 따로 센다


def _store_cost(engine: Engine, login: str, cost: float, at: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_log (request_id, user_login, user_department, user_role,"
                " user_clearance_level, question_sha256, question_chars, outcome, context_files,"
                " cited_files, retrieval_ms, total_ms, cost_usd, created_at) VALUES ('r', :login,"
                " '경영진', '임원', 3, 'h', 1, 'answered', '{}', '{}', 1, 1, :cost, :at)"
            ),
            {"login": login, "cost": cost, "at": at},
        )


def test_company_budget_counts_everyone_and_only_today(
    services: Services, db_engine: Engine
) -> None:
    limited = replace(services, limits=UsageLimits(daily_budget_usd=1.0))
    _store_cost(db_engine, "boss", 5.0, datetime.now(UTC) - timedelta(days=2))
    assert _ask(limited).status_code == 200  # 어제까지의 비용은 세지 않는다

    _store_cost(db_engine, "boss", 1.0, datetime.now(UTC))
    blocked = _ask(limited)

    assert blocked.status_code == 429
    assert "회사 전체 LLM 사용 예산($1.00)" in blocked.json()["detail"]
    assert _llm_calls(services) == 1


def test_concurrent_limit_and_slot_is_released_after_each_answer(services: Services) -> None:
    limited = replace(services, limits=UsageLimits(concurrent_per_user=1))

    assert [_ask(limited).status_code for _ in range(3)] == [200, 200, 200]

    held = limited.in_flight.acquire("kim", 1)  # 다른 질문이 아직 처리 중인 상황
    blocked = _ask(limited)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "5"
    assert "이미 처리 중인 질문이 1개" in blocked.json()["detail"]
    assert isinstance(held, int)
    limited.in_flight.release(held)
    assert _ask(limited).status_code == 200


class _BrokenEmbedder(FakeEmbedder):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("임베딩 실패")


def test_slot_is_released_when_search_fails(services: Services) -> None:
    broken = replace(
        services, embedder=_BrokenEmbedder(), limits=UsageLimits(concurrent_per_user=1)
    )
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_services] = lambda: broken

    response = client.post("/ask", json={"question": "질문"}, headers={"X-User-Id": "kim"})

    assert response.status_code == 500
    assert isinstance(broken.in_flight.acquire("kim", 1), int)
