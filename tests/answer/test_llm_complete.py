"""ClaudeLLM.complete가 만든 요청을 SDK에 넘기고 응답을 해석하는지 검사한다 (네트워크 없음)."""

from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from rag_service.answer.llm import ClaudeLLM


def test_complete_sends_request_and_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key")
    sent: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> BetaMessage:
        sent.append(kwargs)
        return BetaMessage.model_validate(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": "답 [1]"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        )

    monkeypatch.setattr(llm._client.beta.messages, "create", create)

    completion = llm.complete(system="규칙", prompt="질문")

    assert sent == [llm.request(system="규칙", prompt="질문")]
    assert (completion.text, completion.input_tokens, completion.output_tokens) == ("답 [1]", 10, 2)
