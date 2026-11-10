"""감사 기록 테이블. 업무 데이터(db/models.py)와 메타데이터를 나눈다.

감사 기록은 보관 기간, 접근 권한, 백업 정책이 업무 데이터와 다르다. 따로 두면 나중에 별도 DB나
읽기 전용 권한으로 옮기기 쉽다. 테이블은 migrations/의 Alembic 마이그레이션(0004)으로 만든다.

사용자는 외래 키가 아니라 그 시점의 값(로그인 id, 부서, 역할, 등급)을 복사해 둔다. 퇴사로 사용자가
지워지거나 부서가 바뀌어도 "그때 어떤 권한으로 무엇을 봤는지"가 남아야 하기 때문이다.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# DB 역할 (마이그레이션 0005). 앱은 감사 테이블에 쓰기만, 감사자는 읽기만 한다
APP_ROLE = "rag_app"
AUDITOR_ROLE = "rag_auditor"

# answered 답함, refused 거절, error 실패, cancelled 사용자가 연결을 끊음
AUDIT_OUTCOMES = ("answered", "refused", "error", "cancelled")


class AuditBase(DeclarativeBase):
    pass


class AuditLog(AuditBase):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "outcome IN (" + ", ".join(f"'{o}'" for o in AUDIT_OUTCOMES) + ")",
            name="ck_audit_log_outcome",
        ),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_user_login", "user_login", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str] = mapped_column(Text)  # 응답 머리글 X-Request-ID, 운영 로그와 같은 값
    client_ip: Mapped[str | None] = mapped_column(Text)

    # 그 시점의 사용자와 권한
    user_login: Mapped[str] = mapped_column(Text)
    user_department: Mapped[str] = mapped_column(Text)
    user_role: Mapped[str] = mapped_column(Text)
    user_clearance_level: Mapped[int] = mapped_column(Integer)

    # 원문은 설정(AUDIT_STORE_TEXT)으로 끌 수 있다. 꺼도 길이와 해시는 남는다
    question: Mapped[str | None] = mapped_column(Text)
    question_sha256: Mapped[str] = mapped_column(Text)
    question_chars: Mapped[int] = mapped_column(Integer)
    answer: Mapped[str | None] = mapped_column(Text)

    outcome: Mapped[str] = mapped_column(Text)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    context_files: Mapped[list[str]] = mapped_column(ARRAY(Text))  # LLM에 보낸 근거 문서
    cited_files: Mapped[list[str]] = mapped_column(ARRAY(Text))  # 답변이 인용한 문서
    verified: Mapped[bool | None] = mapped_column(Boolean)  # 인용 검증 통과 여부

    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    retrieval_ms: Mapped[int] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)  # 첫 글자를 보낼 때까지 (검색 포함)
    total_ms: Mapped[int] = mapped_column(Integer)


class ChunkSnapshot(AuditBase):
    """감사 기록이 가리키는 청크 본문. 내용 해시당 한 번만 저장한다 (3단계에서 채운다).

    원문이 재수집으로 바뀌어도 "그때 LLM이 본 본문"을 복원하려고 둔다. 기밀 문서의 본문 사본이므로
    읽기는 감사자 역할(rag_auditor)만 한다.
    """

    __tablename__ = "chunk_snapshots"

    content_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
