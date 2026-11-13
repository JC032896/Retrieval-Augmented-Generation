"""채팅 대화(여러 질문을 묶는 단위)와 이어 묻기에서 다시 쓴 질문

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-13

- chat_conversations: 한 대화. 채팅 화면의 왼쪽 목록은 대화 단위로 보인다. 제목은 첫 질문.
  앱 계정은 넣고 읽고 지우고, 마지막 질문 시각(updated_at)만 고칠 수 있다.
  감사 담당 계정은 권한이 없다.
- chat_turns.conversation_id: 질문이 속한 대화. 대화를 지우면 그 질문들도 지워진다.
  기존 기록은 질문 하나가 대화 하나가 되도록 옮긴다 (대화 id = 기록 id).
- chat_turns.search_question, audit_log.search_question: 이어 묻는 질문("그럼 계약직은?")을
  앞 질문들로 다시 쓴 질문. 검색과 답변 요청은 이 질문으로 한다. 감사 재현도 이 질문으로
  요청을 다시 만든다. 다시 쓰지 않았으면(대화의 첫 질문) 비어 있다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rag_app"


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_login", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_chat_conversations_user", "chat_conversations", ["user_login", "updated_at"]
    )
    op.create_index("ix_chat_conversations_updated_at", "chat_conversations", ["updated_at"])
    op.add_column(
        "chat_turns",
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("chat_turns", sa.Column("search_question", sa.Text(), nullable=True))
    op.create_index("ix_chat_turns_conversation", "chat_turns", ["conversation_id", "id"])
    op.add_column("audit_log", sa.Column("search_question", sa.Text(), nullable=True))

    # 기존 기록: 질문 하나 = 대화 하나
    op.execute(
        "INSERT INTO chat_conversations (id, user_login, title, created_at, updated_at) "
        "SELECT id, user_login, left(question, 200), created_at, created_at FROM chat_turns"
    )
    op.execute("UPDATE chat_turns SET conversation_id = id")
    op.execute(
        "SELECT setval(pg_get_serial_sequence('chat_conversations', 'id'), "
        "COALESCE((SELECT max(id) FROM chat_conversations), 0) + 1, false)"
    )

    op.execute("REVOKE ALL ON chat_conversations FROM PUBLIC")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON chat_conversations TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE (updated_at) ON chat_conversations TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SEQUENCE chat_conversations_id_seq TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("audit_log", "search_question")
    op.drop_index("ix_chat_turns_conversation", table_name="chat_turns")
    op.drop_column("chat_turns", "search_question")
    op.drop_column("chat_turns", "conversation_id")
    op.drop_index("ix_chat_conversations_updated_at", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_user", table_name="chat_conversations")
    op.drop_table("chat_conversations")
