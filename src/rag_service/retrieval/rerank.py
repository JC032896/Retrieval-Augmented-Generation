"""리랭커: 1단계 검색이 고른 후보를 질문과 함께 다시 읽고 순위를 다시 매긴다.

크로스 인코더(BAAI/bge-reranker-v2-m3)는 질문과 조각을 한 입력으로 넣어 관련도를 계산한다.
벡터 검색처럼 따로따로 임베딩해 비교하는 것보다 정확하지만, 후보마다 모델을 돌려야 해서 느리다.
그래서 1단계 검색으로 후보를 수십 개로 줄인 뒤에만 쓴다. 점수는 0~1 (sigmoid)이고, 4단계에서
"근거가 부족하면 답변을 거절"하는 기준값으로도 쓴다.

권한 필터는 1단계 검색의 WHERE 절에서 이미 적용되므로, 리랭커는 볼 수 있는 후보만 받는다.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Protocol

from rag_service.retrieval.hits import SearchHit

DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 512  # 질문 + 조각의 최대 토큰 수 (샘플 조각은 모두 이보다 짧다)


class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


def _load_cross_encoder(model_name: str) -> Any:
    # torch를 불러오는 데 몇 초가 걸리므로 실제로 쓸 때만 import한다
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device="cpu", max_length=MAX_LENGTH)


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str = DEFAULT_RERANK_MODEL,
        *,
        loader: Callable[[str], Any] = _load_cross_encoder,
        batch_size: int = 16,
    ) -> None:
        self._model = loader(model_name)
        self._batch_size = batch_size

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        values = self._model.predict(
            [(query, passage) for passage in passages],
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
        return [float(value) for value in values]


def rerank(
    query: str, hits: Sequence[SearchHit], reranker: Reranker, *, limit: int
) -> list[SearchHit]:
    """리랭커 점수 순으로 다시 정렬한다. 점수가 같으면 1단계 순서를 유지한다."""
    if limit <= 0:
        raise ValueError("limit은 양수여야 합니다")
    scores = reranker.score(query, [hit.content for hit in hits])
    order = sorted(range(len(hits)), key=lambda index: (-scores[index], index))
    return [replace(hits[index], score=scores[index]) for index in order[:limit]]
