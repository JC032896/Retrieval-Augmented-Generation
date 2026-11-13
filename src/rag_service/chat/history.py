"""직원의 대화 기록과 근거 문단 보기.

- 기록은 본인 것만 보고 지운다 (로그인 id로 거른다). 다른 사람 기록은 "없음"과 같게 다룬다.
- 보관 기간(keep_days)이 지난 기록은 보이지 않고, 새 기록을 넣을 때 지운다. 0이면 저장하지 않는다.
- 기록을 다시 열 때 그 답의 근거 문서(LLM에 보낸 문서)를 지금도 모두 볼 수 있는지 확인한다.
  권한을 잃었거나 문서가 지워졌으면 답을 가린다 (지난 답이 권한 밖 내용을 다시 보여 주지 않게).
- 근거 문단은 검색과 같은 권한 필터(retrieval.access)로 읽는다. 권한이 없으면 없는 것과 같다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from rag_service.chat.models import ChatTurn
from rag_service.db.models import Chunk, Document
from rag_service.retrieval.access import Viewer, access_filter


@dataclass(frozen=True)
class TurnSummary:
    id: int
    created_at: datetime
    question: str
    outcome: str


@dataclass(frozen=True)
class TurnDetail:
    id: int
    created_at: datetime
    question: str
    outcome: str
    hidden: bool  # 근거 문서 중 지금 볼 수 없는 것이 있어 답을 가렸다
    result: dict[str, Any] | None  # hidden이면 None


@dataclass(frozen=True)
class Passage:
    chunk_id: int
    file: str
    title: str
    section: str | None
    page: int | None
    content: str
    status: str  # current | superseded


def _cutoff(keep_days: int, now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=keep_days)


def save_turn(
    session: Session,
    *,
    request_id: str,
    user_login: str,
    question: str,
    outcome: str,
    result: dict[str, Any],
    context_files: Iterable[str],
    keep_days: int,
    now: datetime | None = None,
) -> int | None:
    """기록을 넣고 id를 돌려준다. keep_days가 0이면 저장하지 않는다. 커밋은 호출하는 쪽에서 한다."""
    if keep_days < 1:
        return None
    session.execute(delete(ChatTurn).where(ChatTurn.created_at < _cutoff(keep_days, now)))
    turn = ChatTurn(
        request_id=request_id,
        user_login=user_login,
        question=question,
        outcome=outcome,
        result=result,
        context_files=list(dict.fromkeys(context_files)),
    )
    if now is not None:
        turn.created_at = now
    session.add(turn)
    session.flush()
    return turn.id


def _own(login: str, keep_days: int, now: datetime | None) -> ColumnElement[bool]:
    return (ChatTurn.user_login == login) & (ChatTurn.created_at >= _cutoff(keep_days, now))


def list_turns(
    session: Session,
    login: str,
    *,
    keep_days: int,
    before: int | None = None,
    limit: int = 30,
    now: datetime | None = None,
) -> list[TurnSummary]:
    """최근 것부터. before를 주면 그 id보다 오래된 것만 (더 보기)."""
    if keep_days < 1:
        return []
    query = select(ChatTurn).where(_own(login, keep_days, now))
    if before is not None:
        query = query.where(ChatTurn.id < before)
    rows = session.scalars(query.order_by(ChatTurn.id.desc()).limit(limit))
    return [TurnSummary(t.id, t.created_at, t.question, t.outcome) for t in rows]


def visible_files(session: Session, viewer: Viewer, files: Iterable[str]) -> set[str]:
    """files 중 viewer가 지금 볼 수 있는 조각이 하나라도 있는 문서."""
    wanted = list(set(files))
    if not wanted:
        return set()
    query = (
        select(Document.source_path)
        .join(Chunk, Chunk.document_id == Document.id)
        .where(Document.source_path.in_(wanted), access_filter(viewer))
        .distinct()
    )
    return set(session.scalars(query))


def get_turn(
    session: Session,
    login: str,
    turn_id: int,
    *,
    viewer: Viewer,
    keep_days: int,
    now: datetime | None = None,
) -> TurnDetail | None:
    if keep_days < 1:
        return None
    turn = session.scalars(
        select(ChatTurn).where(ChatTurn.id == turn_id, _own(login, keep_days, now))
    ).one_or_none()
    if turn is None:
        return None
    hidden = not set(turn.context_files) <= visible_files(session, viewer, turn.context_files)
    return TurnDetail(
        id=turn.id,
        created_at=turn.created_at,
        question=turn.question,
        outcome=turn.outcome,
        hidden=hidden,
        result=None if hidden else turn.result,
    )


def delete_turn(session: Session, login: str, turn_id: int) -> bool:
    """본인 기록 하나를 지운다. 없거나 남의 것이면 False. 커밋은 호출하는 쪽에서 한다."""
    deleted = session.execute(
        delete(ChatTurn)
        .where(ChatTurn.id == turn_id, ChatTurn.user_login == login)
        .returning(ChatTurn.id)
    )
    return deleted.first() is not None


def delete_all(session: Session, login: str) -> int:
    """본인 기록을 모두 지우고 지운 개수를 돌려준다. 커밋은 호출하는 쪽에서 한다."""
    deleted = session.execute(
        delete(ChatTurn).where(ChatTurn.user_login == login).returning(ChatTurn.id)
    )
    return len(deleted.all())


def get_passage(session: Session, viewer: Viewer, chunk_id: int) -> Passage | None:
    """근거 조각 하나. 없거나 viewer가 볼 수 없으면 None (둘을 구별하지 않는다)."""
    row = session.execute(
        select(
            Chunk.id,
            Document.source_path,
            Document.title,
            Chunk.section,
            Chunk.page,
            Chunk.content,
            Document.status,
        )
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id == chunk_id, access_filter(viewer))
    ).one_or_none()
    if row is None:
        return None
    return Passage(*row)
