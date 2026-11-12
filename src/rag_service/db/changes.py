"""문서 변경 이력 (마이그레이션 0009). 관리 화면에서 올리기, 파일 교체, 권한 변경, 삭제를 남긴다.

업무 테이블(models.Base)과 감사 테이블(audit.models.AuditBase)처럼 권한이 다르므로 따로 둔다:
앱 계정은 넣고 읽기만 하고(고치거나 지울 수 없음), 감사 담당 계정도 읽을 수 있다.
문서를 지워도 이력이 남도록 documents를 외래 키로 묶지 않는다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

CHANGE_ACTIONS = ("upload", "replace", "access", "delete")


class ChangeBase(DeclarativeBase):
    pass


class DocumentChange(ChangeBase):
    __tablename__ = "document_changes"
    __table_args__ = (
        CheckConstraint(
            "action IN (" + ", ".join(f"'{a}'" for a in CHANGE_ACTIONS) + ")",
            name="ck_document_changes_action",
        ),
        Index("ix_document_changes_document", "document_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document_id: Mapped[int] = mapped_column(Integer)
    source_path: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    actor_login: Mapped[str] = mapped_column(Text)
    # 권한·제목·파일 해시 등 바뀐 값 (올리기는 after만, 삭제는 before만)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
