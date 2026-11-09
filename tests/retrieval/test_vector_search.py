from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import Chunk
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.vector import vector_search
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.dense_embedding import DenseFakeEmbedder
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def corpus(db_session: Session) -> Corpus:
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=KoreanTokenizer())
    db_session.commit()
    return corpus


def _any_vector() -> list[float]:
    return FakeEmbedder().embed(["아무 질문"])[0]


@pytest.mark.parametrize("user_id", ["kim", "lee", "park", "choi", "jung", "han"])
def test_sql_filter_matches_can_view(db_session: Session, corpus: Corpus, user_id: str) -> None:
    """SQL 권한 필터가 corpus.can_view와 정확히 같은 문서만 보여 주는지 사용자마다 확인한다.

    근사 검색(HNSW)은 모든 결과를 보장하지 않으므로 정확한 전체 비교로 검사한다.
    """
    user = corpus.user(user_id)

    hits = vector_search(db_session, _any_vector(), user, limit=1000, exact=True)

    assert {hit.file for hit in hits} == corpus.visible_files(user)


def test_identical_vector_ranks_first_with_full_score(db_session: Session, corpus: Corpus) -> None:
    chunk = db_session.scalars(
        select(Chunk).where(Chunk.section == "SEC-PW-01 비밀번호 규칙")
    ).one()

    hits = vector_search(db_session, list(chunk.embedding), corpus.user("kim"), limit=3)

    assert hits[0].chunk_id == chunk.id
    assert hits[0].section == "SEC-PW-01 비밀번호 규칙"
    assert hits[0].score == pytest.approx(1.0)
    assert len(hits) == 3


@pytest.mark.parametrize("user_id", ["park", "han"])
def test_index_scan_still_fills_limit_after_permission_filter(
    db_session: Session, user_id: str
) -> None:
    """HNSW 인덱스를 쓰는 실행 계획에서도 권한 필터 뒤 결과가 limit만큼 채워지는지 확인한다.

    iterative scan이 없으면 HNSW는 후보 40개(ef_search)만 보고 필터를 적용해서, 권한이 좁은
    사용자는 결과가 limit보다 적게 나왔다 (2026-11-09 CI 실패의 원인).

    one-hot 가짜 벡터로는 HNSW 그래프가 제대로 연결되지 않아 실행마다 결과가 흔들렸다
    (2026-11-09 CI, 로컬 40번 중 4~7번 실패). 실제 임베딩처럼 퍼진 벡터로 수집한다.
    """
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=DenseFakeEmbedder(), tokenizer=KoreanTokenizer())
    db_session.commit()
    # 테스트 데이터가 작아서 Postgres가 순차 스캔을 고르므로, 인덱스 순서를 쓰는 계획을 강제한다
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    db_session.execute(text("SET LOCAL enable_sort = off"))

    query = DenseFakeEmbedder().embed(["아무 질문"])[0]
    hits = vector_search(db_session, query, corpus.user(user_id), limit=50)

    assert len(hits) == 50


def test_pdf_hits_carry_page(db_session: Session, corpus: Corpus) -> None:
    hits = vector_search(db_session, _any_vector(), corpus.user("kim"), limit=1000, exact=True)

    pages = {hit.section: hit.page for hit in hits if hit.file.endswith(".pdf")}
    assert pages == {"사전 승인": 1, "국내 출장": 1, "해외 출장": 2, "정산": 2}


def test_limit_must_be_positive(db_session: Session) -> None:
    with pytest.raises(ValueError, match="limit"):
        vector_search(db_session, _any_vector(), load_corpus(SAMPLES).user("kim"), limit=0)
