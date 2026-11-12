"""관리 API: 문서 목록, 올리기, 파일 교체, 권한 지정, 삭제, 변경 이력 (/admin/api/documents).

누가 무엇을 할 수 있나
- 중앙 관리자: 모든 문서를 보고, 올린 문서(origin=upload)는 어느 부서 것이든 바꾼다.
- 부서 문서 담당: 자기 부서가 관리하는 올린 문서만 보고 바꾼다. 올릴 때 관리 부서는 자기 부서다.
  다른 부서 문서는 없는 것처럼 404다 (제목도 드러내지 않는다).
- 폴더에서 수집한 문서(origin=folder)는 누구도 화면에서 바꿀 수 없다 (409, acl.yaml에서 바꾼다).

권한을 잘못 주면 문서가 새므로, 저장 전에 access-preview로 "누가 보게 되는지"를 보여 준다
(PRODUCT.md "권한이 먼저다"). 권한 변경은 재임베딩 없이 바로 검색에 반영된다.
올리기와 파일 교체는 임베딩 모델이 필요하다 (모델을 읽는 중이면 503).
"""

import logging
from datetime import datetime
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag_service.api.admin import Admin, AdminServicesDep, DocumentsDep, UserOut
from rag_service.api.readiness import require_models
from rag_service.api.roles import AdminRole
from rag_service.api.services import Services, get_services
from rag_service.corpus import DocumentStatus
from rag_service.db.models import MAX_SECURITY_LEVEL, MIN_SECURITY_LEVEL, Chunk, Document, User
from rag_service.ingest.uploads import (
    Access,
    Staged,
    UploadConflict,
    UploadError,
    access_of,
    add_upload,
    can_view,
    change_access,
    delete_upload,
    history,
    known_values,
    replace_upload,
    who_can_view,
)
from rag_service.logs import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/api", tags=["admin-documents"])

