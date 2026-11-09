from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import Chunk
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.vector import vector_search
from tests.fixtures.db import db_engine, db_session
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
    """SQL 권한 필터가 corpus.can_view와 정확히 같은 문서만 보여 주는지 사용자마다 확인한다."""
    user = corpus.user(user_id)

    hits = vector_search(db_session, _any_vector(), user, limit=1000)

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


def test_exact_search_gives_same_order(db_session: Session, corpus: Corpus) -> None:
    user = corpus.user("han")
    vector = _any_vector()

    approximate = vector_search(db_session, vector, user, limit=10)
    exact = vector_search(db_session, vector, user, limit=10, exact=True)

    assert [hit.chunk_id for hit in exact] == [hit.chunk_id for hit in approximate]


def test_pdf_hits_carry_page(db_session: Session, corpus: Corpus) -> None:
    hits = vector_search(db_session, _any_vector(), corpus.user("kim"), limit=1000)

    pages = {hit.section: hit.page for hit in hits if hit.file.endswith(".pdf")}
    assert pages == {"사전 승인": 1, "국내 출장": 1, "해외 출장": 2, "정산": 2}


def test_limit_must_be_positive(db_session: Session) -> None:
    with pytest.raises(ValueError, match="limit"):
        vector_search(db_session, _any_vector(), load_corpus(SAMPLES).user("kim"), limit=0)
