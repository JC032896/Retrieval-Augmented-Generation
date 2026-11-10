"""POST /ask: 질문 → 권한 안에서 검색 → 인용 답변을 SSE(Server-Sent Events)로 스트리밍.

사용자 확인, 입력 검증, 검색은 응답을 열기 전에 끝낸다. 그래서 이 단계의 실패는 일반 HTTP 오류
(401, 422, 503)로 돌아간다. 스트림이 열린 뒤에는 아래 이벤트만 보낸다.

  event: delta  data: {"text": "..."}       답변 조각. 이어 붙여 화면에 보여 준다
  event: done   data: {답변, 인용, 검증}  마지막 이벤트. text가 최종 답변이다 (delta를 대신함)
  event: error  data: {"code", "message"}   LLM 실패. 이 이벤트로 스트림이 끝난다

LLM이 거절하면 delta 없이 done(refused=true)만 온다 (generate.stream_answer 참고).

질문마다 응답 머리글 X-Request-ID를 붙이고, 스트림이 끝나면(연결이 끊겨도) 감사 기록(DB)과 운영
로그(JSON, 원문 제외)를 남긴다. 사용자 확인 실패도 운영 로그에 남긴다.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable, Generator
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, format_sse_event
from pydantic import BaseModel, StringConstraints

from rag_service.answer.generate import DEFAULT_CONTEXT_SIZE, Answer, stream_answer
from rag_service.answer.llm import LLMError, StreamingLLM, estimate_cost
from rag_service.answer.verify import verify_answer
from rag_service.api.auth import AuthError, AuthUnavailableError, CurrentUser, load_user
from rag_service.api.services import Services, get_services
from rag_service.audit.record import AskResult, Outcome, build_entry, write_entry
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.logs import log_event
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.search import search

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_QUESTION_CHARS = 1000
# 401 응답에 붙이는 표준 머리글 (토큰을 Bearer 방식으로 보내라는 뜻)
BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

ServicesDep = Annotated[Services, Depends(get_services)]


class AskRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


def current_user(request: Request, services: ServicesDep) -> CurrentUser:
    if services.authenticator is None:
        raise HTTPException(503, "사용자 확인 방식이 설정되지 않았습니다 (AUTH_MODE)")
    client_ip = _client_ip(request)
    try:
        login = services.authenticator.login(request.headers)
    except AuthError as error:
        log_event(
            logger, "auth_failed", level=logging.WARNING, reason=str(error), client_ip=client_ip
        )
        raise HTTPException(401, str(error), headers=BEARER_CHALLENGE) from error
    except AuthUnavailableError as error:
        logger.exception("사용자 확인 수단이 동작하지 않음")
        raise HTTPException(503, str(error)) from error
    with services.sessions() as session:
        user = load_user(session, login)
    if user is None:
        log_event(
            logger,
            "auth_failed",
            level=logging.WARNING,
            reason="unregistered",
            login=login,
            client_ip=client_ip,
        )
        raise HTTPException(401, "등록되지 않은 사용자입니다", headers=BEARER_CHALLENGE)
    return user


# response_class=EventSourceResponse는 함수가 생성기일 때 쓰는 표시다. 여기서는 검색을 응답 전에
# 끝내려고 일반 함수에서 응답 객체를 직접 돌려주므로, 문서(OpenAPI)에만 형식을 적는다
@router.post("/ask", responses={200: {"content": {"text/event-stream": {}}}})
def ask(
    request: Request,
    body: AskRequest,
    user: Annotated[CurrentUser, Depends(current_user)],
    services: ServicesDep,
) -> EventSourceResponse:
    if services.llm is None:
        raise HTTPException(503, "답변 LLM이 설정되지 않았습니다 (ANTHROPIC_API_KEY)")
    request_id = uuid.uuid4().hex
    started = time.perf_counter()
    with services.sessions() as session:
        hits = search(
            session,
            query=body.question,
            query_vector=services.embedder.embed([body.question])[0],
            viewer=user,
            tokenizer=services.tokenizer,
            retriever="vector_rerank",  # 평가 1위 (README 6절)
            limit=DEFAULT_CONTEXT_SIZE,
            reranker=services.reranker,
        )
    retrieval_ms = _elapsed_ms(started)

    def finish(result: AskResult) -> None:
        record_ask(
            services,
            request_id=request_id,
            client_ip=_client_ip(request),
            user=user,
            question=body.question,
            result=result,
        )

    events = answer_events(
        body.question,
        hits,
        llm=services.llm,
        tokenizer=services.tokenizer,
        started=started,
        retrieval_ms=retrieval_ms,
        on_finish=finish,
    )
    # 프록시(nginx 등)가 응답을 모아 두지 않고 바로 흘려보내게 한다
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id}
    return EventSourceResponse(events, headers=headers)


def answer_events(
    question: str,
    hits: list[SearchHit],
    *,
    llm: StreamingLLM,
    tokenizer: KoreanTokenizer,
    on_finish: Callable[[AskResult], None],
    started: float | None = None,
    retrieval_ms: int = 0,
) -> Generator[bytes, None, None]:
    """SSE 이벤트를 만든다. 끝나면(오류, 연결 끊김 포함) on_finish에 결과를 넘긴다."""
    clock = _FirstEvent(time.perf_counter() if started is None else started)
    outcome: Outcome | None = None
    answer: Answer | None = None
    verified: bool | None = None
    try:
        try:
            answer = yield from _deltas(stream_answer(question, hits, llm=llm), clock)
        except LLMError:
            logger.exception("답변 생성 실패")
            outcome = "error"
            clock.mark()
            yield _event(
                "error", {"code": "generation_failed", "message": "답변을 만들지 못했습니다."}
            )
            return
        payload = answer_payload(answer, question=question, tokenizer=tokenizer)
        if payload["verification"] is not None:
            verified = payload["verification"]["verified"]
        outcome = "refused" if answer.refused else "answered"
        clock.mark()
        yield _event("done", payload)
    except GeneratorExit:
        outcome = outcome or "cancelled"  # 클라이언트가 답을 다 받기 전에 연결을 끊었다
        raise
    finally:
        context = answer.context if answer is not None else hits[:DEFAULT_CONTEXT_SIZE]
        on_finish(
            AskResult(
                outcome=outcome or "error",  # 예상하지 못한 예외
                answer=answer,
                verified=verified,
                context_files=tuple(dict.fromkeys(hit.file for hit in context)),
                retrieval_ms=retrieval_ms,
                first_token_ms=clock.first_ms,
                total_ms=clock.elapsed_ms(),
            )
        )


def record_ask(
    services: Services,
    *,
    request_id: str,
    client_ip: str | None,
    user: CurrentUser,
    question: str,
    result: AskResult,
) -> None:
    """감사 기록(DB)과 운영 로그를 남긴다. 실패해도 이미 보낸 답변에는 영향을 주지 않는다."""
    entry = build_entry(
        request_id=request_id,
        client_ip=client_ip,
        user=user,
        question=question,
        result=result,
        policy=services.audit,
    )
    log_event(
        logger,
        "ask",
        request_id=request_id,
        user=user.login,
        outcome=entry.outcome,
        refusal_reason=entry.refusal_reason,
        context_files=len(entry.context_files),
        verified=entry.verified,
        model=entry.model,
        input_tokens=entry.input_tokens,
        output_tokens=entry.output_tokens,
        cost_usd=entry.cost_usd,
        retrieval_ms=entry.retrieval_ms,
        first_token_ms=entry.first_token_ms,
        total_ms=entry.total_ms,
    )
    try:
        write_entry(services.sessions, entry)
    except Exception:
        # 감사 기록 누락은 운영자가 반드시 알아야 한다. 로그 수집 시스템에서 경보를 건다
        logger.exception("audit_write_failed", extra={"fields": {"request_id": request_id}})


class _FirstEvent:
    """요청 시작부터 첫 이벤트(답변 조각, 거절, 오류)를 보낼 때까지의 시간을 잰다."""

    def __init__(self, started: float) -> None:
        self.started = started
        self.first_ms: int | None = None

    def mark(self) -> None:
        if self.first_ms is None:
            self.first_ms = self.elapsed_ms()

    def elapsed_ms(self) -> int:
        return _elapsed_ms(self.started)


def _deltas(
    stream: Generator[str, None, Answer], clock: _FirstEvent
) -> Generator[bytes, None, Answer]:
    try:
        while True:
            try:
                text = next(stream)
            except StopIteration as stop:
                answer: Answer = stop.value
                return answer
            clock.mark()
            yield _event("delta", {"text": text})
    finally:
        stream.close()  # 클라이언트가 연결을 끊으면 LLM 스트림도 닫는다


def answer_payload(answer: Answer, *, question: str, tokenizer: KoreanTokenizer) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": answer.text,
        "refused": answer.refused,
        "reason": answer.reason,
        "citations": [asdict(citation) for citation in answer.citations],
        "invalid_citations": list(answer.invalid_citations),
        "verification": None,
        "usage": None,
    }
    if not answer.refused:
        verification = verify_answer(
            answer.text, answer.context, question=question, tokenizer=tokenizer
        )
        payload["verification"] = {
            "verified": verification.verified,
            "problems": [
                {
                    "text": check.text,
                    "status": check.status,
                    "unsupported_numbers": list(check.unsupported_numbers),
                }
                for check in verification.problems
            ],
        }
    if answer.completion is not None:
        c = answer.completion
        payload["usage"] = {
            "model": c.model,
            "input_tokens": c.input_tokens,
            "output_tokens": c.output_tokens,
            "cost_usd": estimate_cost(c.model, c.input_tokens, c.output_tokens),
        }
    return payload


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _client_ip(request: Request) -> str | None:
    # 프록시 뒤에서는 uvicorn --proxy-headers --forwarded-allow-ips로 실제 주소를 받는다
    return request.client.host if request.client else None


def _event(name: str, data: dict[str, Any]) -> bytes:
    return format_sse_event(event=name, data_str=json.dumps(data, ensure_ascii=False))
