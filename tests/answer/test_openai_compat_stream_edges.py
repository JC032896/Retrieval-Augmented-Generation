"""OpenAI 호환 스트림의 경계 상황: 역할만 있는 첫 조각, [DONE] 없이 끝남, </think> 바로 뒤의 답."""

import json
from typing import Any

import httpx2

from rag_service.answer.llm import Completion
from rag_service.answer.openai_compat import OpenAICompatibleLLM


def _stream(*chunks: dict[str, Any]) -> tuple[list[str], Completion]:
    body = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body.encode())

    llm = OpenAICompatibleLLM(
        base_url="http://gpu/v1", model="m", transport=httpx2.MockTransport(handler)
    )
    stream = llm.stream(system="s", prompt="p")
    parts: list[str] = []
    while True:
        try:
            parts.append(next(stream))
        except StopIteration as stop:
            return parts, stop.value


def _delta(**delta: str) -> dict[str, Any]:
    return {"choices": [{"delta": delta, "finish_reason": None}]}


def test_role_only_chunk_and_stream_ending_without_done() -> None:
    parts, completion = _stream(_delta(role="assistant"), _delta(content="답 [1]"))

    assert parts == ["답 [1]"]
    assert completion == Completion("답 [1]", "m", 0, 0)


def test_answer_in_the_same_chunk_as_the_closing_think_tag() -> None:
    parts, completion = _stream(_delta(content="<think>생각</think>  7일 이내 [1]"))

    assert parts == ["7일 이내 [1]"]
    assert completion.text == "7일 이내 [1]"
