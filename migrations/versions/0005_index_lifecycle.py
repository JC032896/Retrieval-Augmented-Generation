"""인덱스 수명 관리: 원문 해시·임베딩 모델·시행일, 조각 키·본문 해시, 감사용 조각 스냅샷, DB 역할

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-11

- 새 컬럼은 모두 비어 있을 수 있다. 0005 이전에 수집한 행은 값이 없고, 재수집하면 채워진다
  (제목 경로가 DB에 없어 기존 행에서 chunk_key를 계산할 수 없으므로 백필하지 않는다).
- chunk_snapshots는 감사 기록이 가리키는 청크 본문 사본이다. 기밀 문서 본문이 들어가므로
  읽기를 감사자 역할로 제한한다.
- DB 역할 (NOLOGIN, 실제 로그인 계정에 부여해서 쓴다)
    rag_app      앱 계정: 업무 테이블 읽기·쓰기, 감사 테이블(audit_log, chunk_snapshots)은 쓰기만
    rag_auditor  감사자 계정: 감사 테이블 읽기만
  역할은 DB 클러스터 전체에 하나씩이라 이미 있으면 다시 만들지 않고, downgrade에서도 지우지 않는다
  (같은 서버의 다른 DB가 쓰고 있을 수 있다). 역할을 만들려면 마이그레이션 계정에 CREATEROLE이
  필요하다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"
AUDITOR_ROLE = "rag_auditor"
BUSINESS_TABLES = "documents, document_acl, chunks, users"
AUDIT_TABLES = "audit_log, chunk_snapshots"


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_sha256", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("source_mtime", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("embedding_model", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("effective_from", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("effective_to", sa.Date(), nullable=True))

    op.add_column("chunks", sa.Column("chunk_key", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("content_sha256", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_chunks_document_key", "chunks", ["document_id", "chunk_key"])

    op.create_table(
        "chunk_snapshots",
        sa.Column("content_sha256", sa.Text(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    for role in (APP_ROLE, AUDITOR_ROLE):
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}, {AUDITOR_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {BUSINESS_TABLES} TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON {AUDIT_TABLES} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON {AUDIT_TABLES} TO {AUDITOR_ROLE}")
    op.execute(f"REVOKE ALL ON {AUDIT_TABLES} FROM PUBLIC")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON audit_log FROM {APP_ROLE}, {AUDITOR_ROLE}")
    op.execute(f"REVOKE ALL ON {BUSINESS_TABLES} FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}, {AUDITOR_ROLE}")
    op.drop_table("chunk_snapshots")
    op.drop_constraint("uq_chunks_document_key", "chunks", type_="unique")
    op.drop_column("chunks", "content_sha256")
    op.drop_column("chunks", "chunk_key")
    for column in (
        "effective_to",
        "effective_from",
        "embedding_model",
        "source_mtime",
        "content_sha256",
    ):
        op.drop_column("documents", column)
