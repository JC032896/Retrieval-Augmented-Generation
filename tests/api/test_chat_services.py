"""채팅 화면 API의 설정 읽기와, 대화 기록 저장이 실패해도 답은 그대로 나가는지."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rag_service.api import ask as ask_module
from rag_service.api import chat as chat_module
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.chat import get_chat_services
from rag_service.api.services import Services, get_services
from rag_service.config import Settings
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.logs import captured_logs, fields
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]


def test_chat_services_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(auth_mode="dev_header", chat_history_days=30, admin_group="it-admins")
    monkeypatch.setattr(chat_module, "get_settings", lambda: settings)
    get_chat_services.cache_clear()
    try:
        built = get_chat_services()
    finally:
        get_chat_services.cache_clear()

    assert isinstance(built.authenticator, DevHeaderAuthenticator)
    assert built.history_days == 30
    assert built.role_groups.admin == "it-admins"


@pytest.fixture
def services(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[Services]:
    built = build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(["7일 이내에 정산을 신청합니다. [1]"]),
    )
    changed = replace(built, history_days=90)
    app.dependency_overrides[get_services] = lambda: changed
    yield changed
    app.dependency_overrides.clear()


def test_history_write_failure_does_not_break_the_answer(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_save(*args: object, **kwargs: object) -> int:
        raise RuntimeError("DB 다운")

    monkeypatch.setattr(ask_module, "save_turn", broken_save)

    with captured_logs("rag_service.api.ask") as records:
        response = TestClient(app).post(
            "/ask", json={"question": "출장비 정산 기한은?"}, headers={"X-User-Id": "kim"}
        )

    assert response.status_code == 200
    assert "event: done" in response.text
    [record] = [r for r in records if r.getMessage() == "chat_history_write_failed"]
    assert fields(record)["request_id"] == response.headers["x-request-id"]
