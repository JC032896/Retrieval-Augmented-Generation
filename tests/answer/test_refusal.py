"""거절 1단계(점수 관문) 테스트."""

import pytest

from rag_service.answer.refusal import DEFAULT_MIN_SCORE, REFUSAL_MESSAGE, score_gate
from rag_service.retrieval.hits import SearchHit


def _hits(*scores: float) -> list[SearchHit]:
    return [
        SearchHit(index, f"{index}.md", "t", "s", None, "c", score)
        for index, score in enumerate(scores)
    ]


def test_no_hits_is_always_refused() -> None:
    decision = score_gate([])

    assert (decision.refuse, decision.reason, decision.top_score) == (True, "no_hits", None)


def test_default_gate_does_not_refuse_low_scores() -> None:
    # 일상어 질문은 정답이어도 리랭커 점수가 0에 가깝다. 기본값은 이런 질문을 LLM에 넘긴다
    decision = score_gate(_hits(0.0003, 0.0001))

    assert DEFAULT_MIN_SCORE is None
    assert (decision.refuse, decision.reason) == (False, None)
    assert decision.top_score == 0.0003


def test_min_score_refuses_only_below_threshold() -> None:
    below = score_gate(_hits(0.009, 0.001), min_score=0.01)
    at = score_gate(_hits(0.01), min_score=0.01)

    assert (below.refuse, below.reason, below.top_score) == (True, "low_score", 0.009)
    assert (at.refuse, at.reason) == (False, None)


def test_top_score_is_the_best_hit_regardless_of_order() -> None:
    assert score_gate(_hits(0.2, 0.9, 0.5), min_score=0.5).top_score == 0.9


@pytest.mark.parametrize("min_score", [-0.1, 1.5])
def test_min_score_must_be_a_reranker_score(min_score: float) -> None:
    with pytest.raises(ValueError, match="min_score"):
        score_gate(_hits(0.5), min_score=min_score)


def test_refusal_message_matches_readme() -> None:
    assert REFUSAL_MESSAGE.startswith("문서에서 찾을 수 없습니다")
