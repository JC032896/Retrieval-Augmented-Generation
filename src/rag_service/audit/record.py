"""감사 기록 만들기, 저장(조각 스냅샷 포함), 보관 기간이 지난 기록 삭제."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.generate import Answer
from rag_service.answer.llm import Completion, estimate_cost
from rag_service.answer.prompt import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT, build_prompt
from rag_service.api.auth import CurrentUser
from rag_service.audit.models import AuditLog, ChunkSnapshot
from rag_service.audit.request import content_sha256, context_chunks, request_sha256
from rag_service.retrieval.hits import SearchHit

Outcome = Literal["answered", "refused", "error", "cancelled"]  # models.AUDIT_OUTCOMES와 같다


@dataclass(frozen=True)
class AuditPolicy:
    store_text: bool = True  # 질문·답변 원문 저장 (끄면 길이와 해시만)
    retention_days: int | None = None  # purge가 이보다 오래된 기록을 지운다 (None: 지우지 않음)
    log_prompts: bool = False  # LLM 요청 원문을 DEBUG 로그로 (개발 전용, config.Settings 참고)


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
    # LLM 요청에 넣은 근거 조각 (순서 = 프롬프트 번호). 점수 관문에서 거절했으면 비어 있다
    request_context: tuple[SearchHit, ...] = ()
    # 화면에 보낸 done 이벤트 내용. 채팅 화면의 대화 기록이 쓴다 (감사 기록에는 넣지 않는다)
    payload: Mapping[str, Any] | None = None
    # 이어 묻는 질문을 다시 쓴 질문 (answer/followup.py). 검색과 LLM 요청은 이 질문으로 했다
    search_question: str | None = None
    rewrite_completion: Completion | None = None  # 다시 쓰기에 쓴 LLM 호출 (비용에 더한다)


def build_entry(
    *,
    request_id: str,
    client_ip: str | None,
    user: CurrentUser,
    question: str,
    result: AskResult,
    policy: AuditPolicy,
    llm_params: Mapping[str, Any] | None = None,
) -> AuditLog:
    """llm_params는 audit.request.llm_params(llm). LLM을 불렀을 때만 재현 정보를 남긴다."""
    answer = result.answer
    completion = answer.completion if answer else None
    sent = result.request_context
    asked = result.search_question or question  # LLM 요청에 실제로 넣은 질문
    replayable = bool(sent) and llm_params is not None
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
        search_question=result.search_question if policy.store_text else None,
        answer=answer.text if answer and policy.store_text else None,
        outcome=result.outcome,
        refusal_reason=answer.reason if answer else None,
        context_files=list(result.context_files),
        cited_files=list(dict.fromkeys(c.file for c in answer.citations)) if answer else [],
        verified=result.verified,
        model=completion.model if completion else None,
        input_tokens=completion.input_tokens if completion else None,
        output_tokens=completion.output_tokens if completion else None,
        cost_usd=_cost(completion, result.rewrite_completion),
        retrieval_ms=result.retrieval_ms,
        first_token_ms=result.first_token_ms,
        total_ms=result.total_ms,
        prompt_template_version=PROMPT_TEMPLATE_VERSION if replayable else None,
        model_params=dict(llm_params) if replayable and llm_params is not None else None,
        context_chunks=[dict(chunk) for chunk in context_chunks(sent)] if replayable else None,
        request_sha256=(
            request_sha256(llm_params, system=SYSTEM_PROMPT, prompt=build_prompt(asked, sent))
            if replayable and llm_params is not None
            else None
        ),
    )


def _cost(*completions: Completion | None) -> float | None:
    """답변과 질문 다시 쓰기의 비용 합. 요금표에 없는 모델은 0으로 본다.

    LLM을 부르지 않았거나 모두 요금표에 없으면 None.
    """
    used = [c for c in completions if c is not None]
    if not used:
        return None
    costs = [estimate_cost(c.model, c.input_tokens, c.output_tokens) for c in used]
    if all(cost is None for cost in costs):
        return None
    return sum(cost or 0.0 for cost in costs)


def write_entry(
    sessions: sessionmaker[Session], entry: AuditLog, snapshots: Sequence[SearchHit] = ()
) -> None:
    """감사 기록과, 요청에 넣은 조각 본문(snapshots)을 한 트랜잭션으로 저장한다.

    본문은 내용 해시당 한 번만 저장한다 (이미 있으면 건너뜀). 앱 계정(rag_app)은 chunk_snapshots를
    읽을 수 없다. 충돌 대상을 적은 ON CONFLICT (content_sha256)는 SELECT 권한이 필요하므로,
    대상 없는 ON CONFLICT DO NOTHING을 쓴다 (유일 제약이 기본 키 하나뿐이라 결과는 같다).
    """
    rows = {content_sha256(hit.content): hit.content for hit in snapshots}
    with sessions.begin() as session:
        if rows:
            session.execute(
                insert(ChunkSnapshot)
                .values([{"content_sha256": k, "content": v} for k, v in rows.items()])
                .on_conflict_do_nothing()
            )
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


# 조각 목록이 없는 기록(0007 이전, LLM을 부르지 않음)은 배열이 아니므로 건너뛴다
ORPHAN_SNAPSHOTS = text(
    "DELETE FROM chunk_snapshots s WHERE NOT EXISTS ("
    " SELECT 1 FROM audit_log a CROSS JOIN LATERAL jsonb_array_elements("
    "  CASE WHEN jsonb_typeof(a.context_chunks) = 'array' THEN a.context_chunks END) e"
    " WHERE e->>'content_sha256' = s.content_sha256)"
)


def purge_orphan_snapshots(session: Session) -> int:
    """어느 감사 기록도 가리키지 않는 조각 스냅샷을 지우고 지운 개수를 돌려준다."""
    return session.connection().execute(ORPHAN_SNAPSHOTS).rowcount
