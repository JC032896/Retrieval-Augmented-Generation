"""키워드 검색: Kiwi 형태소 토큰의 BM25 점수로 순위를 매긴다 (권한 필터를 먼저 적용).

pgvector 이미지에는 BM25 확장이 없어서, 수집할 때 저장한 tsvector(토큰별 위치 목록)로
Okapi BM25를 SQL에서 직접 계산한다.

  score(문서, 질문) = Σ IDF(t) · tf·(k1+1) / (tf + k1·(1 − b + b·문서길이/평균길이))
  IDF(t) = ln(1 + (N − df + 0.5) / (df + 0.5))

- tf: 조각 안에서 토큰이 나온 횟수 (tsvector의 위치 개수)
- N, df, 평균 길이는 **사용자가 볼 수 있는 조각만으로** 계산한다. 볼 수 없는 문서의 단어 통계가
  순위에 영향을 주면, 순위 변화로 숨은 문서의 내용을 짐작할 수 있기 때문이다.
  current_only=True면 폐지 문서도 통계에서 뺀다 (검색 대상에 없는 문서처럼 다룬다).
- 질문마다 볼 수 있는 조각 전체를 훑으므로 조각 수에 비례해 느려진다. 샘플 규모(100개 안팎)에는
  충분하고, 큰 규모에서는 통계를 미리 집계하거나 전용 확장(pg_search 등)으로 바꿔야 한다.
"""

from collections.abc import Sequence

from sqlalchemy import Float, SmallInteger, Text, cast, column, func, select, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from rag_service.db.models import Chunk, Document
from rag_service.retrieval.access import Viewer, scope_filter
from rag_service.retrieval.hits import HIT_COLUMNS, SearchHit, to_hit

K1 = 1.2
B = 0.75


def keyword_search(
    session: Session,
    query_tokens: Sequence[str],
    viewer: Viewer,
    *,
    limit: int = 10,
    current_only: bool = False,
) -> list[SearchHit]:
    if limit <= 0:
        raise ValueError("limit은 양수여야 합니다")
    terms = sorted(set(query_tokens))
    if not terms:
        return []

    visible = (
        select(Chunk.id, Chunk.tokens)
        .where(scope_filter(viewer, current_only=current_only))
        .cte("visible")
    )
    # unnest(tsvector)는 (lexeme, positions, weights) 행을 돌려준다
    entry = (
        func.unnest(visible.c.tokens)
        .table_valued(
            column("lexeme", Text),
            column("positions", ARRAY(SmallInteger)),
            column("weights", ARRAY(Text)),
        )
        .lateral("entry")
    )
    postings = (
        select(
            visible.c.id.label("chunk_id"),
            entry.c.lexeme,
            cast(func.coalesce(func.array_length(entry.c.positions, 1), 1), Float).label("tf"),
        )
        .select_from(visible)
        .join(entry, true())
        .cte("postings")
    )
    lengths = (
        select(postings.c.chunk_id, func.sum(postings.c.tf).label("length"))
        .group_by(postings.c.chunk_id)
        .cte("lengths")
    )
    stats = select(
        cast(func.count(), Float).label("n"), func.avg(lengths.c.length).label("avgdl")
    ).cte("stats")
    matched = select(postings).where(postings.c.lexeme.in_(terms)).cte("matched")
    df = (
        select(matched.c.lexeme, cast(func.count(), Float).label("df"))
        .group_by(matched.c.lexeme)
        .cte("df")
    )

    idf = func.ln(1 + (stats.c.n - df.c.df + 0.5) / (df.c.df + 0.5))
    norm = K1 * (1 - B + B * lengths.c.length / stats.c.avgdl)
    scored = (
        select(
            matched.c.chunk_id,
            func.sum(idf * matched.c.tf * (K1 + 1) / (matched.c.tf + norm)).label("score"),
        )
        .select_from(
            matched.join(df, df.c.lexeme == matched.c.lexeme)
            .join(lengths, lengths.c.chunk_id == matched.c.chunk_id)
            .join(stats, true())
        )
        .group_by(matched.c.chunk_id)
        .cte("scored")
    )

    rows = session.execute(
        select(*HIT_COLUMNS, scored.c.score)
        .select_from(scored)
        .join(Chunk, Chunk.id == scored.c.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .order_by(scored.c.score.desc(), Chunk.id)
        .limit(limit)
    ).all()
    return [to_hit(row, float(row[-1])) for row in rows]
