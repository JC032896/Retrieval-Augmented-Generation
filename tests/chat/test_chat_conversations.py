"""대화 (마이그레이션 0012): 본인 것만, 마지막 질문 시각 순, 보관 기간, 질문마다 가리기.

kim(개발팀 사원, 등급 1)은 출장비 규정만, boss(경영진 임원, 등급 3)는 임원 보수까지 볼 수 있다.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from rag_service.api.auth import CurrentUser
from rag_service.chat.history import (
    delete_all,
    delete_conversation,
    get_conversation,
    list_conversations,
    own_conversation,
    save_turn,
    start_conversation,
)
from rag_service.chat.models import ChatConversation, ChatTurn
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.api import ACL, DOCS, ORG
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

KIM = CurrentUser("kim", "김사원", "개발팀", "사원", 1)
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
RESULT: dict[str, Any] = {"text": "7일 이내입니다. [1]", "refused": False, "citations": []}


@pytest.fixture
def session(tmp_path: Path, db_engine: Engine, db_session: Session) -> Session:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE chat_turns, chat_conversations RESTART IDENTITY"))
    (tmp_path / "docs").mkdir()
    (tmp_path / "org.yaml").write_text(ORG, encoding="utf-8")
    (tmp_path / "acl.yaml").write_text(ACL, encoding="utf-8")
    for name, body in DOCS.items():
        (tmp_path / "docs" / name).write_text(body, encoding="utf-8")
    ingest_corpus(
        db_session, load_corpus(tmp_path), embedder=FakeEmbedder(), tokenizer=KoreanTokenizer()
    )
    db_session.commit()
    return db_session


def _turn(
    session: Session,
    conversation: int | None,
    question: str,
    *,
    login: str = "kim",
    files: tuple[str, ...] = ("travel.md",),
    at: datetime = NOW,
    search_question: str | None = None,
) -> int | None:
    return save_turn(
        session,
        request_id="r",
        user_login=login,
        question=question,
        outcome="answered",
        result=RESULT,
        context_files=files,
        keep_days=90,
        now=at,
        conversation_id=conversation,
        search_question=search_question,
    )


def test_turns_join_a_conversation_and_move_it_to_the_top(session: Session) -> None:
    first = start_conversation(session, "kim", title="재택근무는 주 몇 회야?", now=NOW)
    _turn(session, first, "재택근무는 주 몇 회야?")
    second = start_conversation(session, "kim", title="출장비 정산 기한은?", now=NOW)
    _turn(session, second, "출장비 정산 기한은?", at=NOW + timedelta(minutes=1))
    _turn(
        session,
        first,
        "그럼 계약직은?",
        at=NOW + timedelta(minutes=2),
        search_question="계약직의 재택근무는 주 몇 회인가?",
    )

    listed = list_conversations(session, "kim", keep_days=90, now=NOW)

    assert [(c.id, c.title, c.turns) for c in listed] == [
        (first, "재택근무는 주 몇 회야?", 2),
        (second, "출장비 정산 기한은?", 1),
    ]
    assert listed[0].updated_at == NOW + timedelta(minutes=2)
    older = list_conversations(session, "kim", keep_days=90, before=listed[0].updated_at, now=NOW)
    assert [c.id for c in older] == [second]
    found = get_conversation(session, "kim", first, viewer=KIM, keep_days=90, now=NOW)
    assert found is not None
    title, turns = found
    assert title == "재택근무는 주 몇 회야?"
    assert [(t.question, t.search_question) for t in turns] == [
        ("재택근무는 주 몇 회야?", None),
        ("그럼 계약직은?", "계약직의 재택근무는 주 몇 회인가?"),
    ]


def test_empty_conversations_are_not_listed_and_titles_are_cut(session: Session) -> None:
    start_conversation(session, "kim", title="가" * 300, now=NOW)

    assert list_conversations(session, "kim", keep_days=90, now=NOW) == []
    stored = session.scalars(select(ChatConversation.title)).one()
    assert len(stored) == 200


def test_conversations_are_private(session: Session) -> None:
    boss = start_conversation(session, "boss", title="임원 보수", now=NOW)
    _turn(session, boss, "임원 보수", login="boss", files=("pay.md",))

    assert own_conversation(session, "boss", boss, keep_days=90, now=NOW) is True
    assert own_conversation(session, "kim", boss, keep_days=90, now=NOW) is False
    assert get_conversation(session, "kim", boss, viewer=KIM, keep_days=90, now=NOW) is None
    assert list_conversations(session, "kim", keep_days=90, now=NOW) == []
    assert delete_conversation(session, "kim", boss) is False


def test_each_turn_is_hidden_on_its_own_when_its_sources_are_no_longer_visible(
    session: Session,
) -> None:
    conversation = start_conversation(session, "kim", title="출장비", now=NOW)
    _turn(session, conversation, "출장비 정산 기한은?")
    _turn(session, conversation, "임원 보수도?", files=("travel.md", "pay.md"))

    found = get_conversation(session, "kim", conversation, viewer=KIM, keep_days=90, now=NOW)

    assert found is not None
    _, turns = found
    assert [(t.hidden, t.result is None) for t in turns] == [(False, False), (True, True)]
    assert turns[1].question == "임원 보수도?"  # 질문은 본인이 쓴 글이라 그대로 보인다


def test_expired_conversations_disappear_and_are_removed_on_next_save(session: Session) -> None:
    old = start_conversation(session, "kim", title="오래된 대화", now=NOW - timedelta(days=91))
    _turn(session, old, "오래된 대화", at=NOW - timedelta(days=91))
    keep = start_conversation(session, "kim", title="지금 대화", now=NOW)

    assert own_conversation(session, "kim", old, keep_days=90, now=NOW) is False
    assert own_conversation(session, "kim", old, keep_days=0, now=NOW) is False
    assert list_conversations(session, "kim", keep_days=0, now=NOW) == []
    _turn(session, keep, "지금 대화")
    _turn(session, None, "대화 없이 남은 이전 방식 기록")

    remaining = set(session.scalars(select(ChatConversation.id)))
    assert remaining == {keep}


def test_deleting_a_conversation_deletes_its_turns(session: Session) -> None:
    conversation = start_conversation(session, "kim", title="출장비", now=NOW)
    _turn(session, conversation, "출장비 정산 기한은?")
    _turn(session, conversation, "해외 출장은?")
    other = start_conversation(session, "kim", title="다른 대화", now=NOW)
    _turn(session, other, "다른 대화")

    assert delete_conversation(session, "kim", conversation) is True
    session.flush()

    count = session.scalar(select(func.count()).select_from(ChatTurn))
    assert count == 1
    assert delete_conversation(session, "kim", conversation) is False


def test_delete_all_also_removes_conversations(session: Session) -> None:
    conversation = start_conversation(session, "kim", title="출장비", now=NOW)
    _turn(session, conversation, "출장비 정산 기한은?")
    boss = start_conversation(session, "boss", title="임원", now=NOW)
    _turn(session, boss, "임원", login="boss", files=("pay.md",))

    assert delete_all(session, "kim") == 1

    owners = list(session.scalars(select(ChatConversation.user_login)))
    assert owners == ["boss"]
