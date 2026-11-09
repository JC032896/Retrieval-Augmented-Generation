import math
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import Chunk
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.access import access_filter
from rag_service.retrieval.keyword import K1, B, keyword_search
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
tokenizer = KoreanTokenizer()


@pytest.fixture
def corpus(db_session: Session) -> Corpus:
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()
    return corpus


def _term_frequencies(session: Session, corpus: Corpus, user_id: str) -> dict[int, dict[str, int]]:
    """사용자가 볼 수 있는 조각마다 {토큰: 출현 횟수} (tsvector를 그대로 펼친 값)."""
    visible = list(session.scalars(select(Chunk.id).where(access_filter(corpus.user(user_id)))))
    rows = session.execute(
        text(
            "SELECT c.id, e.lexeme, array_length(e.positions, 1) "
            "FROM chunks c, unnest(c.tokens) AS e WHERE c.id = ANY(:ids)"
        ),
        {"ids": visible},
    )
    frequencies: dict[int, dict[str, int]] = {}
    for chunk_id, lexeme, count in rows:
        frequencies.setdefault(chunk_id, {})[lexeme] = count
    return frequencies


def _reference_bm25(docs: dict[int, dict[str, int]], terms: set[str]) -> dict[int, float]:
    n = len(docs)
    lengths = {doc: sum(tf.values()) for doc, tf in docs.items()}
    average = sum(lengths.values()) / n
    scores: dict[int, float] = {}
    for term in terms:
        containing = [doc for doc, tf in docs.items() if term in tf]
        idf = math.log(1 + (n - len(containing) + 0.5) / (len(containing) + 0.5))
        for doc in containing:
            tf = docs[doc][term]
            norm = K1 * (1 - B + B * lengths[doc] / average)
            scores[doc] = scores.get(doc, 0.0) + idf * tf * (K1 + 1) / (tf + norm)
    return scores


@pytest.mark.parametrize("user_id", ["kim", "han"])
def test_sql_scores_match_reference_bm25(db_session: Session, corpus: Corpus, user_id: str) -> None:
    """SQL로 계산한 BM25가 교과서 공식(볼 수 있는 조각만으로 통계 계산)과 같은지 확인한다."""
    query = tokenizer.tokenize("재택근무 신청은 언제까지 하고 비밀번호는 몇 자 이상이야?")
    expected = _reference_bm25(_term_frequencies(db_session, corpus, user_id), set(query))

    hits = keyword_search(db_session, query, corpus.user(user_id), limit=1000)

    assert {hit.chunk_id: hit.score for hit in hits} == pytest.approx(expected)


@pytest.mark.parametrize("user_id", ["kim", "lee", "park", "choi", "jung", "han"])
def test_sql_filter_matches_can_view(db_session: Session, corpus: Corpus, user_id: str) -> None:
    every_token = list(
        db_session.scalars(text("SELECT DISTINCT lexeme FROM chunks, unnest(tokens)"))
    )
    user = corpus.user(user_id)

    hits = keyword_search(db_session, every_token, user, limit=10000)

    assert {hit.file for hit in hits} == corpus.visible_files(user)


def test_code_token_finds_its_section(db_session: Session, corpus: Corpus) -> None:
    hits = keyword_search(db_session, ["sec-pw-01"], corpus.user("kim"), limit=3)

    assert hits[0].section == "SEC-PW-01 비밀번호 규칙"


def test_no_terms_or_unknown_terms_return_nothing(db_session: Session, corpus: Corpus) -> None:
    user = corpus.user("kim")

    assert keyword_search(db_session, [], user) == []
    assert keyword_search(db_session, ["없는토큰"], user) == []


def test_limit_must_be_positive(db_session: Session) -> None:
    with pytest.raises(ValueError, match="limit"):
        keyword_search(db_session, ["가"], load_corpus(SAMPLES).user("kim"), limit=0)
