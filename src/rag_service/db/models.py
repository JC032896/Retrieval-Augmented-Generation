"""DB 스키마 (SQLAlchemy 모델). 실제 테이블은 migrations/의 Alembic 마이그레이션으로 만든다.

권한 규칙: 사용자는 아래 두 조건을 모두 만족하는 조각만 볼 수 있다.
  1. 사용자의 부서가 allowed_departments에 있거나, 역할이 allowed_roles에 있다 (OR)
  2. 사용자의 clearance_level >= 조각의 security_level

권한의 원본은 document_acl이고, chunks의 권한 컬럼은 검색 SQL의 WHERE 절에서
바로 걸러내기 위한 사본이다. 지금은 권한이 바뀌어도 문서를 통째로 다시 수집한다 (임베딩 재계산).
사본만 갱신하는 기능은 계획이다 (README 로드맵의 증분 수집).
"""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024  # BGE-M3 출력 차원. 모델을 바꾸면 마이그레이션으로 변경한다

# 보안 등급: 0 공개, 1 사내, 2 대외비, 3 기밀
MIN_SECURITY_LEVEL = 0
MAX_SECURITY_LEVEL = 3
_LEVEL_RANGE = f"BETWEEN {MIN_SECURITY_LEVEL} AND {MAX_SECURITY_LEVEL}"

ACL_KINDS = ("department", "role")

# 문서 수명: current 현행, superseded 폐지되었거나 새 판으로 대체됨 (기록으로만 남긴다)
DOCUMENT_STATUSES = ("current", "superseded")

# 문서 출처 (마이그레이션 0009): folder 문서 폴더의 acl.yaml에서 수집 (관리 화면은 읽기 전용),
# upload 관리 화면에서 올림 (권한의 원본이 DB)
DOCUMENT_ORIGINS = ("folder", "upload")


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"security_level {_LEVEL_RANGE}", name="ck_documents_security_level"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in DOCUMENT_STATUSES) + ")",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "origin IN (" + ", ".join(f"'{origin}'" for origin in DOCUMENT_ORIGINS) + ")",
            name="ck_documents_origin",
        ),
        CheckConstraint(
            "origin = 'folder' OR owner_department IS NOT NULL", name="ck_documents_upload_owner"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text, unique=True)
    security_level: Mapped[int] = mapped_column(Integer)
    # 권한과 달리 조각에 복사하지 않는다. 새 판이 나오면 이 한 행만 바꾸면 된다
    status: Mapped[str] = mapped_column(Text, server_default=text("'current'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 수명 관리 (마이그레이션 0005). 0005 이전에 수집한 행은 비어 있다 → 재수집 대상
    content_sha256: Mapped[str | None] = mapped_column(Text)  # 원문 파일 바이트의 해시
    source_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 참고용
    embedding_model: Mapped[str | None] = mapped_column(Text)  # 이 문서의 조각을 임베딩한 모델
    effective_from: Mapped[date | None] = mapped_column(Date)  # 시행일 (비면 미상)
    effective_to: Mapped[date | None] = mapped_column(Date)  # 마지막 유효일 포함 (비면 미상/현재)
    # 증분 수집 (마이그레이션 0006). --prune은 같은 corpus_root의 문서만 지운다
    corpus_root: Mapped[str | None] = mapped_column(Text)  # 수집한 코퍼스 폴더 (절대 경로)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 마지막 동기화
    # 관리 화면 업로드 (마이그레이션 0009)
    origin: Mapped[str] = mapped_column(Text, server_default=text("'folder'"))
    owner_department: Mapped[str | None] = mapped_column(Text)  # 올린 문서를 관리하는 부서


class DocumentAcl(Base):
    """문서 열람 권한의 원본. 한 행이 '이 부서' 또는 '이 역할'에 열람을 허용한다."""

    __tablename__ = "document_acl"
    __table_args__ = (
        UniqueConstraint("document_id", "kind", "value", name="uq_document_acl"),
        CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind}'" for kind in ACL_KINDS) + ")",
            name="ck_document_acl_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        UniqueConstraint("document_id", "chunk_key", name="uq_chunks_document_key"),
        CheckConstraint(f"security_level {_LEVEL_RANGE}", name="ck_chunks_security_level"),
        Index("ix_chunks_tokens", "tokens", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_allowed_departments", "allowed_departments", postgresql_using="gin"),
        Index("ix_chunks_allowed_roles", "allowed_roles", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    # Kiwi 형태소 토큰을 공백으로 이어 to_tsvector('simple', ...)로 만든 값
    tokens: Mapped[str] = mapped_column(TSVECTOR)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # "어느 조항인가": 원문 경로 + 제목 경로 + 같은 제목 경로 안의 순번 (chunker.chunk_keys)
    chunk_key: Mapped[str | None] = mapped_column(Text)
    # "정확히 어떤 문장인가": content(제목 경로 포함 최종 본문)의 해시
    content_sha256: Mapped[str | None] = mapped_column(Text)
    # 권한 사본 (document_acl, documents.security_level에서 복사)
    allowed_departments: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    allowed_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    security_level: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"clearance_level {_LEVEL_RANGE}", name="ck_users_clearance_level"),
        UniqueConstraint("login", name="uq_users_login"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 로그인 id (org.yaml의 users[].id, 이후 SSO 사용자 식별자). API는 이 값으로 사용자를 찾는다
    login: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    clearance_level: Mapped[int] = mapped_column(Integer)
