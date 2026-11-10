"""수집 때 users 테이블을 org.yaml의 사용자 목록과 맞추는지 검사한다."""

from dataclasses import replace
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.corpus import load_corpus
from rag_service.db.models import User
from rag_service.ingest.pipeline import sync_users
from tests.fixtures.db import db_engine, db_session

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _users(session: Session) -> dict[str, tuple[str, str, str, int]]:
    return {
        user.login: (user.name, user.department, user.role, user.clearance_level)
        for user in session.scalars(select(User))
    }


def test_sync_adds_every_user_in_org_yaml(db_session: Session) -> None:
    corpus = load_corpus(SAMPLES)

    count = sync_users(db_session, corpus)

    users = _users(db_session)
    assert count == len(corpus.org.users) == len(users)
    assert users["kim"] == ("김사원", "개발팀", "사원", 1)


def test_resync_updates_changed_users_and_removes_missing_ones(db_session: Session) -> None:
    corpus = load_corpus(SAMPLES)
    sync_users(db_session, corpus)
    kim = corpus.user("kim").model_copy(update={"role": "팀장", "clearance_level": 2})
    changed = replace(corpus, org=corpus.org.model_copy(update={"users": [kim]}))

    count = sync_users(db_session, changed)

    assert count == 1
    assert _users(db_session) == {"kim": ("김사원", "개발팀", "팀장", 2)}
