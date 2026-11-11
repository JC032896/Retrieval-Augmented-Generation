"""검색기들이 함께 쓰는 결과 형식."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rag_service.db.models import Chunk, Document

# 검색 결과로 가져오는 컬럼. 쿼리마다 이 뒤에 점수 컬럼 하나를 붙인다.
HIT_COLUMNS = (
    Chunk.id,
    Document.source_path,
    Document.title,
    Chunk.section,
    Chunk.page,
    Chunk.content,
    Chunk.chunk_key,
)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    file: str  # documents.source_path (acl.yaml의 file)
    title: str
    section: str | None
    page: int | None
    content: str
    score: float  # 검색기마다 의미가 다르다 (벡터: 코사인 유사도, 키워드: BM25, 하이브리드: RRF)
    chunk_key: str | None = None  # 감사 기록용 "어느 조항인가" (0005 이전에 수집한 조각은 없음)


def to_hit(row: Sequence[Any], score: float) -> SearchHit:
    """HIT_COLUMNS 순서의 행을 SearchHit으로 바꾼다."""
    return SearchHit(
        chunk_id=row[0],
        file=row[1],
        title=row[2],
        section=row[3],
        page=row[4],
        content=row[5],
        score=score,
        chunk_key=row[6],
    )
