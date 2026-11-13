"""직원 채팅 화면의 대화 기록

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-13

- chat_turns: 질문 하나와 그 답(완료 이벤트 내용). 직원이 채팅 화면에서 자기 기록을 다시 보고
  지운다. 감사 기록(audit_log)과 따로 둔다. 감사 DB는 앱 계정이 읽을 수 없고, 직원이 기록을
  지워도 회사의 감사 기록은 남아야 하기 때문이다.
- 앱 계정은 넣고 읽고 지울 수 있다(고칠 수는 없다). 감사 담당 계정은 권한이 없다 (질문 원문은
  이미 감사 기록에 있다).
- 보관 기간(CHAT_HISTORY_DAYS)이 지난 기록은 앱이 새 기록을 넣을 때 지운다 (created_at 색인).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"


def upgrade() -> None:
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("user_login", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("context_files", ARRAY(sa.Text()), nullable=False),
        sa.CheckConstraint("outcome IN ('answered', 'refused')", name="ck_chat_turns_outcome"),
    )
    op.create_index("ix_chat_turns_user", "chat_turns", ["user_login", "id"])
    op.create_index("ix_chat_turns_created_at", "chat_turns", ["created_at"])
    op.execute("REVOKE ALL ON chat_turns FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON chat_turns TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SEQUENCE chat_turns_id_seq TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_chat_turns_created_at", table_name="chat_turns")
    op.drop_index("ix_chat_turns_user", table_name="chat_turns")
    op.drop_table("chat_turns")
