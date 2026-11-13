"""직원 채팅 화면이 쓰는 API (/api). 질문 자체는 POST /ask(ask.py, SSE)로 한다.

- GET    /api/config            로그인 전에 읽는 공개 설정 (관리 화면과 같은 값)
- GET    /api/me                로그인한 사람, 관리 화면 역할(링크 표시용), 대화 기록 보관 기간
- GET    /api/history           본인 대화 기록 목록 (최근 것부터, before로 더 보기)
- GET    /api/history/{id}      기록 하나. 근거 문서를 지금 볼 수 없으면 답을 가린다
- DELETE /api/history/{id}      기록 하나 지우기
- DELETE /api/history           본인 기록 모두 지우기
- GET    /api/passages/{id}     근거 문단 (검색과 같은 권한 필터. 볼 수 없으면 없는 것과 같은 404)

모델을 읽지 않는다 (질문 API의 Services와 달리 가벼운 묶음을 쓴다).
기록을 지워도 감사 기록(audit_log)은 남는다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.generate import AnswerRefusal
from rag_service.answer.verify import SentenceStatus
from rag_service.api.admin_ui import UiConfigOut, ui_config
from rag_service.api.auth import Authenticator, build_authenticator
from rag_service.api.current import SignedIn, authenticate
from rag_service.api.roles import AdminRole, RoleGroups
from rag_service.chat.history import (
    delete_all,
    delete_turn,
    get_passage,
    get_turn,
    list_turns,
)
from rag_service.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

HISTORY_PAGE = 30
NOT_FOUND_TURN = "없는 대화 기록입니다"


@dataclass(frozen=True)
class ChatServices:
    sessions: sessionmaker[Session]
    authenticator: Authenticator | None
    role_groups: RoleGroups = RoleGroups()
    history_days: int = 0  # 0이면 대화 기록을 저장하지도 보여 주지도 않는다


@lru_cache
def get_chat_services() -> ChatServices:
    settings = get_settings()
    engine = create_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )
    return ChatServices(
        sessions=sessionmaker(engine),
        authenticator=build_authenticator(settings.auth_mode, settings.oidc),
        role_groups=settings.role_groups,
        history_days=settings.chat_history_days,
    )


ChatServicesDep = Annotated[ChatServices, Depends(get_chat_services)]


def signed_in(request: Request, services: ChatServicesDep) -> SignedIn:
    return authenticate(request, services.authenticator, services.sessions, logger)


SignedInDep = Annotated[SignedIn, Depends(signed_in)]


# ---------- 화면 설정과 로그인한 사람 ----------


@router.get("/config")
def config() -> UiConfigOut:
    return ui_config()


class ChatMeOut(BaseModel):
    login: str
    name: str
    department: str
    admin_roles: list[AdminRole]  # 비어 있지 않으면 화면에 관리 화면 링크를 보인다
    history_days: int  # 대화 기록 보관 기간. 0이면 기록 기능을 숨긴다


@router.get("/me")
def me(who: SignedInDep, services: ChatServicesDep) -> ChatMeOut:
    roles = services.role_groups.roles(who.identity.groups)
    return ChatMeOut(
        login=who.user.login,
        name=who.user.name,
        department=who.user.department,
        admin_roles=[role for role in AdminRole if role in roles],  # 순서를 고정한다
        history_days=services.history_days,
    )


# ---------- 답변 내용 (질문 API의 done 이벤트와 같은 모양) ----------


class CitationOut(BaseModel):
    number: int  # 답변 속 [번호]
    chunk_id: int  # 근거 문단 보기(/api/passages/{chunk_id})에 쓴다
    file: str
    title: str
    section: str | None
    page: int | None


class ProblemOut(BaseModel):
    text: str
    status: SentenceStatus
    unsupported_numbers: list[str]


class VerificationOut(BaseModel):
    verified: bool
    problems: list[ProblemOut]


class AnswerOut(BaseModel):
    text: str
    refused: bool
    reason: AnswerRefusal | None
    citations: list[CitationOut]
    invalid_citations: list[int]
    verification: VerificationOut | None


# ---------- 대화 기록 ----------


class TurnSummaryOut(BaseModel):
    id: int
    created_at: datetime
    question: str
    outcome: str  # answered | refused


class HistoryPageOut(BaseModel):
    items: list[TurnSummaryOut]
    next_before: int | None  # 더 오래된 기록이 있을 수 있으면 다음 요청의 before 값


class TurnOut(BaseModel):
    id: int
    created_at: datetime
    question: str
    outcome: str
    hidden: bool  # 근거 문서의 권한이 바뀌었거나 문서가 지워져 답을 가렸다
    answer: AnswerOut | None  # hidden이면 None


@router.get("/history")
def history(
    who: SignedInDep,
    services: ChatServicesDep,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = HISTORY_PAGE,
) -> HistoryPageOut:
    with services.sessions() as session:
        turns = list_turns(
            session, who.user.login, keep_days=services.history_days, before=before, limit=limit
        )
    items = [TurnSummaryOut(**vars(turn)) for turn in turns]
    return HistoryPageOut(items=items, next_before=items[-1].id if len(items) == limit else None)


@router.get("/history/{turn_id}", responses={404: {"description": NOT_FOUND_TURN}})
def history_turn(turn_id: int, who: SignedInDep, services: ChatServicesDep) -> TurnOut:
    with services.sessions() as session:
        turn = get_turn(
            session, who.user.login, turn_id, viewer=who.user, keep_days=services.history_days
        )
    if turn is None:
        raise HTTPException(404, NOT_FOUND_TURN)
    return TurnOut(
        id=turn.id,
        created_at=turn.created_at,
        question=turn.question,
        outcome=turn.outcome,
        hidden=turn.hidden,
        answer=AnswerOut.model_validate(turn.result) if turn.result is not None else None,
    )


@router.delete(
    "/history/{turn_id}", status_code=204, responses={404: {"description": NOT_FOUND_TURN}}
)
def forget_turn(turn_id: int, who: SignedInDep, services: ChatServicesDep) -> Response:
    with services.sessions.begin() as session:
        found = delete_turn(session, who.user.login, turn_id)
    if not found:
        raise HTTPException(404, NOT_FOUND_TURN)
    return Response(status_code=204)


class DeletedOut(BaseModel):
    deleted: int


@router.delete("/history")
def forget_all(who: SignedInDep, services: ChatServicesDep) -> DeletedOut:
    with services.sessions.begin() as session:
        deleted = delete_all(session, who.user.login)
    return DeletedOut(deleted=deleted)


# ---------- 근거 문단 ----------


class PassageOut(BaseModel):
    chunk_id: int
    file: str
    title: str
    section: str | None
    page: int | None
    content: str
    status: str  # current | superseded (폐지되었거나 새 판으로 대체된 문서)


NOT_FOUND_PASSAGE = "볼 수 있는 근거 문단이 없습니다"


@router.get("/passages/{chunk_id}", responses={404: {"description": NOT_FOUND_PASSAGE}})
def passage(chunk_id: int, who: SignedInDep, services: ChatServicesDep) -> PassageOut:
    with services.sessions() as session:
        found = get_passage(session, who.user, chunk_id)
    if found is None:
        # 권한이 없는 경우와 없는 문단을 구별하지 않는다 (그런 문서가 있다는 사실도 알리지 않는다)
        raise HTTPException(404, NOT_FOUND_PASSAGE)
    return PassageOut(**vars(found))
