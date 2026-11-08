"""초기 스키마: documents, document_acl, chunks, users

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # 마이그레이션은 작성 시점의 값을 고정해서 쓴다 (models.py를 import하지 않음)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False, unique=True),
        sa.Column("security_level", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("security_level BETWEEN 0 AND 3", name="ck_documents_security_level"),
    )

    op.create_table(
        "document_acl",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.UniqueConstraint("document_id", "kind", "value", name="uq_document_acl"),
        sa.CheckConstraint("kind IN ('department', 'role')", name="ck_document_acl_kind"),
    )
    op.create_index("ix_document_acl_document_id", "document_acl", ["document_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("tokens", postgresql.TSVECTOR(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            "allowed_departments",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "allowed_roles",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("security_level", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        sa.CheckConstraint("security_level BETWEEN 0 AND 3", name="ck_chunks_security_level"),
    )
    op.create_index("ix_chunks_tokens", "chunks", ["tokens"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_allowed_departments",
        "chunks",
        ["allowed_departments"],
        postgresql_using="gin",
    )
    op.create_index("ix_chunks_allowed_roles", "chunks", ["allowed_roles"], postgresql_using="gin")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("department", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("clearance_level", sa.Integer(), nullable=False),
        sa.CheckConstraint("clearance_level BETWEEN 0 AND 3", name="ck_users_clearance_level"),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("chunks")
    op.drop_table("document_acl")
    op.drop_table("documents")
    # vector 확장은 다른 스키마가 쓰고 있을 수 있으므로 지우지 않는다
