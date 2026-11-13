"""마이그레이션 0011: 대화 기록 테이블의 결과 제약과 역할별 권한.

앱 계정은 넣고 읽고 지울 수 있지만 고칠 수 없다. 감사 담당 계정은 대화 기록에 권한이 없다
(질문 원문은 감사 기록에 따로 남는다).
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.fixtures.db import db_engine, db_session

__all__ = ["db_engine", "db_session"]

INSERT_TURN = (
    "INSERT INTO chat_turns (request_id, user_login, question, outcome, result, context_files) "
    "VALUES ('r1', 'kim', '출장비 정산 기한은?', :outcome, '{}', '{travel.md}')"
)


@pytest.fixture
def connection(db_engine: Engine, db_session: Session) -> Iterator[Connection]:
    """끝나면 되돌리는 연결 (테스트 DB 계정은 SET ROLE을 할 수 있는 관리자)."""
    with db_engine.connect() as conn:
        conn.execute(text("TRUNCATE chat_turns RESTART IDENTITY"))
        yield conn
        conn.rollback()


@pytest.mark.parametrize("outcome", ["error", "cancelled"])
def test_only_answered_or_refused_turns_are_kept(connection: Connection, outcome: str) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(text(INSERT_TURN), {"outcome": outcome})


def test_app_can_add_read_and_delete_but_not_edit(connection: Connection) -> None:
    connection.execute(text("SET LOCAL ROLE rag_app"))
    connection.execute(text(INSERT_TURN), {"outcome": "answered"})
    connection.execute(text(INSERT_TURN), {"outcome": "refused"})

    assert connection.scalar(text("SELECT count(*) FROM chat_turns")) == 2
    connection.execute(text("SAVEPOINT attempt"))
    with pytest.raises(DBAPIError, match="permission denied"):
        connection.execute(text("UPDATE chat_turns SET question = '바꾼 질문'"))
    connection.execute(text("ROLLBACK TO SAVEPOINT attempt"))
    connection.execute(text("DELETE FROM chat_turns WHERE outcome = 'refused'"))
    assert connection.scalar(text("SELECT count(*) FROM chat_turns")) == 1


def test_auditor_cannot_read_chat_history(connection: Connection) -> None:
    connection.execute(text(INSERT_TURN), {"outcome": "answered"})
    connection.execute(text("SET LOCAL ROLE rag_auditor"))

    with pytest.raises(DBAPIError, match="permission denied"):
        connection.execute(text("SELECT question FROM chat_turns"))