Level = Annotated[int, Field(ge=MIN_SECURITY_LEVEL, le=MAX_SECURITY_LEVEL)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ModelsServicesDep = Annotated[Services, Depends(get_services)]


class DocumentOut(BaseModel):
    id: int
    title: str
    source_path: str
    origin: str  # folder | upload
    owner_department: str | None
    security_level: int
    status: str
    departments: list[str]
    roles: list[str]
    chunks: int
    viewers: int  # 지금 권한으로 이 문서를 볼 수 있는 사용자 수
    editable: bool  # 로그인한 사람이 바꿀 수 있는가
    created_at: datetime
    synced_at: datetime | None


class OrgOut(BaseModel):
    departments: list[str]
    roles: list[str]


class PreviewIn(BaseModel):
    departments: list[str] = []
    roles: list[str] = []
    security_level: Level


class PreviewOut(BaseModel):
    count: int
    total_users: int
    users: list[UserOut]


class AccessIn(PreviewIn):
    title: Title
    status: DocumentStatus = "current"


class ChangeOut(BaseModel):
    id: int
    created_at: datetime
    action: str
    actor_login: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


def _can_manage(admin: Admin, document: Document) -> bool:
    if document.origin != "upload":
        return False
    if AdminRole.ADMIN in admin.roles:
        return True
    return document.owner_department == admin.user.department


def _can_see(admin: Admin, document: Document) -> bool:
    return AdminRole.ADMIN in admin.roles or _can_manage(admin, document)


def _managed(session: Session, admin: Admin, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None or not _can_see(admin, document):
        raise HTTPException(404, "문서가 없습니다")
    if document.origin != "upload":
        raise HTTPException(
            409, "문서 폴더에서 수집한 문서입니다. 권한과 원문은 acl.yaml과 문서 폴더에서 바꿉니다"
        )
    return document


def _bad_request(error: UploadError | UploadConflict) -> NoReturn:
    code = 409 if isinstance(error, UploadConflict) else 422
    raise HTTPException(code, str(error)) from error


def _read_file(file: UploadFile, limit: int) -> bytes:
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"파일이 너무 큽니다 (최대 {limit // (1024 * 1024)}MB)")
    return data


def _commit(session: Session, staged: Staged) -> None:
    try:
        session.commit()
    except BaseException:
        staged.discard()
        raise
    staged.finalize()


def _out(
    session: Session, admin: Admin, documents: list[Document], users: list[User]
) -> list[DocumentOut]:
    chunk_counts = dict(
        session.execute(
            select(Chunk.document_id, func.count())
            .where(Chunk.document_id.in_([d.id for d in documents]))
            .group_by(Chunk.document_id)
        ).all()
    )
    result = []
    for document in documents:
        access = access_of(session, document)
        viewers = sum(1 for user in users if can_view(user, access))
        result.append(
            DocumentOut(
                id=document.id,
                title=document.title,
                source_path=document.source_path,
                origin=document.origin,
                owner_department=document.owner_department,
                security_level=document.security_level,
                status=document.status,
                departments=list(access.departments),
                roles=list(access.roles),
                chunks=chunk_counts.get(document.id, 0),
                viewers=viewers,
                editable=_can_manage(admin, document),
                created_at=document.created_at,
                synced_at=document.synced_at,
            )
        )
    return result


@router.get("/documents")
def list_documents(admin: DocumentsDep, services: AdminServicesDep) -> list[DocumentOut]:
    """중앙 관리자는 전체, 부서 문서 담당은 자기 부서가 관리하는 올린 문서만.

    먼저 넣은 문서부터 (id순). 한글 제목의 정렬은 DB 설정(collation)마다 달라서 화면이 정렬한다.
    """
    with services.sessions() as session:
        query = select(Document).order_by(Document.id)
        if AdminRole.ADMIN not in admin.roles:
            query = query.where(
                Document.origin == "upload",
                Document.owner_department == admin.user.department,
            )
        documents = list(session.scalars(query))
        users = list(session.scalars(select(User)))
        return _out(session, admin, documents, users)


@router.get("/org")
def org(_: DocumentsDep, services: AdminServicesDep) -> OrgOut:
    """권한에 고를 수 있는 부서와 역할 (등록된 사용자와 기존 문서 권한에 나오는 값)."""
    with services.sessions() as session:
        departments, roles = known_values(session)
    return OrgOut(departments=departments, roles=roles)


@router.post("/documents/access-preview")
def access_preview(body: PreviewIn, _: DocumentsDep, services: AdminServicesDep) -> PreviewOut:
    """이 권한으로 저장하면 문서를 볼 수 있게 되는 사용자. 검색 권한 필터와 같은 규칙."""
    with services.sessions() as session:
        users = who_can_view(
            session, tuple(body.departments), tuple(body.roles), body.security_level
        )
        total = session.scalar(select(func.count()).select_from(User)) or 0
    return PreviewOut(
        count=len(users),
        total_users=total,
        users=[
            UserOut(
                login=u.login,
                name=u.name,
                department=u.department,
                role=u.role,
                clearance_level=u.clearance_level,
            )
            for u in users
        ],
    )


def _owner_for(admin: Admin, requested: str | None) -> str:
    """올린 문서를 관리할 부서. 부서 문서 담당은 자기 부서만, 중앙 관리자는 지정한 부서.

    중앙 관리자가 지정하지 않으면 자기 부서다.
    """
    if AdminRole.ADMIN in admin.roles:
        return requested or admin.user.department
    if requested and requested != admin.user.department:
        raise HTTPException(403, "자기 부서 문서만 올릴 수 있습니다")
    return admin.user.department


@router.post("/documents", status_code=201, dependencies=[Depends(require_models)])
def upload_document(
    admin: DocumentsDep,
    services: AdminServicesDep,
    models: ModelsServicesDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[Title, Form()],
    security_level: Annotated[Level, Form()],
    departments: Annotated[list[str] | None, Form()] = None,
    roles: Annotated[list[str] | None, Form()] = None,
    owner_department: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    owner = _owner_for(admin, owner_department)
    data = _read_file(file, services.upload_max_bytes)
    access = Access(title, security_level, tuple(departments or ()), tuple(roles or ()))
    with services.sessions() as session:
        if owner not in known_values(session)[0]:
            raise HTTPException(422, f"없는 부서입니다: {owner}")
        try:
            staged = add_upload(
                session,
                filename=file.filename or "",
                data=data,
                access=access,
                owner_department=owner,
                actor=admin.user.login,
                upload_dir=services.upload_dir,
                embedder=models.embedder,
                tokenizer=models.tokenizer,
            )
        except (UploadError, UploadConflict) as error:
            _bad_request(error)
        _commit(session, staged)
        log_event(
            logger,
            "document_uploaded",
            actor=admin.user.login,
            source_path=staged.document.source_path,
            owner_department=owner,
            security_level=security_level,
        )
        return _document(session, admin, staged.document.id)


@router.put("/documents/{document_id}/file", dependencies=[Depends(require_models)])
def replace_file(
    document_id: int,
    admin: DocumentsDep,
    services: AdminServicesDep,
    models: ModelsServicesDep,
    file: Annotated[UploadFile, File()],
) -> DocumentOut:
    data = _read_file(file, services.upload_max_bytes)
    with services.sessions() as session:
        document = _managed(session, admin, document_id)
        try:
            staged = replace_upload(
                session,
                document,
                filename=file.filename or "",
                data=data,
                actor=admin.user.login,
                upload_dir=services.upload_dir,
                embedder=models.embedder,
                tokenizer=models.tokenizer,
            )
        except (UploadError, UploadConflict) as error:
            _bad_request(error)
        _commit(session, staged)
        log_event(
            logger,
            "document_replaced",
            actor=admin.user.login,
            source_path=staged.document.source_path,
        )
        return _document(session, admin, staged.document.id)


@router.put("/documents/{document_id}/access")
def update_access(
    document_id: int, body: AccessIn, admin: DocumentsDep, services: AdminServicesDep
) -> DocumentOut:
    access = Access(
        body.title, body.security_level, tuple(body.departments), tuple(body.roles), body.status
    )
    with services.sessions() as session:
        document = _managed(session, admin, document_id)
        try:
            changed = change_access(session, document, access, admin.user.login)
        except UploadError as error:
            _bad_request(error)
        session.commit()
        if changed:
            log_event(
                logger,
                "document_access_changed",
                actor=admin.user.login,
                source_path=document.source_path,
                after=access.as_json(),
            )
        return _document(session, admin, document_id)


@router.delete("/documents/{document_id}", status_code=204)
def remove_document(document_id: int, admin: DocumentsDep, services: AdminServicesDep) -> None:
    with services.sessions() as session:
        document = _managed(session, admin, document_id)
        source_path = document.source_path
        staged = delete_upload(session, document, admin.user.login, services.upload_dir)
        _commit(session, staged)
    log_event(logger, "document_deleted", actor=admin.user.login, source_path=source_path)


@router.get("/documents/{document_id}/changes")
def document_changes(
    document_id: int, admin: DocumentsDep, services: AdminServicesDep
) -> list[ChangeOut]:
    with services.sessions() as session:
        document = session.get(Document, document_id)
        if document is None or not _can_see(admin, document):
            raise HTTPException(404, "문서가 없습니다")
        return [
            ChangeOut(
                id=c.id,
                created_at=c.created_at,
                action=c.action,
                actor_login=c.actor_login,
                before=c.before,
                after=c.after,
            )
            for c in history(session, document.source_path)
        ]


def _document(session: Session, admin: Admin, document_id: int) -> DocumentOut:
    document = session.get(Document, document_id)
    assert document is not None
    users = list(session.scalars(select(User)))
    [out] = _out(session, admin, [document], users)
    return out
