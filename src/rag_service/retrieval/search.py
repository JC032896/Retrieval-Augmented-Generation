"""검색 진입점. 서비스와 평가 스크립트(eval/run_eval.py)가 같은 함수를 쓴다.

1단계 검색기 (RETRIEVERS)
- vector:  의미 검색 (BGE-M3 임베딩, 코사인 유사도)
- keyword: 키워드 검색 (Kiwi 토큰 BM25)
- hybrid:  두 검색의 상위 HYBRID_CANDIDATES개씩을 RRF로 합친다. 점수 단위가 달라서 순위만 쓴다.

리랭커를 붙인 검색기 (RERANKED_RETRIEVERS, reranker 인자가 필요하다)
- vector_rerank: 벡터 상위 RERANK_CANDIDATES개를 리랭커로 다시 정렬한다.
- hybrid_rerank: 벡터 상위와 BM25 상위의 합집합을 리랭커로 다시 정렬한다. 리랭커가 순서를 새로
  정하므로 RRF로 합칠 필요가 없고, BM25는 벡터가 놓친 후보를 더하는 역할만 한다.

어느 방식이든 권한 필터는 각 검색 SQL의 WHERE 절에서 먼저 적용된다.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import Literal

from sqlalchemy.orm import Session

from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.access import Viewer
from rag_service.retrieval.fusion import reciprocal_rank_fusion
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.keyword import keyword_search
from rag_service.retrieval.rerank import Reranker, rerank
from rag_service.retrieval.vector import vector_search

Retriever = Literal["vector", "keyword", "hybrid", "vector_rerank", "hybrid_rerank"]
RETRIEVERS: tuple[Retriever, ...] = ("vector", "keyword", "hybrid")
RERANKED_RETRIEVERS: tuple[Retriever, ...] = ("vector_rerank", "hybrid_rerank")
HYBRID_CANDIDATES = 20  # 각 검색기에서 RRF로 넘길 후보 수
RERANK_CANDIDATES = 20  # 각 검색기에서 리랭커로 넘길 후보 수
RRF_K = 60


def search(
    session: Session,
    *,
    query: str,
    query_vector: Sequence[float],
    viewer: Viewer,
    tokenizer: KoreanTokenizer,
    retriever: Retriever = "hybrid",
    limit: int = 10,
    exact: bool = False,
    reranker: Reranker | None = None,
) -> list[SearchHit]:
    if retriever == "vector":
        return vector_search(session, query_vector, viewer, limit=limit, exact=exact)
    if retriever == "keyword":
        return keyword_search(session, tokenizer.tokenize(query), viewer, limit=limit)
    if retriever == "hybrid":
        return hybrid_search(
            vector_search(session, query_vector, viewer, limit=HYBRID_CANDIDATES, exact=exact),
            keyword_search(session, tokenizer.tokenize(query), viewer, limit=HYBRID_CANDIDATES),
            limit=limit,
        )
    if retriever in RERANKED_RETRIEVERS:
        if reranker is None:
            raise ValueError(f"{retriever} 검색기에는 reranker가 필요합니다")
        candidates = vector_search(
            session, query_vector, viewer, limit=RERANK_CANDIDATES, exact=exact
        )
        if retriever == "hybrid_rerank":
            keyword_hits = keyword_search(
                session, tokenizer.tokenize(query), viewer, limit=RERANK_CANDIDATES
            )
            seen = {hit.chunk_id for hit in candidates}
            candidates += [hit for hit in keyword_hits if hit.chunk_id not in seen]
        return rerank(query, candidates, reranker, limit=limit)
    raise ValueError(f"알 수 없는 검색기: {retriever}")


def hybrid_search(
    vector_hits: Sequence[SearchHit], keyword_hits: Sequence[SearchHit], *, limit: int
) -> list[SearchHit]:
    """두 결과 목록을 RRF로 합친다. 점수는 RRF 점수로 바꾼다."""
    if limit <= 0:
        raise ValueError("limit은 양수여야 합니다")
    by_id = {str(hit.chunk_id): hit for hit in [*keyword_hits, *vector_hits]}
    fused = reciprocal_rank_fusion(
        [[str(hit.chunk_id) for hit in vector_hits], [str(hit.chunk_id) for hit in keyword_hits]],
        k=RRF_K,
    )
    return [replace(by_id[chunk_id], score=score) for chunk_id, score in fused[:limit]]
