"""POST /ask: 질문 → 권한 안에서 검색 → 인용 답변을 SSE(Server-Sent Events)로 스트리밍.

사용자 확인, 입력 검증, 검색은 응답을 열기 전에 끝낸다. 그래서 이 단계의 실패는 일반 HTTP 오류
(401, 422, 503)로 돌아간다. 스트림이 열린 뒤에는 아래 이벤트만 보낸다.

  event: delta  data: {"text": "..."}       답변 조각. 이어 붙여 화면에 보여 준다
  event: done   data: {답변, 인용, 검증}  마지막 이벤트. text가 최종 답변이다 (delta를 대신함)
  event: error  data: {"code", "message"}   LLM 실패. 이 이벤트로 스트림이 끝난다

LLM이 거절하면 delta 없이 done(refused=true)만 온다 (generate.stream_answer 참고).
"""

import json
import logging
from collections.abc import Generator, Iterator
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse, format_sse_event
from pydantic import BaseModel, StringConstraints

from rag_service.answer.generate import DEFAULT_CONTEXT_SIZE, Answer, stream_answer
from rag_service.answer.llm import LLMError, StreamingLLM, estimate_cost
from rag_service.answer.verify import verify_answer
from rag_service.api.auth import AuthError, CurrentUser, load_user
from rag_service.api.services import Services, get_services
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.search import search

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_QUESTION_CHARS = 1000

ServicesDep = Annotated[Services, Depends(get_services)]


class AskRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


def current_user(request: Request, services: ServicesDep) -> CurrentUser:
    if services.authenticator is None:
        raise HTTPException(503, "사용자 확인 방식이 설정되지 않았습니다 (AUTH_MODE)")
    try:
        login = services.authenticator.login(request.headers)
    except AuthError as error:
        raise HTTPException(401, str(error)) from error
    with services.sessions() as session:
        user = load_user(session, login)
    if user is None:
        raise HTTPException(401, "등록되지 않은 사용자입니다")
    return user


# response_class=EventSourceResponse는 함수가 생성기일 때 쓰는 표시다. 여기서는 검색을 응답 전에
# 끝내려고 일반 함수에서 응답 객체를 직접 돌려주므로, 문서(OpenAPI)에만 형식을 적는다
@router.post("/ask", responses={200: {"content": {"text/event-stream": {}}}})
def ask(
    body: AskRequest,
    user: Annotated[CurrentUser, Depends(current_user)],
    services: ServicesDep,
) -> EventSourceResponse:
    if services.llm is None:
        raise HTTPException(503, "답변 LLM이 설정되지 않았습니다 (ANTHROPIC_API_KEY)")
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
    events = answer_events(body.question, hits, llm=services.llm, tokenizer=services.tokenizer)
    # 프록시(nginx 등)가 응답을 모아 두지 않고 바로 흘려보내게 한다
    return EventSourceResponse(
        events, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


def answer_events(
    question: str, hits: list[SearchHit], *, llm: StreamingLLM, tokenizer: KoreanTokenizer
) -> Iterator[bytes]:
    stream = stream_answer(question, hits, llm=llm)
    try:
        answer = yield from _deltas(stream)
    except LLMError:
        logger.exception("답변 생성 실패")
        yield _event("error", {"code": "generation_failed", "message": "답변을 만들지 못했습니다."})
        return
    yield _event("done", answer_payload(answer, question=question, tokenizer=tokenizer))


def _deltas(stream: Generator[str, None, Answer]) -> Generator[bytes, None, Answer]:
    try:
        while True:
            try:
                text = next(stream)
            except StopIteration as stop:
                answer: Answer = stop.value
                return answer
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


def _event(name: str, data: dict[str, Any]) -> bytes:
    return format_sse_event(event=name, data_str=json.dumps(data, ensure_ascii=False))
