"""대화 기록과 근거 문단: 본인 것만, 보관 기간, 권한이 바뀐 지난 답 가리기, 근거 문단의 권한 필터.

kim(개발팀 사원, 등급 1)은 출장비 규정만, boss(경영진 임원, 등급 3)는 임원 보수까지 볼 수 있다.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

from rag_service.api.auth import CurrentUser
from rag_service.chat.history import (
    delete_all,
    delete_turn,
    get_passage,
    get_turn,
    list_turns,
    save_turn,
)
from rag_service.chat.models import ChatTurn
from rag_service.corpus import load_corpus
from rag_service.db.models import Chunk, Document
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.api import ACL, DOCS, ORG
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

KIM = CurrentUser("kim", "김사원", "개발팀", "사원", 1)
BOSS = CurrentUser("boss", "대표", "경영진", "임원", 3)
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
RESULT: dict[str, Any] = {"text": "7일 이내입니다. [1]", "refused": False, "citations": []}


@pytest.fixture
def session(tmp_path: Path, db_engine: Engine, db_session: Session) -> Session:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE chat_turns RESTART IDENTITY"))
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


def _save(
    session: Session,
    login: str = "kim",
    *,
    question: str = "출장비 정산 기한은?",
    files: tuple[str, ...] = ("travel.md",),
    keep_days: int = 90,
    now: datetime = NOW,
) -> int | None:
    return save_turn(
        session,
        request_id="r",
        user_login=login,
        question=question,
        outcome="answered",
        result=RESULT,
        context_files=files,
        keep_days=keep_days,
        now=now,
    )


def _chunk_id(session: Session, file: str) -> int:
    query = select(Chunk.id).join(Document).where(Document.source_path == file).limit(1)
    return session.scalars(query).one()


def test_lists_only_own_turns_newest_first_with_paging(session: Session) -> None:
    first = _save(session, question="첫 질문")
    second = _save(session, question="둘째 질문")
    _save(session, "boss", question="대표 질문")
    third = _save(session, question="셋째 질문")

    page = list_turns(session, "kim", keep_days=90, limit=2, now=NOW)
    older = list_turns(session, "kim", keep_days=90, before=page[-1].id, limit=2, now=NOW)

    assert [t.id for t in page] == [third, second]
    assert [(t.id, t.question, t.outcome) for t in older] == [(first, "첫 질문", "answered")]


def test_context_files_are_stored_once_in_order(session: Session) -> None:
    turn_id = _save(session, files=("travel.md", "pay.md", "travel.md"))

    stored = session.get(ChatTurn, turn_id)
    assert stored is not None
    assert stored.context_files == ["travel.md", "pay.md"]


def test_zero_keep_days_stores_and_shows_nothing(session: Session) -> None:
    assert _save(session, keep_days=0) is None
    kept = _save(session)
    assert kept is not None

    assert list_turns(session, "kim", keep_days=0, now=NOW) == []
    assert get_turn(session, "kim", kept, viewer=KIM, keep_days=0, now=NOW) is None


def test_expired_turns_are_hidden_and_removed_on_next_save(session: Session) -> None:
    old = _save(session, question="오래된 질문", now=NOW - timedelta(days=91))
    assert old is not None

    assert list_turns(session, "kim", keep_days=90, now=NOW) == []
    assert get_turn(session, "kim", old, viewer=KIM, keep_days=90, now=NOW) is None

    _save(session, "boss")  # 누가 넣든 기간이 지난 기록을 지운다
    count = session.scalar(select(func.count()).select_from(ChatTurn))
    assert count == 1
    assert session.get(ChatTurn, old) is None


def test_turn_shows_answer_while_every_source_is_still_visible(session: Session) -> None:
    turn_id = _save(session)
    assert turn_id is not None

    turn = get_turn(session, "kim", turn_id, viewer=KIM, keep_days=90, now=NOW)

    assert turn is not None
    assert (turn.question, turn.hidden, turn.result) == ("출장비 정산 기한은?", False, RESULT)


def test_answer_is_hidden_when_a_source_is_no_longer_visible(session: Session) -> None:
    # kim이 예전에 boss 권한의 문서를 근거로 답을 받았다고 가정한다 (그 뒤 권한을 잃음)
    turn_id = _save(session, files=("travel.md", "pay.md"))
    assert turn_id is not None

    turn = get_turn(session, "kim", turn_id, viewer=KIM, keep_days=90, now=NOW)

    assert turn is not None
    assert (turn.question, turn.hidden, turn.result) == ("출장비 정산 기한은?", True, None)


def test_answer_is_hidden_when_a_source_was_deleted(session: Session) -> None:
    turn_id = _save(session, "boss", files=("pay.md",))
    assert turn_id is not None
    shown = get_turn(session, "boss", turn_id, viewer=BOSS, keep_days=90, now=NOW)

    session.execute(delete(Document).where(Document.source_path == "pay.md"))
    hidden = get_turn(session, "boss", turn_id, viewer=BOSS, keep_days=90, now=NOW)

    assert shown is not None and shown.hidden is False
    assert hidden is not None and (hidden.hidden, hidden.result) == (True, None)


def test_refusal_without_sources_stays_visible(session: Session) -> None:
    turn_id = _save(session, files=())
    assert turn_id is not None

    turn = get_turn(session, "kim", turn_id, viewer=KIM, keep_days=90, now=NOW)

    assert turn is not None and turn.hidden is False


def test_other_peoples_turns_cannot_be_read_or_deleted(session: Session) -> None:
    boss_turn = _save(session, "boss")
    assert boss_turn is not None

    assert get_turn(session, "kim", boss_turn, viewer=KIM, keep_days=90, now=NOW) is None
    assert delete_turn(session, "kim", boss_turn) is False
    assert delete_turn(session, "boss", boss_turn) is True
    assert delete_turn(session, "boss", boss_turn) is False


def test_delete_all_removes_only_own_turns(session: Session) -> None:
    _save(session)
    _save(session)
    _save(session, "boss")

    assert delete_all(session, "kim") == 2
    assert list_turns(session, "kim", keep_days=90, now=NOW) == []
    assert len(list_turns(session, "boss", keep_days=90, now=NOW)) == 1


def test_passage_uses_the_same_permission_rule_as_search(session: Session) -> None:
    travel = _chunk_id(session, "travel.md")
    pay = _chunk_id(session, "pay.md")

    passage = get_passage(session, KIM, travel)

    assert passage is not None
    assert (passage.file, passage.title, passage.status) == ("travel.md", "출장비 규정", "current")
    assert "7일 이내" in passage.content
    assert get_passage(session, KIM, pay) is None  # 권한 없음과 없는 문단을 구별하지 않는다
    assert get_passage(session, KIM, 999_999) is None
    boss_view = get_passage(session, BOSS, pay)
    assert boss_view is not None and "300%" in boss_view.content
