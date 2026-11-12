"""관리 화면에서 올린 문서와 문서 변경 이력

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12

- documents.origin: folder(문서 폴더의 acl.yaml에서 수집, 관리 화면에서는 읽기 전용) 또는
  upload(관리 화면에서 올림, 권한의 원본은 DB). 기존 행은 모두 folder다.
- documents.owner_department: 올린 문서를 관리하는 부서. 부서 문서 담당자는 자기 부서 문서만
  바꾼다. upload 문서에는 반드시 있다.
- document_changes: 올리기, 파일 교체, 권한 변경, 삭제의 이력 (누가, 언제, 전후 값).
  앱 계정은 넣고 읽기만 하고 고치거나 지울 수 없다. 감사 담당 계정도 읽을 수 있다.
  문서를 지워도 이력은 남도록 documents를 외래 키로 묶지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"
AUDITOR_ROLE = "rag_auditor"


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("origin", sa.Text(), server_default=sa.text("'folder'"), nullable=False),
    )
    op.add_column("documents", sa.Column("owner_department", sa.Text(), nullable=True))
    op.create_check_constraint("ck_documents_origin", "documents", "origin IN ('folder', 'upload')")
    op.create_check_constraint(
        "ck_documents_upload_owner",
        "documents",
        "origin = 'folder' OR owner_department IS NOT NULL",
    )

    op.create_table(
        "document_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor_login", sa.Text(), nullable=False),
        sa.Column("before", JSONB(none_as_null=True), nullable=True),
        sa.Column("after", JSONB(none_as_null=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('upload', 'replace', 'access', 'delete')",
            name="ck_document_changes_action",
        ),
    )
    op.create_index(
        "ix_document_changes_document", "document_changes", ["document_id", "created_at"]
    )
    op.execute("REVOKE ALL ON document_changes FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT ON document_changes TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SEQUENCE document_changes_id_seq TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON document_changes TO {AUDITOR_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_document_changes_document", table_name="document_changes")
    op.drop_table("document_changes")
    op.drop_constraint("ck_documents_upload_owner", "documents", type_="check")
    op.drop_constraint("ck_documents_origin", "documents", type_="check")
    op.drop_column("documents", "owner_department")
    op.drop_column("documents", "origin")
