"""답변 생성용 LLM 인터페이스와 Claude 구현.

LLM은 Protocol 뒤에 둔다. 기본은 Claude API이고, 같은 complete()만 구현하면 로컬 모델(Ollama 등)로
바꿀 수 있다. 테스트와 CI는 API를 부르지 않는 가짜 LLM을 쓴다.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from anthropic.types.beta import BetaMessage

Effort = Literal["low", "medium", "high"]

# 정책상 거부되면 서버가 정해 둔 다른 모델로 한 번 더 시도한다. 지원하지 않는 모델에서는 무시된다
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 사고(thinking) 토큰도 max_tokens에 들어간다. 실제로 쓴 만큼만 과금되므로 넉넉히 둔다
DEFAULT_MAX_TOKENS = 16000

# 공개 표준 요금 (100만 토큰당 입력, 출력 달러, 2026-11 기준). 비용 추정용
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.1, 0.5),
}


@dataclass(frozen=True)
class Completion:
    text: str
    model: str  # 실제로 답한 모델 (대체 모델이 답했으면 그 모델)
    input_tokens: int
    output_tokens: int


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """달러 비용 추정. 요금표에 없는 모델은 None."""
    if model not in MODEL_PRICES:
        return None
    input_price, output_price = MODEL_PRICES[model]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


class LLMError(RuntimeError):
    """LLM이 정상적인 답을 끝까지 내지 못했다 (안전 정책 거부, 길이 초과 등)."""


class LLM(Protocol):
    def complete(self, *, system: str, prompt: str) -> Completion: ...


class ClaudeLLM:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        effort: Effort = "medium",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        # api_key가 None이면 SDK가 환경 변수 ANTHROPIC_API_KEY를 읽는다
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def complete(self, *, system: str, prompt: str) -> Completion:
        response = self._client.beta.messages.create(**self.request(system=system, prompt=prompt))
        return parse_response(response)

    def request(self, *, system: str, prompt: str) -> dict[str, Any]:
        """API 요청 인자. 네트워크 없이 검사할 수 있게 따로 만든다."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort},
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }


def parse_response(response: BetaMessage) -> Completion:
    """응답에서 답변 텍스트만 꺼낸다. 사고 블록은 버린다."""
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise LLMError(f"LLM이 안전 정책으로 답하지 않았습니다 (category={category})")
    if response.stop_reason == "max_tokens":
        raise LLMError("답변이 max_tokens에서 잘렸습니다")
    text = "".join(block.text for block in response.content if block.type == "text")
    return Completion(
        text=text.strip(),
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
