"""LLM 비용 추정 테스트."""

import pytest

from rag_service.answer.llm import MODEL_PRICES, estimate_cost


def test_cost_uses_per_million_prices() -> None:
    # 실측 예: Sonnet 5.5 입력 1426, 출력 93 토큰 → 약 $0.0038
    assert estimate_cost("claude-sonnet-5-5", 1426, 93) == pytest.approx(0.003782)


def test_unknown_model_has_no_cost() -> None:
    assert estimate_cost("local-model", 1000, 1000) is None


def test_compared_models_all_have_prices() -> None:
    assert {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"} <= set(MODEL_PRICES)
