"""POST /ask 테스트: 사용자 확인, 권한 안의 검색, SSE 이벤트 순서와 내용.

모델 대신 가짜 임베더·리랭커·LLM을 쓰고, DB는 테스트 DB에 작은 코퍼스를 수집해서 쓴다.
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.llm import ClaudeLLM
from rag_service.api import services as services_module
from rag_service.api.auth import DevHeaderAuthenticator, build_authenticator
from rag_service.api.services import Services, get_services
from rag_service.config import Settings
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.rerank import OverlapReranker
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

ORG = """
departments: [개발팀, 경영진]
roles: [사원, 임원]
users:
  - {id: kim, name: 김사원, department: 개발팀, role: 사원, clearance_level: 1}
  - {id: boss, name: 대표, department: 경영진, role: 임원, clearance_level: 3}
"""
ACL = """
documents:
  - {file: travel.md, title: 출장비 규정, security_level: 1, roles: [사원, 임원]}
  - {file: pay.md, title: 임원 보수, security_level: 3, departments: [경영진]}
"""
TRAVEL = "# 출장비 규정\n\n## 정산\n\n출장에서 돌아온 날로부터 7일 이내에 정산을 신청한다.\n"
PAY = "# 임원 보수\n\n## 성과급\n\n임원 성과급은 기본급의 300%까지 지급한다.\n"

Client = Callable[..., TestClient]


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def services(
    tmp_path: Path, db_engine: Engine, db_session: Session, tokenizer: KoreanTokenizer
) -> Services:
    (tmp_path / "docs").mkdir()
    (tmp_path / "org.yaml").write_text(ORG, encoding="utf-8")
    (tmp_path / "acl.yaml").write_text(ACL, encoding="utf-8")
    (tmp_path / "docs" / "travel.md").write_text(TRAVEL, encoding="utf-8")
    (tmp_path / "docs" / "pay.md").write_text(PAY, encoding="utf-8")
    embedder = FakeEmbedder()
    ingest_corpus(db_session, load_corpus(tmp_path), embedder=embedder, tokenizer=tokenizer)
    db_session.commit()
    return Services(
        sessions=sessionmaker(db_engine),
        embedder=embedder,
        reranker=OverlapReranker(),
        tokenizer=tokenizer,
        llm=FakeStreamingLLM(["7일 이내에 ", "정산을 신청합니다. [1]"]),
        authenticator=DevHeaderAuthenticator(),
    )


@pytest.fixture
def client(services: Services) -> Iterator[Client]:
    def make(**changes: Any) -> TestClient:
        changed = replace(services, **changes)
        app.dependency_overrides[get_services] = lambda: changed
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _ask(client: TestClient, question: str, user: str | None = "kim") -> Any:
    headers = {} if user is None else {"X-User-Id": user}
    return client.post("/ask", json={"question": question}, headers=headers)


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_streams_deltas_then_done_with_citations(client: Client) -> None:
    response = _ask(client(), "출장비 정산 기한은?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [name for name, _ in events] == ["delta", "delta", "done"]
    assert "".join(data["text"] for name, data in events if name == "delta") == (
        "7일 이내에 정산을 신청합니다. [1]"
    )
    done = events[-1][1]
    assert done["text"] == "7일 이내에 정산을 신청합니다. [1]"
    assert (done["refused"], done["reason"]) == (False, None)
    assert [(c["number"], c["file"]) for c in done["citations"]] == [(1, "travel.md")]
    assert done["verification"] == {"verified": True, "problems": []}
    assert done["usage"]["model"] == "fake"


def test_search_only_sees_documents_the_user_may_read(client: Client) -> None:
    llm = FakeStreamingLLM(["임원 성과급은 300%입니다. [1]"])

    _ask(client(llm=llm), "임원 성과급은?", user="kim")
    _ask(client(llm=llm), "임원 성과급은?", user="boss")

    kim_prompt, boss_prompt = (prompt for _, prompt in llm.calls)
    assert "300%" not in kim_prompt
    assert "300%" in boss_prompt


def test_refusal_sends_only_done(client: Client) -> None:
    llm = FakeStreamingLLM(["문서에서 찾을 수 없습니다. 해외 규정이 없습니다."])

    events = _events(_ask(client(llm=llm), "해외 출장비는?").text)

    assert [name for name, _ in events] == ["done"]
    done = events[0][1]
    assert (done["refused"], done["reason"]) == (True, "not_in_documents")
    assert (done["citations"], done["verification"]) == ([], None)


def test_llm_failure_ends_with_error_event(client: Client) -> None:
    llm = FakeStreamingLLM(["7일 ", "이내 [1]"], fail_after=1)

    events = _events(_ask(client(llm=llm), "출장비 정산 기한은?").text)

    assert [name for name, _ in events] == ["delta", "error"]
    assert events[-1][1]["code"] == "generation_failed"


@pytest.mark.parametrize("user", [None, "", "nobody"])
def test_unknown_or_missing_user_is_401(client: Client, user: str | None) -> None:
    llm = FakeStreamingLLM(["안 쓰임"])

    response = _ask(client(llm=llm), "출장비 정산 기한은?", user=user)

    assert response.status_code == 401
    assert llm.calls == []


def test_disabled_auth_is_503(client: Client) -> None:
    response = _ask(client(authenticator=None), "출장비 정산 기한은?")

    assert response.status_code == 503
    assert "AUTH_MODE" in response.json()["detail"]


def test_missing_llm_is_503(client: Client) -> None:
    response = _ask(client(llm=None), "출장비 정산 기한은?")

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


@pytest.mark.parametrize("question", ["", "   ", "가" * 1001])
def test_blank_or_too_long_question_is_422(client: Client, question: str) -> None:
    assert _ask(client(), question).status_code == 422


def test_build_authenticator_follows_auth_mode() -> None:
    assert build_authenticator("disabled") is None
    assert isinstance(build_authenticator("dev_header"), DevHeaderAuthenticator)


@pytest.mark.parametrize("key", [None, "test-key"])
def test_get_services_builds_from_settings(
    monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    settings = Settings(
        anthropic_api_key=None if key is None else SecretStr(key),
        auth_mode="dev_header",
        llm_timeout_seconds=30.0,
    )
    monkeypatch.setattr(services_module, "get_settings", lambda: settings)
    # 수 GB 모델을 읽지 않도록 가짜로 바꾼다
    monkeypatch.setattr(services_module, "SentenceTransformerEmbedder", FakeEmbedder)
    monkeypatch.setattr(services_module, "CrossEncoderReranker", OverlapReranker)
    get_services.cache_clear()
    try:
        built = get_services()
    finally:
        get_services.cache_clear()

    assert isinstance(built.authenticator, DevHeaderAuthenticator)
    if key is None:
        assert built.llm is None
    else:
        assert isinstance(built.llm, ClaudeLLM)
        assert built.llm._client.timeout == 30.0
