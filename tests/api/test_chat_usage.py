"""GET /api/usage: 채팅 화면의 입력창 옆에 보이는 '오늘 남은 질문 수'.

질문 API가 남긴 감사 기록으로 센다 (질문 한도와 같은 DB 함수, 마이그레이션 0008).
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.chat import ChatServices, get_chat_services
from rag_service.api.limits import UsageLimits
from rag_service.api.services import get_services
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

Client = Callable[[int | None], TestClient]


@pytest.fixture
def client(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[Client]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log RESTART IDENTITY CASCADE"))
    services = build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(["7일 이내에 정산을 신청합니다. [1]"]),
    )
    app.dependency_overrides[get_services] = lambda: services

    def make(daily: int | None) -> TestClient:
        chat = ChatServices(
            sessions=services.sessions,
            authenticator=DevHeaderAuthenticator(),
            limits=UsageLimits(daily_requests_per_user=daily),
        )
        app.dependency_overrides[get_chat_services] = lambda: chat
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _ask(api: TestClient, user: str = "kim") -> None:
    response = api.post(
        "/ask", json={"question": "출장비 정산 기한은?"}, headers={"X-User-Id": user}
    )
    assert response.status_code == 200


def test_questions_left_counts_todays_questions_per_user(client: Client) -> None:
    api = client(5)
    _ask(api)
    _ask(api)
    _ask(api, user="boss")

    kim = api.get("/api/usage", headers={"X-User-Id": "kim"}).json()
    boss = api.get("/api/usage", headers={"X-User-Id": "boss"}).json()

    assert kim == {"questions_left": 3, "daily_questions": 5}
    assert boss == {"questions_left": 4, "daily_questions": 5}


def test_questions_left_never_goes_below_zero(client: Client) -> None:
    api = client(1)
    _ask(api)
    _ask(api)  # 질문 API 쪽 한도는 꺼 두었으므로 한도를 넘겨 기록된다

    assert api.get("/api/usage", headers={"X-User-Id": "kim"}).json()["questions_left"] == 0


def test_no_per_user_limit_means_no_count(client: Client) -> None:
    api = client(None)

    assert api.get("/api/usage", headers={"X-User-Id": "kim"}).json() == {
        "questions_left": None,
        "daily_questions": None,
    }
    assert api.get("/api/usage").status_code == 401
