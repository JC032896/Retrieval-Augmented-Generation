"""답변 LLM 선택(LLM_PROVIDER): 기본은 Claude, openai_compatible이면 사내 서버. 재현도 같은 LLM."""

import pytest
from pydantic import SecretStr, ValidationError

from rag_service.answer.llm import ClaudeLLM
from rag_service.answer.openai_compat import OpenAICompatibleLLM
from rag_service.answer.providers import build_llm
from rag_service.audit import replay
from rag_service.audit.request import llm_params
from rag_service.config import Settings


def test_claude_is_the_default_and_needs_a_key() -> None:
    assert Settings.model_fields["llm_provider"].default == "claude"
    assert build_llm(Settings(anthropic_api_key=None)) is None

    llm = build_llm(Settings(anthropic_api_key=SecretStr("k"), llm_model="claude-haiku-5-5"))
    assert isinstance(llm, ClaudeLLM) and llm.model == "claude-haiku-5-5"


def test_openai_compatible_uses_the_configured_server() -> None:
    settings = Settings(
        llm_provider="openai_compatible",
        llm_base_url="http://ollama:11434/v1",
        llm_model="gemma3:12b",
        llm_api_key=SecretStr("local-key"),
        anthropic_api_key=None,
    )

    llm = build_llm(settings)

    assert isinstance(llm, OpenAICompatibleLLM)
    assert (llm.base_url, llm.model) == ("http://ollama:11434/v1", "gemma3:12b")
    assert llm._client.headers["authorization"] == "Bearer local-key"


@pytest.mark.parametrize("url", [None, "", "ollama:11434/v1", "ftp://gpu/v1"])
def test_openai_compatible_requires_an_http_base_url(url: str | None) -> None:
    with pytest.raises(ValidationError, match="LLM_BASE_URL"):
        Settings.model_validate({"llm_provider": "openai_compatible", "llm_base_url": url})


def test_replay_rebuilds_a_local_model_from_recorded_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = llm_params(
        OpenAICompatibleLLM(base_url="http://gpu:8000/v1", model="local", max_tokens=1024)
    )
    settings = Settings(llm_api_key=SecretStr("k"))
    monkeypatch.setattr(replay, "get_settings", lambda: settings)

    rebuilt = replay.default_llm_factory(recorded)

    assert isinstance(rebuilt, OpenAICompatibleLLM)
    assert llm_params(rebuilt) == recorded
    assert rebuilt._client.headers["authorization"] == "Bearer k"
