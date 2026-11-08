"""DB 스키마 (SQLAlchemy 모델). 실제 테이블은 migrations/의 Alembic 마이그레이션으로 만든다.

권한 규칙: 사용자는 아래 두 조건을 모두 만족하는 조각만 볼 수 있다.
  1. 사용자의 부서가 allowed_departments에 있거나, 역할이 allowed_roles에 있다 (OR)
  2. 사용자의 clearance_level >= 조각의 security_level

권한의 원본은 document_acl이고, chunks의 권한 컬럼은 검색 SQL의 WHERE 절에서
바로 걸러내기 위한 사본이다. 권한이 바뀌면 사본만 갱신하고 임베딩은 다시 만들지 않는다.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
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


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"security_level {_LEVEL_RANGE}", name="ck_documents_security_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text, unique=True)
    security_level: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    # 권한 사본 (document_acl, documents.security_level에서 복사)
    allowed_departments: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    allowed_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    security_level: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"clearance_level {_LEVEL_RANGE}", name="ck_users_clearance_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    clearance_level: Mapped[int] = mapped_column(Integer)
