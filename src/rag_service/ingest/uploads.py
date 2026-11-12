"""관리 화면에서 올린 문서 (origin=upload). 권한의 원본은 DB다 (폴더 문서는 acl.yaml).

- 원문 파일은 UPLOAD_DIR/docs/upload/<파일 이름>에 두고, source_path는 "upload/<파일 이름>"이다.
  폴더 문서의 source_path(acl.yaml의 file)와 겹치지 않고, corpus_root가 UPLOAD_DIR이라서 폴더
  수집의 --prune은 올린 문서를 지우지 않는다. /health의 신선도 요약도 같은 규칙으로 원문을 찾는다.
- 수집(청킹·임베딩·권한 사본)은 폴더 문서와 같은 write_document를 쓴다. 파일을 바꿔 올리면
  본문이 같은 조각의 벡터를 다시 쓴다.
- 권한 변경은 재임베딩 없이 document_acl과 조각의 권한 사본만 고친다 (update_metadata).
- 올리기, 교체, 권한 변경, 삭제는 document_changes에 누가·언제·전후 값을 남긴다.
- 파일은 임시 폴더에 받아 검사·수집하고, DB 커밋이 끝난 뒤에 제자리로 옮긴다 (Staged.finalize).
  커밋에 실패하면 Staged.discard로 임시 파일만 지운다. 기존 원문은 커밋 전까지 건드리지 않는다.
- 커밋은 호출하는 쪽(관리 API)에서 한다.
"""

import shutil
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from rag_service.corpus import DocumentEntry, DocumentStatus
from rag_service.db.changes import DocumentChange
from rag_service.db.models import Chunk, Document, DocumentAcl, User
from rag_service.ingest.chunker import chunk_document
from rag_service.ingest.embedder import Embedder
from rag_service.ingest.parsers import SUPPORTED_SUFFIXES
from rag_service.ingest.pipeline import (
    acl_by_document,
    corpus_root_key,
    file_sha256,
    update_metadata,
    write_document,
)
from rag_service.ingest.tokenizer import KoreanTokenizer

UPLOAD_PREFIX = "upload/"
MAX_FILENAME_CHARS = 120
_FORBIDDEN_CHARS = set('/\\:*?"<>|')


class UploadError(ValueError):
    """요청 내용이 잘못됐다 (HTTP 422)."""


class UploadConflict(ValueError):
    """같은 이름의 문서가 이미 있다 (HTTP 409)."""


@dataclass(frozen=True)
class Access:
    """문서의 제목과 열람 권한. (부서 OR 역할) AND 사용자 등급 >= security_level."""

    title: str
    security_level: int
    departments: tuple[str, ...]
    roles: tuple[str, ...]
    status: DocumentStatus = "current"

    def as_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "security_level": self.security_level,
            "departments": sorted(self.departments),
            "roles": sorted(self.roles),
            "status": self.status,
        }


