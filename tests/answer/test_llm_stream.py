"""ClaudeLLM.stream이 SDK 스트림을 열고, 텍스트를 내보내고, 오류를 LLMError로 바꾸는지 검사한다."""

from collections.abc import Generator, Iterator
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from rag_service.answer.llm import ClaudeLLM, Completion, LLMError


class _FakeStream:
    def __init__(self, texts: list[str], message: BetaMessage) -> None:
        self.text_stream: Iterator[str] = iter(texts)
        self._message = message

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get_final_message(self) -> BetaMessage:
        return self._message


def _message(text: str, stop_reason: str = "end_turn") -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }
    )


def _run(stream: Generator[str, None, Completion]) -> tuple[list[str], Completion]:
    deltas: list[str] = []
    while True:
        try:
            deltas.append(next(stream))
        except StopIteration as stop:
            return deltas, stop.value


def test_stream_sends_request_yields_text_and_returns_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key")
    sent: list[dict[str, Any]] = []

    def stream(**kwargs: Any) -> _FakeStream:
        sent.append(kwargs)
        return _FakeStream(["답 ", "[1]"], _message("답 [1]"))

    monkeypatch.setattr(llm._client.beta.messages, "stream", stream)

    deltas, completion = _run(llm.stream(system="규칙", prompt="질문"))

    assert sent == [llm.request(system="규칙", prompt="질문")]
    assert deltas == ["답 ", "[1]"]
    assert (completion.text, completion.input_tokens, completion.output_tokens) == ("답 [1]", 10, 3)


def test_stream_refusal_raises_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key")

    def stream(**kwargs: Any) -> _FakeStream:
        return _FakeStream(["부분"], _message("부분", stop_reason="refusal"))

    monkeypatch.setattr(llm._client.beta.messages, "stream", stream)

    with pytest.raises(LLMError, match="안전 정책"):
        _run(llm.stream(system="규칙", prompt="질문"))


def test_stream_turns_api_errors_into_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key")
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def stream(**kwargs: Any) -> _FakeStream:
        raise anthropic.APITimeoutError(request=request)

    monkeypatch.setattr(llm._client.beta.messages, "stream", stream)

    with pytest.raises(LLMError, match="APITimeoutError"):
        _run(llm.stream(system="규칙", prompt="질문"))


def test_timeout_is_set_on_the_client() -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key", timeout=30.0)

    assert llm._client.timeout == 30.0
