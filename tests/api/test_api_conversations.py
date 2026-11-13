"""한 대화에서 이어 묻기: 질문 API(/ask)의 대화 id와 앞 질문, 대화 API, 감사 기록과 재현.

첫 질문은 그대로 검색하고, 이어 묻는 질문은 앞 질문들로 다시 쓴 질문으로 검색·답변한다.
kim(개발팀 사원, 등급 1)은 출장비 규정만, boss(경영진 임원, 등급 3)는 임원 보수까지 볼 수 있다.
"""

from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from rag_service.answer.followup import FOLLOWUP_SYSTEM_PROMPT
from rag_service.answer.llm import Completion
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.chat import ChatServices, get_chat_services
from rag_service.api.services import Services, get_services
from rag_service.audit import replay
from rag_service.audit.models import AuditLog
from rag_service.audit.record import AuditPolicy
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services, parse_events
from tests.fixtures.db import db_engine, db_session

__all__ = ["db_engine", "db_session"]

REWRITTEN = "출장비 정산은 해외 출장도 7일 이내에 신청해야 하는가?"
ANSWER = "돌아온 날로부터 7일 이내에 정산을 신청합니다. [1]"


@dataclass
class TwoPromptLLM:
    """질문 다시 쓰기 요청과 답변 요청에 다르게 답하는 가짜 LLM. 받은 요청을 기록한다."""

    rewrite: str = REWRITTEN
    calls: list[tuple[str, str]] = field(default_factory=list)

    def stream(self, *, system: str, prompt: str) -> Generator[str, None, Completion]:
        self.calls.append((system, prompt))
        text = self.rewrite if system == FOLLOWUP_SYSTEM_PROMPT else ANSWER
        yield text
        return Completion(text, model="fake", input_tokens=10, output_tokens=5)


Client = Callable[..., TestClient]


@pytest.fixture
def llm() -> TwoPromptLLM:
    return TwoPromptLLM()


@pytest.fixture
def client(
    tmp_path: Path, db_engine: Engine, db_session: Session, llm: TwoPromptLLM
) -> Iterator[Client]:
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE chat_turns, chat_conversations, audit_log, chunk_snapshots "
                "RESTART IDENTITY"
            )
        )
    base = build_services(
        tmp_path, engine=db_engine, session=db_session, tokenizer=KoreanTokenizer(), llm=llm
    )

    def make(history_days: int = 90, **changes: Any) -> TestClient:
        services: Services = replace(base, history_days=history_days, **changes)
        chat = ChatServices(
            sessions=base.sessions,
            authenticator=DevHeaderAuthenticator(),
            history_days=history_days,
        )
        app.dependency_overrides[get_services] = lambda: services
        app.dependency_overrides[get_chat_services] = lambda: chat
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _as(login: str) -> dict[str, str]:
    return {"X-User-Id": login}


def _ask(api: TestClient, body: dict[str, Any], user: str = "kim") -> tuple[dict[str, str], Any]:
    response = api.post("/ask", json=body, headers=_as(user))
    assert response.status_code == 200, response.text
    return dict(response.headers), parse_events(response.text)[-1][1]


def test_first_question_starts_a_conversation_without_rewriting(
    client: Client, llm: TwoPromptLLM
) -> None:
    headers, done = _ask(client(), {"question": "출장비 정산 기한은?"})

    assert headers["x-conversation-id"] == "1"
    assert done["search_question"] is None
    assert [system == FOLLOWUP_SYSTEM_PROMPT for system, _ in llm.calls] == [False]


def test_follow_up_is_rewritten_searched_answered_and_kept_in_the_same_conversation(
    client: Client, llm: TwoPromptLLM, db_engine: Engine
) -> None:
    api = client()
    first_headers, _ = _ask(api, {"question": "출장비 정산 기한은?"})
    conversation = int(first_headers["x-conversation-id"])

    headers, done = _ask(
        api,
        {
            "question": "해외 출장도?",
            "conversation_id": conversation,
            "previous": ["출장비 정산 기한은?"],
        },
    )

    assert headers["x-conversation-id"] == str(conversation)
    assert done["search_question"] == REWRITTEN
    rewrite_call, answer_call = llm.calls[1:]
    assert rewrite_call[0] == FOLLOWUP_SYSTEM_PROMPT
    assert "1. 출장비 정산 기한은?" in rewrite_call[1]
    assert "마지막 질문: 해외 출장도?" in rewrite_call[1]
    assert ANSWER not in rewrite_call[1]  # 앞 답은 넣지 않는다
    assert REWRITTEN in answer_call[1]  # 답변 요청은 다시 쓴 질문으로

    page = api.get("/api/conversations", headers=_as("kim")).json()
    [item] = page["items"]
    assert (item["id"], item["title"], item["turns"]) == (conversation, "출장비 정산 기한은?", 2)
    opened = api.get(f"/api/conversations/{conversation}", headers=_as("kim")).json()
    assert [(t["question"], t["search_question"]) for t in opened["turns"]] == [
        ("출장비 정산 기한은?", None),
        ("해외 출장도?", REWRITTEN),
    ]
    assert opened["turns"][1]["answer"]["search_question"] == REWRITTEN

    with Session(db_engine) as session:
        rows = session.execute(
            select(AuditLog.question, AuditLog.search_question).order_by(AuditLog.id)
        ).all()
    assert [tuple(row) for row in rows] == [
        ("출장비 정산 기한은?", None),
        ("해외 출장도?", REWRITTEN),
    ]


