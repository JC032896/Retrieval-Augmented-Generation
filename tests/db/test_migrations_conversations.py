"""마이그레이션 0012: 대화 테이블의 역할별 권한, 기존 기록을 대화로 옮기기, 다시 쓴 질문 열."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.fixtures.db import db_engine, db_session, migrate

__all__ = ["db_engine", "db_session"]

INSERT_CONVERSATION = "INSERT INTO chat_conversations (user_login, title) VALUES ('kim', '출장비')"


@pytest.fixture
def connection(db_engine: Engine, db_session: Session) -> Iterator[Connection]:
    """끝나면 되돌리는 연결 (테스트 DB 계정은 SET ROLE을 할 수 있는 관리자)."""
    with db_engine.connect() as conn:
        conn.execute(text("TRUNCATE chat_turns, chat_conversations RESTART IDENTITY"))
        yield conn
        conn.rollback()


def _denied(connection: Connection, statement: str) -> None:
    connection.execute(text("SAVEPOINT attempt"))
    with pytest.raises(DBAPIError, match="permission denied"):
        connection.execute(text(statement))
    connection.execute(text("ROLLBACK TO SAVEPOINT attempt"))


def test_app_can_add_read_touch_and_delete_but_not_retitle(connection: Connection) -> None:
    connection.execute(text("SET LOCAL ROLE rag_app"))
    connection.execute(text(INSERT_CONVERSATION))
    connection.execute(text("UPDATE chat_conversations SET updated_at = now()"))

    assert connection.scalar(text("SELECT title FROM chat_conversations")) == "출장비"
    _denied(connection, "UPDATE chat_conversations SET title = '바꾼 제목'")
    _denied(connection, "UPDATE chat_conversations SET user_login = 'boss'")
    connection.execute(text("DELETE FROM chat_conversations"))
    assert connection.scalar(text("SELECT count(*) FROM chat_conversations")) == 0


def test_auditor_cannot_read_conversations(connection: Connection) -> None:
    connection.execute(text(INSERT_CONVERSATION))
    connection.execute(text("SET LOCAL ROLE rag_auditor"))

    _denied(connection, "SELECT title FROM chat_conversations")


def test_audit_log_keeps_the_rewritten_question(connection: Connection) -> None:
    columns = connection.scalars(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'audit_log' AND column_name = 'search_question'"
        )
    ).all()

    assert columns == ["search_question"]


def test_existing_turns_become_one_conversation_each(
    db_engine: Engine, db_session: Session
) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE chat_turns, chat_conversations RESTART IDENTITY"))
    migrate(db_engine, "0011", downgrade=True)
    try:
        with db_engine.begin() as conn:
            for question in ("재택근무는 주 몇 회야?", "출장비 정산 기한은?"):
                conn.execute(
                    text(
                        "INSERT INTO chat_turns (request_id, user_login, question, outcome, "
                        "result, context_files) VALUES ('r', 'kim', :q, 'answered', '{}', '{}')"
                    ),
                    {"q": question},
                )
        migrate(db_engine)
        with db_engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT t.id, t.conversation_id, c.title, c.user_login FROM chat_turns t "
                    "JOIN chat_conversations c ON c.id = t.conversation_id ORDER BY t.id"
                )
            ).all()
            new_id = conn.execute(
                text(
                    "INSERT INTO chat_conversations (user_login, title) "
                    "VALUES ('kim', 'x') RETURNING id"
                )
            ).scalar_one()
    finally:
        migrate(db_engine)
        with db_engine.begin() as conn:
            conn.execute(text("TRUNCATE chat_turns, chat_conversations RESTART IDENTITY"))

    assert [tuple(row) for row in rows] == [
        (1, 1, "재택근무는 주 몇 회야?", "kim"),
        (2, 2, "출장비 정산 기한은?", "kim"),
    ]
    assert new_id == 3  # 옮긴 대화 id 다음부터 이어진다
