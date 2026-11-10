"""문서 묶음(코퍼스)의 조직 정보, 문서 권한 목록을 읽고 검증한다.

파일 구성 (samples/ 참고):
  org.yaml   departments, roles, users
  acl.yaml   documents: 문서 파일별 제목, 보안 등급, 열람 가능한 부서와 역할,
             수명(status: current 기본값, superseded 폐지/대체),
             시행일(effective_from, effective_to: 마지막 유효일 포함, 비우면 미상 또는 현재까지)
  docs/      문서 본문

권한 규칙은 can_view 하나로 정의한다. 검색 SQL의 권한 필터와 평가의 유출 검사는
이 함수와 같은 결과를 내야 한다.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rag_service.db.models import MAX_SECURITY_LEVEL, MIN_SECURITY_LEVEL
from rag_service.ingest.parsers import SUPPORTED_SUFFIXES

DocumentStatus = Literal["current", "superseded"]  # db.models.DOCUMENT_STATUSES와 같다
SecurityLevel = Annotated[int, Field(ge=MIN_SECURITY_LEVEL, le=MAX_SECURITY_LEVEL)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserEntry(_Strict):
    id: str
    name: str
    department: str
    role: str
    clearance_level: SecurityLevel


class Org(_Strict):
    departments: list[str]
    roles: list[str]
    users: list[UserEntry]


class DocumentEntry(_Strict):
    file: str
    title: str
    security_level: SecurityLevel
    departments: list[str] = []
    roles: list[str] = []
    status: DocumentStatus = "current"
    # 문서 본문 등 근거가 있는 날짜만 적는다. 추정값은 넣지 않는다 (비우면 "시행일 미상")
    effective_from: date | None = None
    effective_to: date | None = None  # 마지막 유효일 (그날까지 포함)


class AclFile(_Strict):
    documents: list[DocumentEntry]


class CorpusError(ValueError):
    """코퍼스 파일의 내용이 서로 맞지 않을 때 발생한다."""


@dataclass(frozen=True)
class Corpus:
    root: Path
    org: Org
    documents: list[DocumentEntry]

    def doc_path(self, document: DocumentEntry) -> Path:
        return self.root / "docs" / document.file

    def user(self, user_id: str) -> UserEntry:
        for user in self.org.users:
            if user.id == user_id:
                return user
        raise KeyError(user_id)

    def visible_files(self, user: UserEntry) -> set[str]:
        return {doc.file for doc in self.documents if can_view(user, doc)}


def can_view(user: UserEntry, document: DocumentEntry) -> bool:
    """(부서가 허용 목록에 있음 OR 역할이 허용 목록에 있음) AND 열람 등급 >= 문서 등급."""
    allowed = user.department in document.departments or user.role in document.roles
    return allowed and user.clearance_level >= document.security_level


def load_corpus(root: Path) -> Corpus:
    org = Org.model_validate(_read_yaml(root / "org.yaml"))
    acl = AclFile.model_validate(_read_yaml(root / "acl.yaml"))
    corpus = Corpus(root=root, org=org, documents=acl.documents)
    _validate(corpus)
    return corpus


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _validate(corpus: Corpus) -> None:
    errors: list[str] = []
    departments = set(corpus.org.departments)
    roles = set(corpus.org.roles)

    user_ids = [user.id for user in corpus.org.users]
    errors += [f"사용자 id 중복: {i}" for i in _duplicates(user_ids)]
    for user in corpus.org.users:
        if user.department not in departments:
            errors.append(f"사용자 {user.id}: 없는 부서 {user.department}")
        if user.role not in roles:
            errors.append(f"사용자 {user.id}: 없는 역할 {user.role}")

    errors += [f"문서 중복: {f}" for f in _duplicates([d.file for d in corpus.documents])]
    for doc in corpus.documents:
        if not corpus.doc_path(doc).is_file():
            errors.append(f"{doc.file}: 파일 없음")
        if not doc.departments and not doc.roles:
            errors.append(f"{doc.file}: 열람 가능한 부서나 역할이 없음")
        errors += [f"{doc.file}: 없는 부서 {d}" for d in doc.departments if d not in departments]
        errors += [f"{doc.file}: 없는 역할 {r}" for r in doc.roles if r not in roles]
        if doc.effective_from and doc.effective_to and doc.effective_from > doc.effective_to:
            errors.append(f"{doc.file}: effective_from이 effective_to보다 늦음")

    listed = {doc.file for doc in corpus.documents}
    docs_dir = corpus.root / "docs"
    errors += [
        f"{p.name}: acl.yaml에 없음"
        for p in sorted(docs_dir.iterdir())
        if p.suffix.lower() in SUPPORTED_SUFFIXES and p.name not in listed
    ]

    if errors:
        raise CorpusError("\n".join(errors))


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    return duplicates