@dataclass
class Staged:
    """커밋을 기다리는 파일. 커밋 뒤 finalize, 실패하면 discard."""

    document: Document
    temp_dir: Path
    target: Path | None = None  # None이면 옮길 파일이 없다 (삭제)
    remove: list[Path] = field(default_factory=list)  # 커밋 뒤 지울 파일

    def finalize(self) -> None:
        if self.target is not None:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            source = self.temp_dir / self.target.name
            source.replace(self.target)  # 수정 시각을 그대로 옮긴다 (신선도 요약과 맞춘다)
        for path in self.remove:
            path.unlink(missing_ok=True)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def discard(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def clean_filename(name: str) -> str:
    """브라우저가 보낸 파일 이름을 저장할 이름으로 고친다. 경로와 위험한 문자는 거부한다."""
    base = unicodedata.normalize("NFC", name.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    if not base or base in (".", "..") or base.startswith("."):
        raise UploadError("파일 이름이 비어 있거나 올바르지 않습니다")
    if any(ch in _FORBIDDEN_CHARS or unicodedata.category(ch).startswith("C") for ch in base):
        raise UploadError(f"파일 이름에 쓸 수 없는 문자가 있습니다: {base}")
    if len(base) > MAX_FILENAME_CHARS:
        raise UploadError(f"파일 이름은 {MAX_FILENAME_CHARS}자 이하여야 합니다")
    if Path(base).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UploadError(f"지원하는 형식은 {', '.join(SUPPORTED_SUFFIXES)}입니다: {base}")
    return base


def source_path_for(filename: str) -> str:
    return UPLOAD_PREFIX + filename


def stored_file(upload_dir: Path, source_path: str) -> Path:
    """올린 문서의 원문 위치. 폴더 문서와 같은 규칙(<corpus_root>/docs/<source_path>)이다."""
    return upload_dir / "docs" / source_path


def known_values(session: Session) -> tuple[list[str], list[str]]:
    """권한에 쓸 수 있는 (부서, 역할): 등록된 사용자와 기존 문서 권한에 나오는 값."""
    departments = set(session.scalars(select(User.department)))
    roles = set(session.scalars(select(User.role)))
    for kind, value in session.execute(select(DocumentAcl.kind, DocumentAcl.value)):
        (departments if kind == "department" else roles).add(value)
    return sorted(departments), sorted(roles)


def check_access(session: Session, access: Access) -> None:
    if not access.title.strip():
        raise UploadError("제목이 비어 있습니다")
    if not access.departments and not access.roles:
        raise UploadError("볼 수 있는 부서나 역할을 하나 이상 정해야 합니다")
    departments, roles = known_values(session)
    unknown = [d for d in access.departments if d not in departments]
    unknown += [r for r in access.roles if r not in roles]
    if unknown:
        raise UploadError(f"없는 부서나 역할입니다: {', '.join(unknown)}")


def who_can_view(
    session: Session, departments: tuple[str, ...], roles: tuple[str, ...], security_level: int
) -> list[User]:
    """이 권한으로 문서를 볼 수 있게 되는 사용자 (부서, 로그인 순). 검색 권한 필터와 같은 규칙."""
    query = (
        select(User)
        .where(
            or_(User.department.in_(departments), User.role.in_(roles)),
            User.clearance_level >= security_level,
        )
        .order_by(User.department, User.login)
    )
    return list(session.scalars(query))


def can_view(user: User, access: Access) -> bool:
    """corpus.can_view, 검색 권한 필터와 같은 규칙을 DB 사용자에 적용한다."""
    allowed = user.department in access.departments or user.role in access.roles
    return allowed and user.clearance_level >= access.security_level


def access_of(session: Session, document: Document) -> Access:
    departments, roles = acl_by_document(session).get(document.id, ((), ()))
    status: DocumentStatus = "superseded" if document.status == "superseded" else "current"
    return Access(document.title, document.security_level, departments, roles, status)


def _entry(source_path: str, access: Access, document: Document | None = None) -> DocumentEntry:
    return DocumentEntry(
        file=source_path,
        title=access.title.strip(),
        security_level=access.security_level,
        departments=list(access.departments),
        roles=list(access.roles),
        status=access.status,
        effective_from=document.effective_from if document else None,
        effective_to=document.effective_to if document else None,
    )


def _receive(upload_dir: Path, filename: str, data: bytes) -> tuple[Path, Path]:
    """임시 폴더에 파일을 쓰고 읽어 본다. (임시 폴더, 임시 파일)을 돌려준다."""
    temp_dir = upload_dir / "tmp" / uuid.uuid4().hex
    temp_dir.mkdir(parents=True)
    path = temp_dir / filename
    path.write_bytes(data)
    try:
        pieces = chunk_document(path)
    except Exception as error:  # 파서마다 예외가 다르다 (깨진 PDF, 암호 걸린 DOCX 등)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise UploadError(f"문서를 읽을 수 없습니다: {filename}") from error
    if not pieces:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise UploadError(f"본문 글자가 없습니다 (스캔한 PDF는 아직 지원하지 않습니다): {filename}")
    return temp_dir, path


def _record(
    session: Session,
    document: Document,
    action: str,
    actor: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    session.add(
        DocumentChange(
            document_id=document.id,
            source_path=document.source_path,
            action=action,
            actor_login=actor,
            before=before,
            after=after,
        )
    )
    session.flush()


def _find(session: Session, source_path: str) -> Document | None:
    return session.scalars(
        select(Document).where(Document.source_path == source_path)
    ).one_or_none()


def add_upload(
    session: Session,
    *,
    filename: str,
    data: bytes,
    access: Access,
    owner_department: str,
    actor: str,
    upload_dir: Path,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
) -> Staged:
    name = clean_filename(filename)
    source_path = source_path_for(name)
    if _find(session, source_path) is not None:
        raise UploadConflict(f"같은 이름의 문서가 이미 있습니다: {name} (파일 교체를 쓰세요)")
    check_access(session, access)
    temp_dir, path = _receive(upload_dir, name, data)
    try:
        write_document(
            session,
            _entry(source_path, access),
            path,
            root=corpus_root_key(upload_dir),
            embedder=embedder,
            tokenizer=tokenizer,
            origin="upload",
            owner_department=owner_department,
        )
        document = _find(session, source_path)
        assert document is not None
        _record(
            session,
            document,
            "upload",
            actor,
            None,
            access.as_json() | {"owner_department": owner_department, "sha256": file_sha256(path)},
        )
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return Staged(document, temp_dir, target=stored_file(upload_dir, source_path))


def replace_upload(
    session: Session,
    document: Document,
    *,
    filename: str,
    data: bytes,
    actor: str,
    upload_dir: Path,
    embedder: Embedder,
    tokenizer: KoreanTokenizer,
) -> Staged:
    """같은 문서의 새 판. 권한과 제목은 그대로 두고 원문만 바꾼다 (같은 조각은 벡터 재사용)."""
    current = document.source_path.removeprefix(UPLOAD_PREFIX)
    name = clean_filename(filename)
    if Path(name).suffix.lower() != Path(current).suffix.lower():
        raise UploadError(f"같은 형식({Path(current).suffix})의 파일로만 바꿀 수 있습니다")
    access = access_of(session, document)
    before = {"sha256": document.content_sha256}
    owner, source_path = document.owner_department, document.source_path
    temp_dir, received = _receive(upload_dir, name, data)
    path = received.rename(temp_dir / current)  # 저장 이름은 처음 올린 이름을 유지한다
    try:
        write_document(
            session,
            _entry(source_path, access, document),
            path,
            root=corpus_root_key(upload_dir),
            embedder=embedder,
            tokenizer=tokenizer,
            origin="upload",
            owner_department=owner,
        )
        replaced = _find(session, source_path)
        assert replaced is not None
        _record(session, replaced, "replace", actor, before, {"sha256": file_sha256(path)})
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return Staged(replaced, temp_dir, target=stored_file(upload_dir, source_path))


def change_access(session: Session, document: Document, access: Access, actor: str) -> bool:
    """권한·제목·상태를 바꾼다 (재임베딩 없음). 바뀐 것이 없으면 False (이력도 남기지 않는다)."""
    check_access(session, access)
    before = access_of(session, document)
    if before.as_json() == access.as_json():
        return False
    update_metadata(
        session, _entry(document.source_path, access, document), document.corpus_root or ""
    )
    _record(session, document, "access", actor, before.as_json(), access.as_json())
    return True


def delete_upload(session: Session, document: Document, actor: str, upload_dir: Path) -> Staged:
    before = access_of(session, document).as_json() | {"sha256": document.content_sha256}
    _record(session, document, "delete", actor, before, None)
    session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    session.execute(delete(Document).where(Document.id == document.id))
    session.flush()
    temp_dir = upload_dir / "tmp" / uuid.uuid4().hex
    return Staged(document, temp_dir, remove=[stored_file(upload_dir, document.source_path)])


def history(session: Session, source_path: str) -> list[DocumentChange]:
    """이 source_path의 변경 이력 (최근 것부터). 파일을 바꾸면 문서 id가 바뀌므로 경로로 찾는다."""
    query = (
        select(DocumentChange)
        .where(DocumentChange.source_path == source_path)
        .order_by(DocumentChange.id.desc())
    )
    return list(session.scalars(query))
