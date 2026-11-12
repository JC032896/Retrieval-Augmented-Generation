"""관리 화면 최종 검토(B-6)로 바꾼 서버 동작.

- 대시보드 '오늘 질문': 회사 전체 오늘 질문 수·질문한 사람 수·비용
  (마이그레이션 0010 함수. 앱 계정은 감사 기록을 읽지 못하고 숫자만 받는다)
- 문서 이력은 문서 단위: 같은 경로에 지웠다가 다시 올린 문서에 이전 문서의 이력을
  붙이지 않는다
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from rag_service.api.admin import Admin, AdminServices, status
from rag_service.api.auth import CurrentUser
from rag_service.api.limits import UsageLimits, day_start
from rag_service.api.roles import AdminRole
from rag_service.db.changes import DocumentChange
from rag_service.db.models import Document, User
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.ingest.uploads import Access, add_upload, delete_upload, history
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

HAN = Admin(CurrentUser("han", "한임원", "경영진", "임원", 3), frozenset({AdminRole.ADMIN}))
INSERT = text(
    "INSERT INTO audit_log (created_at, request_id, user_login, user_department, user_role, "
    "user_clearance_level, question_sha256, question_chars, outcome, context_files, cited_files, "
    "retrieval_ms, total_ms, cost_usd) VALUES (:at, :rid, :login, '개발팀', '사원', 1, 'q', 1, "
    "'answered', '{}', '{}', 1, 1, :cost)"
)


@pytest.fixture
def audit_rows(db_engine: Engine, db_session: Session) -> datetime:
    """오늘(한국 시간) 3건(2명, $0.75)과 어제 1건을 넣는다. 오늘 0시를 돌려준다."""
    today = day_start(datetime.now(UTC), 9)
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log, chunk_snapshots RESTART IDENTITY"))
        for i, (at, login, cost) in enumerate(
            [
                (today + timedelta(minutes=1), "kim", 0.25),
                (today + timedelta(minutes=2), "kim", 0.25),
                (today + timedelta(minutes=3), "lee", 0.25),
                (today - timedelta(minutes=1), "park", 9.0),
            ]
        ):
            connection.execute(INSERT, {"at": at, "rid": f"u-{i}", "login": login, "cost": cost})
    return today


def test_status_reports_todays_company_usage(db_engine: Engine, audit_rows: datetime) -> None:
    services = AdminServices(
        sessions=sessionmaker(db_engine),
        audit_sessions=None,
        authenticator=None,
        limits=UsageLimits(daily_budget_usd=20.0, utc_offset_hours=9),
    )

    usage = status(HAN, services).usage

    assert usage is not None
    assert (usage.requests, usage.users, usage.cost_usd) == (3, 2, 0.75)
    assert usage.since == audit_rows


def test_app_role_gets_only_the_numbers(db_engine: Engine, audit_rows: datetime) -> None:
    with db_engine.connect() as connection:
        connection.execute(text("SET ROLE rag_app"))
        row = connection.execute(
            text("SELECT * FROM llm_usage_summary_since(:since)"), {"since": audit_rows}
        ).one()
        assert tuple(row) == (3, 2, 0.75)
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.execute(text("SELECT question FROM audit_log"))
        connection.rollback()


def test_auditor_role_cannot_call_the_summary(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        connection.execute(text("SET ROLE rag_auditor"))
        with pytest.raises(DBAPIError, match="permission denied"):
            connection.execute(text("SELECT * FROM llm_usage_summary_since(now())"))
        connection.rollback()


def test_history_starts_at_the_latest_upload_of_the_path(
    db_engine: Engine, db_session: Session, tmp_path: Path
) -> None:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
    db_session.add(
        User(login="lee", name="이팀장", department="개발팀", role="팀장", clearance_level=2)
    )
    db_session.commit()
    tokenizer = KoreanTokenizer()

    def upload() -> None:
        staged = add_upload(
            db_session,
            filename="회의실.md",
            data="# 회의실\n\n포털에서 예약한다.\n".encode(),
            access=Access("회의실", 1, ("개발팀",), ()),
            owner_department="개발팀",
            actor="lee",
            upload_dir=tmp_path,
            embedder=FakeEmbedder(),
            tokenizer=tokenizer,
        )
        db_session.commit()
        staged.finalize()

    upload()
    first = history(db_session, "upload/회의실.md")
    document = db_session.scalars(select(Document)).one()
    staged = delete_upload(db_session, document, "lee", tmp_path)
    db_session.commit()
    staged.finalize()
    upload()

    assert [c.action for c in first] == ["upload"]
    # 다시 올린 문서의 이력에는 이전 문서의 삭제가 붙지 않는다
    assert [c.action for c in history(db_session, "upload/회의실.md")] == ["upload"]
    rows = db_session.scalars(select(DocumentChange.action).order_by(DocumentChange.id)).all()
    assert rows == ["upload", "delete", "upload"]  # 기록 자체는 모두 남는다


def test_history_of_a_path_without_uploads_has_no_cut(
    db_engine: Engine, db_session: Session
) -> None:
    """올린 기록이 없는 경로(폴더 문서 등)는 자를 기준이 없으니 있는 기록을 그대로 돌려준다."""
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE document_changes RESTART IDENTITY"))
    db_session.add(
        DocumentChange(
            document_id=1,
            source_path="rule.md",
            action="access",
            actor_login="han",
            before=None,
            after=None,
        )
    )
    db_session.commit()

    assert [c.action for c in history(db_session, "rule.md")] == ["access"]
    assert history(db_session, "없는 경로.md") == []
