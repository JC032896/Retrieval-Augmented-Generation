"""벡터 검색: 질문 벡터와 조각 벡터의 코사인 거리로 순위를 매긴다 (권한 필터를 먼저 적용).

exact=True면 HNSW 인덱스를 쓰지 않고 전체를 비교한다(flat). 결과가 항상 같아서 평가에 쓴다.

exact=False면 Postgres가 HNSW 인덱스를 쓸 수 있다. HNSW는 근사 검색이라 기본 설정에서는 후보를
ef_search(40)개만 보고 그중 WHERE 권한 필터를 통과한 것만 돌려준다. 그래서 권한이 좁은 사용자는
결과가 limit보다 훨씬 적게 나오고 정답이 빠질 수 있다 (2026-11-09 CI에서 발견: 볼 수 있는 문서
16개 중 9개만 나옴). pgvector 0.8의 iterative scan을 켜서 필터 후 결과가 모자라면 그래프를 더
탐색하게 한다. 그래도 근사 검색이라 모든 결과를 보장하지는 않는다.
"""

from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rag_service.db.models import Chunk, Document
from rag_service.retrieval.access import Viewer, access_filter
from rag_service.retrieval.hits import HIT_COLUMNS, SearchHit, to_hit

__all__ = ["SearchHit", "vector_search"]


def vector_search(
    session: Session,
    query_vector: Sequence[float],
    viewer: Viewer,
    *,
    limit: int = 10,
    exact: bool = False,
) -> list[SearchHit]:
    if limit <= 0:
        raise ValueError("limit은 양수여야 합니다")
    if exact:
        # 현재 트랜잭션에서만 인덱스 스캔을 끈다 (순차 스캔 = 정확한 전체 비교)
        session.execute(text("SET LOCAL enable_indexscan = off"))
        session.execute(text("SET LOCAL enable_bitmapscan = off"))
    else:
        # 권한 필터로 후보가 걸러져도 limit을 채울 때까지 HNSW 탐색을 이어 간다 (순서는 정확히 유지)
        session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))

    distance = Chunk.embedding.cosine_distance(list(query_vector))
    rows = session.execute(
        select(*HIT_COLUMNS, distance)
        .join(Document, Document.id == Chunk.document_id)
        .where(access_filter(viewer))
        .order_by(distance, Chunk.id)  # 거리가 같으면 id 순으로 고정
        .limit(limit)
    ).all()
    return [to_hit(row, 1.0 - float(row[-1])) for row in rows]
