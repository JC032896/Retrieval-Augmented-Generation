"""관리 API (/admin/api). 관리 화면(React)이 부른다.

사용자 확인은 질문 API와 같고(current.py), 역할은 토큰의 그룹 값으로 정한다 (roles.py).
- GET /me      로그인한 사람과 관리 역할. 역할이 없어도 200 (화면이 "권한 없음"을 보여 준다)
- GET /status  설치 상태: DB, 모델, 인덱스, 답변 LLM, 감사 DB 연결, 사용 한도 (관리 역할 누구나)
- GET /users   사용자와 권한 속성 (중앙 관리자)
- GET /audit   감사 기록 목록, GET /audit/{id} 한 건 (감사 담당)

감사 기록은 앱 계정이 읽을 수 없으므로 감사 담당 DB 계정(rag_auditor 역할)으로 따로 연결한다.
감사 기록을 본 사실은 운영 로그(admin_audit_viewed)에 남긴다. 질문 원문은 로그에 넣지 않는다.
모델을 읽지 않으므로 모델을 읽는 중에도 관리 화면은 동작한다.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from rag_service import __version__
from rag_service.api.auth import Authenticator, CurrentUser, build_authenticator
from rag_service.api.current import authenticate
from rag_service.api.limits import UsageLimits
from rag_service.api.readiness import MODELS
from rag_service.api.roles import AdminRole, RoleGroups
from rag_service.audit.models import AuditLog
from rag_service.audit.record import Outcome
from rag_service.config import get_settings
from rag_service.db.models import User
from rag_service.ingest.check import index_summary
from rag_service.ingest.embedder import DEFAULT_MODEL
from rag_service.logs import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/api", tags=["admin"])

MAX_AUDIT_PAGE = 200


@dataclass(frozen=True)
class LlmInfo:
    provider: str
    model: str
    configured: bool  # False면 질문 API가 503 (Claude인데 API 키가 없음)


@dataclass(frozen=True)
class AdminServices:
    sessions: sessionmaker[Session]  # 앱 계정
    audit_sessions: sessionmaker[Session] | None  # 감사 담당 계정. 설정하지 않았으면 None
    authenticator: Authenticator | None
    role_groups: RoleGroups = RoleGroups()
    llm: LlmInfo = LlmInfo("claude", "", configured=False)
    limits: UsageLimits = UsageLimits()
    upload_dir: Path = Path("data/uploads")
    upload_max_bytes: int = 30 * 1024 * 1024


def _sessions(url: URL) -> sessionmaker[Session]:
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    return sessionmaker(engine)


@lru_cache
def get_admin_services() -> AdminServices:
    settings = get_settings()
    audit_url = settings.audit_database_url if settings.admin_audit_view else None
    configured = settings.llm_provider == "openai_compatible" or bool(settings.anthropic_api_key)
    return AdminServices(
        sessions=_sessions(settings.database_url),
        audit_sessions=_sessions(audit_url) if audit_url is not None else None,
        authenticator=build_authenticator(settings.auth_mode, settings.oidc),
        role_groups=settings.role_groups,
        llm=LlmInfo(settings.llm_provider, settings.llm_model, configured),
        limits=UsageLimits(
            daily_requests_per_user=settings.llm_daily_requests_per_user,
            daily_budget_usd=settings.llm_daily_budget_usd,
            concurrent_per_user=settings.llm_concurrent_per_user,
            utc_offset_hours=settings.usage_utc_offset_hours,
        ),
        upload_dir=settings.upload_dir,
        upload_max_bytes=settings.upload_max_mb * 1024 * 1024,
    )


AdminServicesDep = Annotated[AdminServices, Depends(get_admin_services)]


@dataclass(frozen=True)
class Admin:
    user: CurrentUser
    roles: frozenset[AdminRole]


def signed_in(request: Request, services: AdminServicesDep) -> Admin:
    who = authenticate(request, services.authenticator, services.sessions, logger)
    return Admin(who.user, services.role_groups.roles(who.identity.groups))


SignedInDep = Annotated[Admin, Depends(signed_in)]


def require(*allowed: AdminRole) -> Callable[[Admin], Admin]:
    """allowed 중 하나라도 가진 사람만 통과시키는 의존성. 거절은 운영 로그에 남긴다."""

    def check(admin: SignedInDep) -> Admin:
        if admin.roles.isdisjoint(allowed):
            log_event(
                logger,
                "admin_forbidden",
                level=logging.WARNING,
                login=admin.user.login,
                roles=sorted(admin.roles),
                required=sorted(allowed),
            )
            raise HTTPException(403, "이 화면을 볼 권한이 없습니다")
        return admin

    return check


AnyAdminDep = Annotated[Admin, Depends(require(*AdminRole))]
CentralAdminDep = Annotated[Admin, Depends(require(AdminRole.ADMIN))]
AuditorDep = Annotated[Admin, Depends(require(AdminRole.AUDITOR))]
DocumentsDep = Annotated[Admin, Depends(require(AdminRole.ADMIN, AdminRole.DOC_MANAGER))]


class MeOut(BaseModel):
    login: str
    name: str
    department: str
    role: str
    clearance_level: int
    roles: list[AdminRole]


@router.get("/me")
def me(admin: SignedInDep) -> MeOut:
    user = admin.user
    roles = [role for role in AdminRole if role in admin.roles]  # 순서를 고정한다
    return MeOut(
        login=user.login,
        name=user.name,
        department=user.department,
        role=user.role,
        clearance_level=user.clearance_level,
        roles=roles,
    )


class LimitsOut(BaseModel):
    daily_requests_per_user: int | None
    daily_budget_usd: float | None
    concurrent_per_user: int | None
    utc_offset_hours: int


class StatusOut(BaseModel):
    version: str
    db: str  # ok | error
    models: dict[str, str]  # status(ready, loading, lazy, error), 실패하면 error에 이유
    index: dict[str, Any]  # ingest.check.index_summary
    llm: dict[str, Any]
    audit_db: bool  # 감사 담당 계정으로 연결하도록 설정했는가
    limits: LimitsOut


@router.get("/status")
def status(_: AnyAdminDep, services: AdminServicesDep) -> StatusOut:
    try:
        with services.sessions() as session:
            index: dict[str, Any] = index_summary(session, model=DEFAULT_MODEL)
        db = "ok"
    except SQLAlchemyError:
        logger.exception("관리 화면 상태: DB를 읽지 못함")
        index = {"error": "DB에 연결하거나 인덱스를 읽을 수 없습니다"}
        db = "error"
    models: dict[str, str] = {"status": MODELS.status}
    if MODELS.error:
        models["error"] = MODELS.error
    limits = services.limits
    return StatusOut(
        version=__version__,
        db=db,
        models=models,
        index=index,
        llm={
            "provider": services.llm.provider,
            "model": services.llm.model,
            "configured": services.llm.configured,
        },
        audit_db=services.audit_sessions is not None,
        limits=LimitsOut(
            daily_requests_per_user=limits.daily_requests_per_user,
            daily_budget_usd=limits.daily_budget_usd,
            concurrent_per_user=limits.concurrent_per_user,
            utc_offset_hours=limits.utc_offset_hours,
        ),
    )


class UserOut(BaseModel):
    login: str
    name: str
    department: str
    role: str
    clearance_level: int


@router.get("/users")
def users(_: CentralAdminDep, services: AdminServicesDep) -> list[UserOut]:
    """문서 폴더의 org.yaml에서 수집한 사용자. 바꾸려면 org.yaml을 고친다 (관리 화면은 보기만)."""
    with services.sessions() as session:
        rows = session.scalars(select(User).order_by(User.department, User.login)).all()
    return [
        UserOut(
            login=u.login,
            name=u.name,
            department=u.department,
            role=u.role,
            clearance_level=u.clearance_level,
        )
        for u in rows
    ]


class AuditSummaryOut(BaseModel):
    id: int
    created_at: datetime
    request_id: str
    user_login: str
    user_department: str
    user_role: str
    question: str | None  # 원문을 저장하지 않는 설정(AUDIT_STORE_TEXT=false)이면 None
    question_chars: int
    outcome: str
    refusal_reason: str | None
    cited_files: list[str]
    verified: bool | None
    model: str | None
    cost_usd: float | None
    total_ms: int


class AuditPageOut(BaseModel):
    items: list[AuditSummaryOut]
    next_before_id: int | None  # 다음 페이지를 받으려면 before_id로 넘긴다. 없으면 끝


class AuditDetailOut(AuditSummaryOut):
    client_ip: str | None
    user_clearance_level: int
    question_sha256: str
    answer: str | None
    context_files: list[str]
    input_tokens: int | None
    output_tokens: int | None
    retrieval_ms: int
    first_token_ms: int | None
    prompt_template_version: str | None
    model_params: dict[str, Any] | None
    context_chunks: list[dict[str, Any]] | None
    request_sha256: str | None


def _audit_sessions(services: AdminServices) -> sessionmaker[Session]:
    if services.audit_sessions is None:
        raise HTTPException(
            503,
            "관리 화면의 감사 기록 보기가 꺼져 있거나 감사 담당 DB 계정이 설정되지 않았습니다"
            " (ADMIN_AUDIT_VIEW, AUDIT_DB_USER, AUDIT_DB_PASSWORD)",
        )
    return services.audit_sessions


def _summary(row: AuditLog) -> dict[str, Any]:
    return {name: getattr(row, name) for name in AuditSummaryOut.model_fields}


@router.get("/audit")
def audit_list(
    admin: AuditorDep,
    services: AdminServicesDep,
    login: str | None = None,
    outcome: Outcome | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_PAGE)] = 50,
) -> AuditPageOut:
    """최근 기록부터. since 이후(포함), until 이전(제외)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if login:
        query = query.where(AuditLog.user_login == login)
    if outcome:
        query = query.where(AuditLog.outcome == outcome)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at < until)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    with _audit_sessions(services)() as session:
        rows = session.scalars(query).all()
        items = [AuditSummaryOut(**_summary(row)) for row in rows[:limit]]
    log_event(
        logger,
        "admin_audit_viewed",
        viewer=admin.user.login,
        filters={"login": login, "outcome": outcome, "since": since, "until": until},
        count=len(items),
    )
    more = len(rows) > limit
    return AuditPageOut(items=items, next_before_id=items[-1].id if more else None)


@router.get("/audit/{audit_id}")
def audit_detail(audit_id: int, admin: AuditorDep, services: AdminServicesDep) -> AuditDetailOut:
    with _audit_sessions(services)() as session:
        row = session.get(AuditLog, audit_id)
        if row is None:
            raise HTTPException(404, "감사 기록이 없습니다")
        detail = AuditDetailOut(
            **{name: getattr(row, name) for name in AuditDetailOut.model_fields}
        )
    log_event(logger, "admin_audit_viewed", viewer=admin.user.login, audit_id=audit_id)
    return detail
