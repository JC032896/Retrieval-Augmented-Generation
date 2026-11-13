"""직원의 대화 기록과 근거 문단 보기.

- 기록은 본인 것만 보고 지운다 (로그인 id로 거른다). 다른 사람 기록은 "없음"과 같게 다룬다.
- 보관 기간(keep_days)이 지난 기록은 보이지 않고, 새 기록을 넣을 때 지운다. 0이면 저장하지 않는다.
- 기록을 다시 열 때 그 답의 근거 문서(LLM에 보낸 문서)를 지금도 모두 볼 수 있는지 확인한다.
  권한을 잃었거나 문서가 지워졌으면 답을 가린다 (지난 답이 권한 밖 내용을 다시 보여 주지 않게).
- 근거 문단은 검색과 같은 권한 필터(retrieval.access)로 읽는다. 권한이 없으면 없는 것과 같다.
- 대화(0012): 질문들은 대화에 속한다. 목록은 대화 단위이고, 마지막 질문 시각(updated_at)으로
  정렬하고 보관 기간도 그 시각으로 센다. 대화를 지우면 그 질문들도 지워진다.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session

from rag_service.chat.models import ChatConversation, ChatTurn
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
class ConversationSummary:
    id: int
    title: str
    updated_at: datetime
    turns: int


@dataclass(frozen=True)
class ConversationTurn:
    id: int
    created_at: datetime
    question: str
    search_question: str | None
    outcome: str
    hidden: bool
    result: dict[str, Any] | None


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
    conversation_id: int | None = None,
    search_question: str | None = None,
) -> int | None:
    """기록을 넣고 id를 돌려준다. keep_days가 0이면 저장하지 않는다. 커밋은 호출하는 쪽에서 한다.

    conversation_id를 주면 그 대화의 마지막 질문 시각도 고친다.
    """
    if keep_days < 1:
        return None
    cutoff = _cutoff(keep_days, now)
    session.execute(delete(ChatTurn).where(ChatTurn.created_at < cutoff))
    # 지난 대화도 지운다 (지금 질문을 넣는 대화는 남긴다. 다른 기기에서 막 이어 묻는 중일 수 있다)
    expired = delete(ChatConversation).where(ChatConversation.updated_at < cutoff)
    if conversation_id is not None:
        expired = expired.where(ChatConversation.id != conversation_id)
    session.execute(expired)
    turn = ChatTurn(
        request_id=request_id,
        user_login=user_login,
        question=question,
        outcome=outcome,
        result=result,
        context_files=list(dict.fromkeys(context_files)),
        conversation_id=conversation_id,
        search_question=search_question,
    )
    if now is not None:
        turn.created_at = now
    session.add(turn)
    session.flush()
    if conversation_id is not None:
        session.execute(
            update(ChatConversation)
            .where(ChatConversation.id == conversation_id)
            .values(updated_at=turn.created_at)
        )
    return turn.id


def start_conversation(
    session: Session, login: str, *, title: str, now: datetime | None = None
) -> int:
    """새 대화를 만들고 id를 돌려준다. 제목은 첫 질문. 커밋은 호출하는 쪽에서 한다."""
    conversation = ChatConversation(user_login=login, title=title[:200])
    if now is not None:
        conversation.created_at = conversation.updated_at = now
    session.add(conversation)
    session.flush()
    return conversation.id


def own_conversation(
    session: Session,
    login: str,
    conversation_id: int,
    *,
    keep_days: int,
    now: datetime | None = None,
) -> bool:
    """본인의, 보관 기간 안의 대화인가."""
    if keep_days < 1:
        return False
    query = select(ChatConversation.id).where(
        ChatConversation.id == conversation_id,
        ChatConversation.user_login == login,
        ChatConversation.updated_at >= _cutoff(keep_days, now),
    )
    return session.scalar(query) is not None


def list_conversations(
    session: Session,
    login: str,
    *,
    keep_days: int,
    before: datetime | None = None,
    limit: int = 30,
    now: datetime | None = None,
) -> list[ConversationSummary]:
    """질문이 하나라도 있는 본인 대화, 마지막 질문이 최근인 것부터.

    before를 주면 그보다 오래된 것만.
    """
    if keep_days < 1:
        return []
    turns = func.count(ChatTurn.id)
    query = (
        select(ChatConversation, turns)
        .join(ChatTurn, ChatTurn.conversation_id == ChatConversation.id)
        .where(
            ChatConversation.user_login == login,
            ChatConversation.updated_at >= _cutoff(keep_days, now),
        )
        .group_by(ChatConversation.id)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
        .limit(limit)
    )
    if before is not None:
        query = query.where(ChatConversation.updated_at < before)
    return [
        ConversationSummary(c.id, c.title, c.updated_at, count)
        for c, count in session.execute(query)
    ]


def get_conversation(
    session: Session,
    login: str,
    conversation_id: int,
    *,
    viewer: Viewer,
    keep_days: int,
    now: datetime | None = None,
) -> tuple[str, list[ConversationTurn]] | None:
    """대화 제목과 질문들(오래된 것부터). 질문마다 근거 문서를 지금도 볼 수 있는지 따로 확인한다."""
    if not own_conversation(session, login, conversation_id, keep_days=keep_days, now=now):
        return None
    title = session.scalars(
        select(ChatConversation.title).where(ChatConversation.id == conversation_id)
    ).one()
    rows = list(
        session.scalars(
            select(ChatTurn)
            .where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.id)
        )
    )
    files = {file for turn in rows for file in turn.context_files}
    visible = visible_files(session, viewer, files)
    turns = []
    for turn in rows:
        hidden = not set(turn.context_files) <= visible
        turns.append(
            ConversationTurn(
                id=turn.id,
                created_at=turn.created_at,
                question=turn.question,
                search_question=turn.search_question,
                outcome=turn.outcome,
                hidden=hidden,
                result=None if hidden else turn.result,
            )
        )
    return title, turns


def delete_conversation(session: Session, login: str, conversation_id: int) -> bool:
    """본인 대화와 그 질문들을 지운다. 없거나 남의 것이면 False. 커밋은 호출하는 쪽에서 한다."""
    deleted = session.execute(
        delete(ChatConversation)
        .where(ChatConversation.id == conversation_id, ChatConversation.user_login == login)
        .returning(ChatConversation.id)
    )
    return deleted.first() is not None


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
    count = len(deleted.all())
    session.execute(delete(ChatConversation).where(ChatConversation.user_login == login))
    return count


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
