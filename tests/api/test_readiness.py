"""모델 미리 읽기(PRELOAD_MODELS)와 준비 상태: /ask 503, /ready, /health의 db·models."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service import main as main_module
from rag_service.api import readiness
from rag_service.api.readiness import MODELS, ModelState, start_warm_up, warm_up
from rag_service.api.services import Services, get_services
from rag_service.config import Settings
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app, get_index_sessions
from tests.fixtures.api import build_services
from tests.fixtures.db import CONNECT_ARGS, db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    yield
    MODELS.status, MODELS.error = "lazy", None
    app.dependency_overrides.clear()


@pytest.fixture
def services(tmp_path: Path, db_engine: Engine, db_session: Session) -> Services:
    return build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(["답 [1]"]),
    )


def test_warm_up_loads_and_exercises_both_models(services: Services) -> None:
    state = ModelState()
    assert isinstance(services.embedder, FakeEmbedder)

    warm_up(state, lambda: services)

    assert (state.status, state.error) == ("ready", None)
    assert services.embedder.calls[-1] == ["준비"]


def test_warm_up_failure_is_recorded() -> None:
    def missing() -> Services:
        raise OSError("모델 파일이 없습니다")

    state = ModelState()
    warm_up(state, missing)

    assert (state.status, state.error) == ("error", "OSError: 모델 파일이 없습니다")


def test_background_warm_up_uses_the_shared_services(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(readiness, "get_services", lambda: services)
    state = ModelState()

    start_warm_up(state).join(timeout=10)

    assert state.status == "ready"


def _ask(services: Services) -> TestClient:
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


@pytest.mark.parametrize(
    ("status", "message"),
    [("loading", "불러오는 중입니다"), ("error", "불러오지 못했습니다")],
)
def test_questions_wait_until_models_are_ready(
    services: Services, status: readiness.ModelStatus, message: str
) -> None:
    MODELS.status = status
    response = _ask(services).post(
        "/ask", json={"question": "출장비 정산 기한은?"}, headers={"X-User-Id": "kim"}
    )

    assert response.status_code == 503
    assert message in response.json()["detail"]
    assert (response.headers.get("retry-after") == "30") == (status == "loading")
    assert isinstance(services.llm, FakeStreamingLLM) and services.llm.calls == []


def _client(engine: Engine) -> TestClient:
    app.dependency_overrides[get_index_sessions] = lambda: sessionmaker(engine)
    return TestClient(app)


@pytest.mark.parametrize(
    ("status", "code"), [("lazy", 200), ("ready", 200), ("loading", 503), ("error", 503)]
)
def test_ready_follows_model_state(
    db_engine: Engine, status: readiness.ModelStatus, code: int
) -> None:
    MODELS.status = status
    response = _client(db_engine).get("/ready")

    assert response.status_code == code
    assert response.json()["models"]["status"] == status


def test_ready_and_health_report_a_broken_database(db_engine: Engine) -> None:
    broken = create_engine(db_engine.url.set(database="rag_no_such_db"), connect_args=CONNECT_ARGS)
    MODELS.status, MODELS.error = "error", "OSError: 없음"
    client = _client(broken)

    ready = client.get("/ready")
    health = client.get("/health").json()

    assert ready.status_code == 503
    assert ready.json() == {
        "ready": False,
        "db": "error",
        "models": {"status": "error", "error": "OSError: 없음"},
    }
    assert (health["status"], health["db"]) == ("ok", "error")


def test_lifespan_preloads_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[bool] = []
    monkeypatch.setattr(main_module, "start_warm_up", lambda: started.append(True))
    for preload in (False, True):
        settings = Settings(preload_models=preload)
        monkeypatch.setattr(main_module, "get_settings", lambda s=settings: s)
        with TestClient(app):
            pass

    assert started == [True]
