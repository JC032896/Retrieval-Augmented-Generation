from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.search import RETRIEVERS, Retriever, hybrid_search, search
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
tokenizer = KoreanTokenizer()


def _hit(chunk_id: int, score: float = 0.0) -> SearchHit:
    return SearchHit(chunk_id, f"{chunk_id}.md", "t", "s", None, "c", score)


def test_hybrid_fuses_ranks_and_replaces_scores() -> None:
    fused = hybrid_search([_hit(1, 0.9), _hit(2, 0.8)], [_hit(2, 7.0), _hit(3, 5.0)], limit=10)

    assert [hit.chunk_id for hit in fused] == [2, 1, 3]  # 2는 두 목록에 모두 있다
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)


def test_hybrid_respects_limit() -> None:
    assert len(hybrid_search([_hit(1), _hit(2)], [_hit(3)], limit=2)) == 2
    with pytest.raises(ValueError, match="limit"):
        hybrid_search([], [], limit=0)


@pytest.fixture
def corpus(db_session: Session) -> Corpus:
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()
    return corpus


@pytest.mark.parametrize("retriever", RETRIEVERS)
def test_every_retriever_only_returns_visible_documents(
    db_session: Session, corpus: Corpus, retriever: Retriever
) -> None:
    user = corpus.user("park")  # 인사팀 사원: 공용 문서만 볼 수 있다
    query = "인사평가 등급과 연봉 인상률, 희망퇴직 위로금"

    hits = search(
        db_session,
        query=query,
        query_vector=FakeEmbedder().embed([query])[0],
        viewer=user,
        tokenizer=tokenizer,
        retriever=retriever,
        limit=50,
        exact=True,
    )

    assert hits
    assert {hit.file for hit in hits} <= corpus.visible_files(user)


def test_unknown_retriever_is_rejected(db_session: Session, corpus: Corpus) -> None:
    with pytest.raises(ValueError, match="알 수 없는"):
        search(
            db_session,
            query="가",
            query_vector=FakeEmbedder().embed(["가"])[0],
            viewer=corpus.user("kim"),
            tokenizer=tokenizer,
            retriever=cast(Retriever, "magic"),
        )
