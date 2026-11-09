"""documents.status: 문서 수명 (current 현행, superseded 폐지/대체)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 기존 문서는 모두 현행으로 둔다 (server_default가 기존 행도 채운다)
    op.add_column(
        "documents",
        sa.Column("status", sa.Text(), server_default=sa.text("'current'"), nullable=False),
    )
    op.create_check_constraint(
        "ck_documents_status", "documents", "status IN ('current', 'superseded')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_documents_status", "documents", type_="check")
    op.drop_column("documents", "status")
