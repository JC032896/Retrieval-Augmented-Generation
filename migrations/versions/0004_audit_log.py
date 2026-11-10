"""audit_log: 질문 하나마다 누가, 언제, 무엇을 물었고 어떤 문서로 어떻게 답했는지

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column("user_login", sa.Text(), nullable=False),
        sa.Column("user_department", sa.Text(), nullable=False),
        sa.Column("user_role", sa.Text(), nullable=False),
        sa.Column("user_clearance_level", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("question_sha256", sa.Text(), nullable=False),
        sa.Column("question_chars", sa.Integer(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("context_files", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("cited_files", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("retrieval_ms", sa.Integer(), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('answered', 'refused', 'error', 'cancelled')", name="ck_audit_log_outcome"
        ),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_user_login", "audit_log", ["user_login", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
