"""거절 1단계: LLM을 부르기 전에 검색 결과만 보고 거절할지 정한다 (점수 관문).

거절은 2단으로 한다.
  1. 점수 관문 (이 모듈): 검색 결과가 없거나, 1위 리랭커 점수가 min_score 미만이면 LLM 없이 거절
  2. LLM 판단 (4b): 근거 조각을 읽고 답이 없으면 REFUSAL_MESSAGE로 답하게 한다

기본값은 점수 관문을 끈다 (min_score=None, 결과가 없을 때만 거절). 골든 95문항에서 측정한 결과
(2026-11-09, vector_rerank):
- 일상어로 바꾼 질문은 1위가 정답이어도 리랭커 점수가 0에 가깝다
  ("바닷가 쪽 숙소를 싸게 쓸 수 있는 방법이 있어?" 0.00038, 점수가 두 번째로 낮은 질문)
- 주제는 같고 답은 없는 질문은 점수가 높다 ("인사평가 등급별 배분 비율" 0.898)
- 점수만으로 거절하면 F1 최고 0.77이고, 그때 답이 있는 질문 4개를 잘못 거절한다
잘못 거절하는 쪽이 LLM을 한 번 더 부르는 비용보다 나쁘므로, 점수 관문은 LLM 판단의 결과를 본 뒤
비용 절감용으로만 켠다. min_score는 리랭커 점수(0~1) 기준이라, 리랭커를 쓰는 검색기에서만
의미가 있다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rag_service.retrieval.hits import SearchHit

REFUSAL_MESSAGE = "문서에서 찾을 수 없습니다."
DEFAULT_MIN_SCORE: float | None = None  # 점수 관문 끔

RefusalReason = Literal["no_hits", "low_score"]


@dataclass(frozen=True)
class GateDecision:
    refuse: bool
    reason: RefusalReason | None = None
    top_score: float | None = None  # 1위 점수 (결과가 없으면 None). 로그와 기준값 조정에 쓴다


def score_gate(
    hits: Sequence[SearchHit], *, min_score: float | None = DEFAULT_MIN_SCORE
) -> GateDecision:
    """검색 결과(점수 내림차순)를 보고 LLM 없이 거절할지 정한다."""
    if min_score is not None and not 0.0 <= min_score <= 1.0:
        raise ValueError("min_score는 0과 1 사이의 리랭커 점수여야 합니다")
    if not hits:
        return GateDecision(refuse=True, reason="no_hits")
    top_score = max(hit.score for hit in hits)
    if min_score is not None and top_score < min_score:
        return GateDecision(refuse=True, reason="low_score", top_score=top_score)
    return GateDecision(refuse=False, top_score=top_score)
