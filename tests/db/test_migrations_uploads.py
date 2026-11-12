"""마이그레이션 0009: 문서 출처(origin)·관리 부서 제약과 변경 이력 테이블의 역할별 권한."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from tests.fixtures.db import db_engine, db_session

__all__ = ["db_engine", "db_session"]

INSERT_DOCUMENT = (
    "INSERT INTO documents (title, source_path, security_level, origin, owner_department) "
    "VALUES ('t', :path, 1, :origin, :owner)"
)
INSERT_CHANGE = (
    "INSERT INTO document_changes (document_id, source_path, action, actor_login) "
    "VALUES (1, 'upload/a.md', :action, 'lee')"
)


@pytest.fixture
def connection(db_engine: Engine, db_session: Session) -> Iterator[Connection]:
    """끝나면 되돌리는 연결 (테스트 DB 계정은 SET ROLE을 할 수 있는 관리자)."""
    with db_engine.connect() as conn:
        conn.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
        yield conn
        conn.rollback()


def test_existing_documents_default_to_folder_origin(connection: Connection) -> None:
    connection.execute(
        text("INSERT INTO documents (title, source_path, security_level) VALUES ('t', 'a.md', 1)")
    )

    row = connection.execute(text("SELECT origin, owner_department FROM documents")).one()
    assert tuple(row) == ("folder", None)


@pytest.mark.parametrize(
    ("origin", "owner"),
    [("upload", None), ("email", "개발팀")],  # 올린 문서에는 관리 부서가 있어야 한다
)
def test_origin_and_owner_constraints(
    connection: Connection, origin: str, owner: str | None
) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(
            text(INSERT_DOCUMENT), {"path": "upload/a.md", "origin": origin, "owner": owner}
        )


def test_change_action_is_checked(connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(text(INSERT_CHANGE), {"action": "rename"})


def test_app_can_add_and_read_changes_but_not_edit_or_delete(connection: Connection) -> None:
    connection.execute(text("SET LOCAL ROLE rag_app"))
    connection.execute(text(INSERT_CHANGE), {"action": "upload"})

    assert connection.scalar(text("SELECT count(*) FROM document_changes")) == 1
    for statement in (
        "UPDATE document_changes SET actor_login = 'x'",
        "DELETE FROM document_changes",
    ):
        connection.execute(text("SAVEPOINT attempt"))
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.execute(text(statement))
        connection.execute(text("ROLLBACK TO SAVEPOINT attempt"))


def test_auditor_can_read_changes_only(connection: Connection) -> None:
    connection.execute(text(INSERT_CHANGE), {"action": "access"})
    connection.execute(text("SET LOCAL ROLE rag_auditor"))

    assert connection.scalar(text("SELECT action FROM document_changes")) == "access"
    with pytest.raises(DBAPIError, match="permission denied"):
        connection.execute(text(INSERT_CHANGE), {"action": "upload"})
