"""OpenAI 호환 LLM (vLLM, Ollama): 요청 본문, 답·토큰 수 읽기, 스트리밍, <think> 제거, 오류 처리.

실제 서버 대신 httpx2.MockTransport로 응답을 정해 둔다.
"""

import json
from collections.abc import Callable, Generator
from typing import Any

import httpx2
import pytest

from rag_service.answer.generate import Answer, stream_answer
from rag_service.answer.llm import Completion, LLMError
from rag_service.answer.openai_compat import OpenAICompatibleLLM, strip_reasoning
from rag_service.answer.refusal import REFUSAL_MESSAGE
from rag_service.audit.request import llm_params, request_payload
from rag_service.retrieval.hits import SearchHit

Handler = Callable[[httpx2.Request], httpx2.Response]


def _llm(handler: Handler, api_key: str | None = None) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url="http://gpu:8000/v1/",
        model="local-model",
        api_key=api_key,
        transport=httpx2.MockTransport(handler),
    )


def _reply(content: str, finish: str = "stop", **extra: Any) -> dict[str, Any]:
    return {
        "model": "local-model-q4",
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 8},
        **extra,
    }


def test_complete_sends_system_and_user_messages_and_reads_usage() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_reply("7일 이내입니다. [1]"))

    completion = _llm(handler, api_key="secret").complete(system="규칙", prompt="질문")

    assert completion == Completion("7일 이내입니다. [1]", "local-model-q4", 120, 8)
    [request] = seen
    assert str(request.url) == "http://gpu:8000/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body == {
        "model": "local-model",
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "규칙"},
            {"role": "user", "content": "질문"},
        ],
    }


def test_complete_removes_reasoning_and_tolerates_missing_usage() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        reply = _reply("<think>문서 2를 보면…</think>\n\n답입니다. [2]")
        del reply["usage"], reply["model"]
        return httpx2.Response(200, json=reply)

    completion = _llm(handler).complete(system="s", prompt="p")

    assert completion == Completion("답입니다. [2]", "local-model", 0, 0)
    assert "authorization" not in seen[0].headers  # 키가 없으면 머리글도 없다


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx2.Response(200, json=_reply("잘린 답", finish="length")), "max_tokens"),
        (httpx2.Response(200, json=_reply("", finish="content_filter")), "안전 정책"),
        (httpx2.Response(500, text="GPU 메모리 부족"), "HTTPStatusError"),
        (httpx2.Response(200, text="<html>프록시 오류</html>"), "JSONDecodeError"),
    ],
)
def test_complete_failures_become_llm_errors(response: httpx2.Response, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _llm(lambda request: response).complete(system="s", prompt="p")


def test_unreachable_server_is_an_llm_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("연결 거부", request=request)

    with pytest.raises(LLMError, match="ConnectError"):
        _llm(handler).complete(system="s", prompt="p")


def _sse(*chunks: dict[str, Any] | str) -> httpx2.Response:
    lines = [": keep-alive"]
    for chunk in chunks:
        payload = chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False)
        lines.append(f"data: {payload}")
    body = "\n\n".join(lines) + "\n\n"
    return httpx2.Response(
        200, content=body.encode(), headers={"content-type": "text/event-stream"}
    )


def _delta(text: str, finish: str | None = None) -> dict[str, Any]:
    return {
        "model": "local-model-q4",
        "choices": [{"delta": {"content": text}, "finish_reason": finish}],
    }


def _drain(stream: Generator[str, None, Completion]) -> tuple[list[str], Completion]:
    parts: list[str] = []
    while True:
        try:
            parts.append(next(stream))
        except StopIteration as stop:
            return parts, stop.value


def test_stream_yields_deltas_hides_reasoning_and_reads_final_usage() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return _sse(
            _delta("<thi"),
            _delta("nk>근거를 찾는 중</th"),
            _delta("ink>\n"),
            _delta("7일 이내"),
            _delta("입니다. [1]", finish="stop"),
            {
                "model": "local-model-q4",
                "choices": [],
                "usage": {"prompt_tokens": 50, "completion_tokens": 9},
            },
            "[DONE]",
            _delta("이 뒤는 읽지 않는다"),
        )

    parts, completion = _drain(_llm(handler).stream(system="s", prompt="p"))

    assert parts == ["7일 이내", "입니다. [1]"]
    assert completion == Completion("7일 이내입니다. [1]", "local-model-q4", 50, 9)
    assert (seen[0]["stream"], seen[0]["stream_options"]) == (True, {"include_usage": True})


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["바로 ", "답합니다."], ["바로 ", "답합니다."]),
        (["<"], ["<"]),  # 태그가 아닌 짧은 답
        (["<think>끝나지 않은 생각"], []),
    ],
)
def test_stream_without_reasoning_block(chunks: list[str], expected: list[str]) -> None:
    response = _sse(*[_delta(c) for c in chunks], "[DONE]")

    parts, _ = _drain(_llm(lambda request: response).stream(system="s", prompt="p"))

    assert parts == expected


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_sse(_delta("잘", finish="length")), "max_tokens"),
        (_sse("{깨진 JSON"), "잘못된 스트림"),
        (httpx2.Response(503, text="모델 로딩 중"), "HTTPStatusError"),
    ],
)
def test_stream_failures_become_llm_errors(response: httpx2.Response, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _drain(_llm(lambda request: response).stream(system="s", prompt="p"))


def test_strip_reasoning() -> None:
    assert strip_reasoning("  <think>생각</think>답") == "답"
    assert strip_reasoning("<think>닫히지 않음") == ""
    assert strip_reasoning("답 <think>는 본문</think>") == "답 <think>는 본문</think>"


def test_audit_parameters_rebuild_the_request_description() -> None:
    llm = _llm(lambda request: httpx2.Response(200, json=_reply("답")))
    params = llm_params(llm)

    assert params == {
        "provider": "openai_compatible",
        "base_url": "http://gpu:8000/v1",
        "model": "local-model",
        "max_tokens": 4096,
        "temperature": 0,
    }
    assert request_payload(params, system="s", prompt="p") == llm.request(system="s", prompt="p")


def test_refusal_from_a_local_model_is_hidden_while_streaming() -> None:
    response = _sse(_delta(REFUSAL_MESSAGE[:5]), _delta(REFUSAL_MESSAGE[5:]), "[DONE]")
    hit = SearchHit(1, "a.md", "제목", "절", None, "본문", 0.9)

    deltas = stream_answer("질문", [hit], llm=_llm(lambda request: response))
    parts: list[str] = []
    while True:
        try:
            parts.append(next(deltas))
        except StopIteration as stop:
            answer: Answer = stop.value
            break

    assert parts == []
    assert answer.refused and answer.reason == "not_in_documents"
