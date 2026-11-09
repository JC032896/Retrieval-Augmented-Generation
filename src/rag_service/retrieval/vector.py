"""벡터 검색: 질문 벡터와 조각 벡터의 코사인 거리로 순위를 매긴다 (권한 필터를 먼저 적용).

exact=True면 HNSW 인덱스를 쓰지 않고 전체를 비교한다(flat). 결과가 항상 같아서 평가에 쓴다.
HNSW는 근사 검색이라 WHERE 필터와 함께 쓰면 결과가 limit보다 적게 나올 수 있다
(pgvector 0.8의 hnsw.iterative_scan으로 완화 가능). 운영 경로는 3단계 후반에 정한다.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rag_service.db.models import Chunk, Document
from rag_service.retrieval.access import Viewer, access_filter


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    file: str  # documents.source_path (acl.yaml의 file)
    title: str
    section: str | None
    page: int | None
    content: str
    score: float  # 코사인 유사도 (1 - 코사인 거리)


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

    distance = Chunk.embedding.cosine_distance(list(query_vector))
    rows = session.execute(
        select(
            Chunk.id,
            Document.source_path,
            Document.title,
            Chunk.section,
            Chunk.page,
            Chunk.content,
            distance,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(access_filter(viewer))
        .order_by(distance, Chunk.id)  # 거리가 같으면 id 순으로 고정
        .limit(limit)
    ).all()
    return [
        SearchHit(
            chunk_id=row[0],
            file=row[1],
            title=row[2],
            section=row[3],
            page=row[4],
            content=row[5],
            score=1.0 - float(row[6]),
        )
        for row in rows
    ]
