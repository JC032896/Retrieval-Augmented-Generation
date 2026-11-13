"""질문 API의 503에 붙는 오류 종류 머리글 (X-Error-Code).

본문 문장은 운영자용(설정 이름 ANTHROPIC_API_KEY)이라 명령줄 도구가 그대로 보여 준다.
직원 채팅 화면은 문장 대신 이 머리글을 읽고 "관리자에게 알려 주세요"를 보인다.
"""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rag_service.api.services import Services, get_services
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]


@pytest.fixture
def services(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[Services]:
    yield build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(["7일 이내에 정산을 신청합니다. [1]"]),
    )
    app.dependency_overrides.clear()


QUESTION = {"question": "출장비 정산 기한은?"}


def _client(services: Services) -> TestClient:
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


def test_missing_llm_says_which_error_in_a_header(services: Services) -> None:
    response = _client(replace(services, llm=None)).post(
        "/ask", json=QUESTION, headers={"X-User-Id": "kim"}
    )

    assert response.status_code == 503
    assert response.headers["x-error-code"] == "llm_not_configured"
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]  # 운영자용 문장은 그대로


def test_other_responses_have_no_error_code(services: Services) -> None:
    client = _client(services)
    answered = client.post("/ask", json=QUESTION, headers={"X-User-Id": "kim"})
    unauthenticated = client.post("/ask", json=QUESTION)

    assert answered.status_code == 200
    assert unauthenticated.status_code == 401
    assert "x-error-code" not in answered.headers
    assert "x-error-code" not in unauthenticated.headers
