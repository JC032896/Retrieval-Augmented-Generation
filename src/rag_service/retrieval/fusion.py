"""여러 검색기의 순위 목록을 하나로 합치는 함수."""

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = 60
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion(RRF)으로 순위 목록을 합친다.

    각 목록에서 순위 r(1부터)에 있는 문서는 1 / (k + r)점을 받고, 점수를 모두 더한다.
    BM25 점수와 벡터 유사도처럼 단위가 다른 점수를 직접 비교하지 않고 순위만 쓴다.
    점수가 같으면 문서 ID 오름차순으로 정렬해서 결과가 항상 같게 나오도록 한다.
    """
    if k <= 0:
        raise ValueError("k는 양수여야 합니다")

    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen:  # 같은 목록 안의 중복은 처음 순위만 인정
                continue
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