def test_replay_of_a_follow_up_uses_the_rewritten_question(
    client: Client, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    api = client()
    first, _ = _ask(api, {"question": "출장비 정산 기한은?"})
    _ask(
        api,
        {
            "question": "해외 출장도?",
            "conversation_id": int(first["x-conversation-id"]),
            "previous": ["출장비 정산 기한은?"],
        },
    )
    with Session(db_engine) as session:
        audit_id = session.scalars(select(AuditLog.id).order_by(AuditLog.id.desc())).first()

    assert replay.main([str(audit_id)], engine=db_engine) == 0
    assert "요청 해시 일치" in capsys.readouterr().out


def test_text_off_policy_drops_the_rewritten_question_from_the_audit_log(
    client: Client, db_engine: Engine
) -> None:
    api = client(audit=AuditPolicy(store_text=False))
    _ask(api, {"question": "해외 출장도?", "previous": ["출장비 정산 기한은?"]})

    with Session(db_engine) as session:
        row = session.execute(select(AuditLog.question, AuditLog.search_question)).one()
    assert tuple(row) == (None, None)


def test_someone_elses_conversation_is_404_and_previous_is_limited(client: Client) -> None:
    api = client()
    boss, _ = _ask(api, {"question": "임원 성과급은?"}, user="boss")
    conversation = boss["x-conversation-id"]

    stolen = api.post(
        "/ask",
        json={"question": "그럼 상한은?", "conversation_id": int(conversation)},
        headers=_as("kim"),
    )
    too_many = api.post(
        "/ask", json={"question": "q", "previous": ["a", "b", "c", "d", "e"]}, headers=_as("kim")
    )

    assert stolen.status_code == 404
    assert too_many.status_code == 422
    assert api.get(f"/api/conversations/{conversation}", headers=_as("kim")).status_code == 404
    assert api.delete(f"/api/conversations/{conversation}", headers=_as("kim")).status_code == 404


def test_history_off_still_rewrites_but_keeps_no_conversation(
    client: Client, llm: TwoPromptLLM
) -> None:
    api = client(history_days=0)
    headers, done = _ask(api, {"question": "해외 출장도?", "previous": ["출장비 정산 기한은?"]})

    assert "x-conversation-id" not in headers
    assert done["search_question"] == REWRITTEN
    assert api.get("/api/conversations", headers=_as("kim")).json() == {
        "items": [],
        "next_before": None,
    }
    assert (
        api.post(
            "/ask", json={"question": "q", "conversation_id": 1}, headers=_as("kim")
        ).status_code
        == 200
    )  # 기록을 두지 않는 설치에서는 대화 id를 무시한다


def test_deleting_a_conversation_and_paging(client: Client) -> None:
    api = client()
    ids = []
    for question in ("첫 대화", "둘째 대화", "셋째 대화"):
        headers, _ = _ask(api, {"question": question})
        ids.append(int(headers["x-conversation-id"]))

    first = api.get("/api/conversations?limit=2", headers=_as("kim")).json()
    rest = api.get(
        "/api/conversations",
        params={"limit": 2, "before": first["next_before"]},
        headers=_as("kim"),
    ).json()

    assert [i["title"] for i in first["items"]] == ["셋째 대화", "둘째 대화"]
    assert [i["title"] for i in rest["items"]] == ["첫 대화"]
    assert rest["next_before"] is None
    assert api.delete(f"/api/conversations/{ids[0]}", headers=_as("kim")).status_code == 204
    assert api.get(f"/api/conversations/{ids[0]}", headers=_as("kim")).status_code == 404
    assert api.get("/api/conversations").status_code == 401
