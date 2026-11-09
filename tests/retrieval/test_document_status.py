"""폐지(superseded) 문서를 검색에서 빼는지 테스트."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import Document
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.keyword import keyword_search
from rag_service.retrieval.search import RERANKED_RETRIEVERS, RETRIEVERS, Retriever, search
from rag_service.retrieval.vector import vector_search
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.rerank import OverlapReranker

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
tokenizer = KoreanTokenizer()
SUPERSEDED = {
    "16_travel_expense_rules_2025.md",
    "17_remote_work_pilot_2023.md",
    "20_sales_proposal_guide_2024.md",
}


@pytest.fixture
def corpus(db_session: Session) -> Corpus:
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()
    return corpus


def test_ingest_stores_document_status(db_session: Session, corpus: Corpus) -> None:
    rows = db_session.execute(select(Document.source_path, Document.status)).all()

    assert {path for path, status in rows if status == "superseded"} == SUPERSEDED
    assert len(rows) == len(corpus.documents)


def _search(
    session: Session, corpus: Corpus, retriever: Retriever, *, include_superseded: bool
) -> list[SearchHit]:
    query = "출장 숙박비 한도와 재택근무 신청, 제안서 작성"
    return search(
        session,
        query=query,
        query_vector=FakeEmbedder().embed([query])[0],
        viewer=corpus.user("han"),  # 경영진 임원: 폐지 문서 16, 17은 볼 수 있다
        tokenizer=tokenizer,
        retriever=retriever,
        limit=1000,
        exact=True,
        reranker=OverlapReranker(),
        include_superseded=include_superseded,
    )


@pytest.mark.parametrize("retriever", RETRIEVERS + RERANKED_RETRIEVERS)
def test_search_excludes_superseded_by_default(
    db_session: Session, corpus: Corpus, retriever: Retriever
) -> None:
    hits = _search(db_session, corpus, retriever, include_superseded=False)

    assert hits
    assert {hit.file for hit in hits}.isdisjoint(SUPERSEDED)


def test_search_can_include_superseded(db_session: Session, corpus: Corpus) -> None:
    hits = _search(db_session, corpus, "vector", include_superseded=True)

    visible = corpus.visible_files(corpus.user("han"))
    assert {hit.file for hit in hits} == visible
    assert SUPERSEDED & visible  # 이 사용자에게 보이는 폐지 문서가 결과에 다시 들어온다


def test_superseded_is_still_bound_by_permissions(db_session: Session, corpus: Corpus) -> None:
    user = corpus.user("kim")  # 개발팀: 영업팀 문서(20)는 폐지 여부와 관계없이 볼 수 없다
    vector = FakeEmbedder().embed(["가"])[0]

    hits = vector_search(db_session, vector, user, limit=1000, exact=True)

    assert "20_sales_proposal_guide_2024.md" not in {hit.file for hit in hits}
    assert "16_travel_expense_rules_2025.md" in {hit.file for hit in hits}


def test_current_only_vector_search_covers_all_current_documents(
    db_session: Session, corpus: Corpus
) -> None:
    user = corpus.user("han")
    vector = FakeEmbedder().embed(["가"])[0]

    hits = vector_search(db_session, vector, user, limit=1000, exact=True, current_only=True)

    assert {hit.file for hit in hits} == corpus.visible_files(user) - SUPERSEDED


def test_keyword_statistics_ignore_superseded(db_session: Session, corpus: Corpus) -> None:
    user = corpus.user("han")
    # "시범"은 17(재택근무 시범 운영, 폐지)에 많이 나온다. 폐지 문서를 빼면 N과 df가 달라진다
    tokens = tokenizer.tokenize("시범 운영 재택근무")

    all_hits = keyword_search(db_session, tokens, user, limit=1000)
    current_hits = keyword_search(db_session, tokens, user, limit=1000, current_only=True)

    assert current_hits
    assert {hit.file for hit in current_hits}.isdisjoint(SUPERSEDED)
    all_scores = {hit.chunk_id: hit.score for hit in all_hits}
    # 같은 조각이라도 점수가 현행 문서만의 통계로 다시 계산된다
    assert all(hit.score != pytest.approx(all_scores[hit.chunk_id]) for hit in current_hits)
