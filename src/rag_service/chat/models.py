"""대화 기록 테이블 (마이그레이션 0011).

업무 테이블(db.models.Base)과 권한이 다르므로 따로 둔다: 앱 계정은 넣고 읽고 지울 수 있고(고칠 수
없음), 감사 담당 계정은 권한이 없다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TURN_OUTCOMES = ("answered", "refused")  # 오류나 끊긴 질문은 남기지 않는다 (감사 기록에는 남는다)


class ChatBase(DeclarativeBase):
    pass


class ChatTurn(ChatBase):
    __tablename__ = "chat_turns"
    __table_args__ = (
        CheckConstraint(
            "outcome IN (" + ", ".join(f"'{o}'" for o in TURN_OUTCOMES) + ")",
            name="ck_chat_turns_outcome",
        ),
        Index("ix_chat_turns_user", "user_login", "id"),
        Index("ix_chat_turns_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str] = mapped_column(Text)  # 감사 기록·운영 로그와 같은 값
    user_login: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    # 질문 API의 done 이벤트 내용 (사용량 제외). 화면은 실시간 답과 같은 방식으로 다시 그린다
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # LLM에 보낸 근거 문서. 다시 열 때 이 문서들을 지금도 볼 수 있는지 확인한다
    context_files: Mapped[list[str]] = mapped_column(ARRAY(Text))
