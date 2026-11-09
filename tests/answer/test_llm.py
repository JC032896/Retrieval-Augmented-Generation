"""Claude LLM 테스트. API는 부르지 않고 요청 인자와 응답 해석만 검사한다."""

from typing import Any

import pytest
from anthropic.types.beta import BetaMessage

from rag_service.answer.llm import FALLBACK_BETA, ClaudeLLM, LLMError, parse_response


def _message(
    content: list[dict[str, Any]], stop_reason: str = "end_turn", **extra: Any
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 80},
            **extra,
        }
    )


def test_request_sends_system_prompt_effort_and_fallback() -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test-key", effort="low")

    request = llm.request(system="규칙", prompt="질문")

    assert request["model"] == "claude-sonnet-5-5"
    assert request["system"] == "규칙"
    assert request["messages"] == [{"role": "user", "content": "질문"}]
    assert request["output_config"] == {"effort": "low"}
    assert (request["betas"], request["fallbacks"]) == ([FALLBACK_BETA], "default")
    assert "thinking" not in request  # 최신 모델은 적응형 사고가 기본이다


def test_parse_keeps_only_text_blocks() -> None:
    message = _message(
        [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "  답입니다 [1]. "},
            {"type": "text", "text": "추가 [2]"},
        ]
    )

    completion = parse_response(message)

    assert completion.text == "답입니다 [1]. 추가 [2]"
    assert (completion.model, completion.input_tokens, completion.output_tokens) == (
        "claude-sonnet-5-5",
        1200,
        80,
    )


def test_safety_refusal_raises() -> None:
    message = _message(
        [],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": None},
    )

    with pytest.raises(LLMError, match="cyber"):
        parse_response(message)


def test_truncated_answer_raises() -> None:
    with pytest.raises(LLMError, match="max_tokens"):
        parse_response(_message([{"type": "text", "text": "잘린 답"}], stop_reason="max_tokens"))
