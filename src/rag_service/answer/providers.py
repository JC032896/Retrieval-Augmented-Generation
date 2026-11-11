"""설정에 따라 답변 LLM을 만든다 (LLM_PROVIDER).

- claude (기본): Anthropic Claude API. ANTHROPIC_API_KEY가 없으면 None (질문 API가 503)
- openai_compatible: 사내 GPU 서버 등 OpenAI 호환 API (vLLM, Ollama). LLM_BASE_URL, LLM_MODEL 필요
"""

from rag_service.answer.llm import ClaudeLLM
from rag_service.answer.openai_compat import OpenAICompatibleLLM
from rag_service.config import Settings


def build_llm(settings: Settings) -> ClaudeLLM | OpenAICompatibleLLM | None:
    if settings.llm_provider == "openai_compatible":
        key = settings.llm_api_key
        return OpenAICompatibleLLM(
            base_url=settings.llm_base_url or "",  # Settings 검증이 비어 있지 않음을 보장한다
            model=settings.llm_model,
            api_key=key.get_secret_value() if key else None,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.anthropic_api_key is None:
        return None
    return ClaudeLLM(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        effort=settings.llm_effort,
        timeout=settings.llm_timeout_seconds,
    )
