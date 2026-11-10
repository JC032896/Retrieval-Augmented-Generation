"""OIDC 모드의 POST /ask: 유효한 토큰만 통과하고, 개발용 헤더로는 다른 사람 행세를 할 수 없다."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.services import Services, get_services
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import sync_users
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.oidc import FakeIssuer, bearer, new_private_key
from tests.fixtures.rerank import OverlapReranker
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
QUESTION = {"question": "출장비 정산 기한은?"}


@pytest.fixture
def issuer() -> FakeIssuer:
    return FakeIssuer()


@pytest.fixture
def client(db_engine: Engine, db_session: Session, issuer: FakeIssuer) -> Iterator[TestClient]:
    sync_users(db_session, load_corpus(SAMPLES))  # 문서 없이 사용자만 등록한다
    db_session.commit()
    services = Services(
        sessions=sessionmaker(db_engine),
        embedder=FakeEmbedder(),
        reranker=OverlapReranker(),
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(["안 쓰임"]),
        authenticator=issuer.authenticator("preferred_username"),
    )
    app.dependency_overrides[get_services] = lambda: services
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_valid_token_is_accepted(client: TestClient, issuer: FakeIssuer) -> None:
    response = client.post("/ask", json=QUESTION, headers=bearer(issuer.token()))

    assert response.status_code == 200
    assert "event: done" in response.text  # 문서가 없으므로 검색 결과 없음으로 거절된다


def test_forged_token_is_401_with_bearer_challenge(client: TestClient, issuer: FakeIssuer) -> None:
    forged = issuer.token(key=new_private_key())

    response = client.post("/ask", json=QUESTION, headers=bearer(forged))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_dev_header_cannot_impersonate_in_oidc_mode(client: TestClient) -> None:
    response = client.post("/ask", json=QUESTION, headers={"X-User-Id": "kim"})

    assert response.status_code == 401


def test_valid_token_for_unregistered_user_is_401(client: TestClient, issuer: FakeIssuer) -> None:
    token = issuer.token(preferred_username="ghost")

    response = client.post("/ask", json=QUESTION, headers=bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == "등록되지 않은 사용자입니다"


def test_login_server_down_is_503(client: TestClient, issuer: FakeIssuer) -> None:
    issuer.down = True

    response = client.post("/ask", json=QUESTION, headers=bearer(issuer.token()))

    assert response.status_code == 503
