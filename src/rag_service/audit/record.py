"""감사 기록 만들기, 저장, 보관 기간이 지난 기록 삭제."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.generate import Answer
from rag_service.answer.llm import estimate_cost
from rag_service.api.auth import CurrentUser
from rag_service.audit.models import AuditLog

Outcome = Literal["answered", "refused", "error", "cancelled"]  # models.AUDIT_OUTCOMES와 같다


@dataclass(frozen=True)
class AuditPolicy:
    store_text: bool = True  # 질문·답변 원문 저장 (끄면 길이와 해시만)
    retention_days: int = 90  # purge 명령이 이보다 오래된 기록을 지운다


@dataclass(frozen=True)
class AskResult:
    """질문 하나를 처리한 결과. 감사 기록과 운영 로그가 같은 값을 쓴다."""

    outcome: Outcome
    answer: Answer | None  # error, cancelled면 None일 수 있다
    verified: bool | None
    context_files: tuple[str, ...]
    retrieval_ms: int
    first_token_ms: int | None
    total_ms: int


def build_entry(
    *,
    request_id: str,
    client_ip: str | None,
    user: CurrentUser,
    question: str,
    result: AskResult,
    policy: AuditPolicy,
) -> AuditLog:
    answer = result.answer
    completion = answer.completion if answer else None
    return AuditLog(
        request_id=request_id,
        client_ip=client_ip,
        user_login=user.login,
        user_department=user.department,
        user_role=user.role,
        user_clearance_level=user.clearance_level,
        question=question if policy.store_text else None,
        question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        question_chars=len(question),
        answer=answer.text if answer and policy.store_text else None,
        outcome=result.outcome,
        refusal_reason=answer.reason if answer else None,
        context_files=list(result.context_files),
        cited_files=list(dict.fromkeys(c.file for c in answer.citations)) if answer else [],
        verified=result.verified,
        model=completion.model if completion else None,
        input_tokens=completion.input_tokens if completion else None,
        output_tokens=completion.output_tokens if completion else None,
        cost_usd=(
            estimate_cost(completion.model, completion.input_tokens, completion.output_tokens)
            if completion
            else None
        ),
        retrieval_ms=result.retrieval_ms,
        first_token_ms=result.first_token_ms,
        total_ms=result.total_ms,
    )


def write_entry(sessions: sessionmaker[Session], entry: AuditLog) -> None:
    with sessions.begin() as session:
        session.add(entry)


def purge(session: Session, *, older_than_days: int, now: datetime | None = None) -> int:
    """older_than_days일보다 오래된 기록을 지우고 지운 개수를 돌려준다.

    커밋은 호출하는 쪽에서 한다.
    """
    if older_than_days < 1:
        raise ValueError("보관 기간은 1일 이상이어야 합니다")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    result = session.connection().execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    return result.rowcount
