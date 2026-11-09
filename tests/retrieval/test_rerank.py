import sys
import types
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.rerank import (
    DEFAULT_RERANK_MODEL,
    MAX_LENGTH,
    CrossEncoderReranker,
    rerank,
)
from rag_service.retrieval.search import RERANK_CANDIDATES, RERANKED_RETRIEVERS, Retriever, search
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.rerank import OverlapReranker

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
tokenizer = KoreanTokenizer()


def _hit(chunk_id: int, content: str) -> SearchHit:
    return SearchHit(chunk_id, f"{chunk_id}.md", "t", "s", None, content, 0.0)


def test_rerank_orders_by_score_and_keeps_order_on_ties() -> None:
    hits = [_hit(1, "가"), _hit(2, "가나다"), _hit(3, "나"), _hit(4, "가나")]

    reranked = rerank("가나다", hits, OverlapReranker(), limit=10)

    assert [hit.chunk_id for hit in reranked] == [2, 4, 1, 3]  # 1과 3은 1점 동점: 원래 순서
    assert [hit.score for hit in reranked] == [3.0, 2.0, 1.0, 1.0]


def test_rerank_limit_and_empty_input() -> None:
    hits = [_hit(1, "가"), _hit(2, "가나")]

    assert len(rerank("가나", hits, OverlapReranker(), limit=1)) == 1
    assert rerank("가나", [], OverlapReranker(), limit=5) == []
    with pytest.raises(ValueError, match="limit"):
        rerank("가", hits, OverlapReranker(), limit=0)


class FakeCrossEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, str]], dict[str, Any]]] = []

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> list[float]:
        self.calls.append((pairs, kwargs))
        return [0.25 * index for index, _ in enumerate(pairs)]


def test_cross_encoder_reranker_scores_query_passage_pairs() -> None:
    model = FakeCrossEncoder()
    reranker = CrossEncoderReranker(loader=lambda name: model, batch_size=4)

    assert reranker.score("질문", ["가", "나"]) == [0.0, 0.25]
    assert reranker.score("질문", []) == []
    pairs, kwargs = model.calls[0]
    assert pairs == [("질문", "가"), ("질문", "나")]
    assert kwargs["batch_size"] == 4
    assert len(model.calls) == 1  # 빈 입력은 모델을 부르지 않는다


def test_default_loader_uses_cross_encoder_on_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[str, str, int]] = []

    class FakeLoadedCrossEncoder(FakeCrossEncoder):
        def __init__(self, name: str, device: str, max_length: int) -> None:
            super().__init__()
            created.append((name, device, max_length))

    class FakeModule(types.ModuleType):
        CrossEncoder = FakeLoadedCrossEncoder

    monkeypatch.setitem(sys.modules, "sentence_transformers", FakeModule("sentence_transformers"))

    CrossEncoderReranker()

    assert created == [(DEFAULT_RERANK_MODEL, "cpu", MAX_LENGTH)]


@pytest.fixture
def corpus(db_session: Session) -> Corpus:
    corpus = load_corpus(SAMPLES)
    ingest_corpus(db_session, corpus, embedder=FakeEmbedder(), tokenizer=tokenizer)
    db_session.commit()
    return corpus


def _search(
    session: Session, corpus: Corpus, retriever: Retriever, reranker: OverlapReranker | None
) -> list[SearchHit]:
    query = "출장 숙박비 한도"
    return search(
        session,
        query=query,
        query_vector=FakeEmbedder().embed([query])[0],
        viewer=corpus.user("park"),
        tokenizer=tokenizer,
        retriever=retriever,
        limit=5,
        exact=True,
        reranker=reranker,
    )


@pytest.mark.parametrize("retriever", RERANKED_RETRIEVERS)
def test_reranked_search_only_sees_visible_candidates(
    db_session: Session, corpus: Corpus, retriever: Retriever
) -> None:
    reranker = OverlapReranker()

    hits = _search(db_session, corpus, retriever, reranker)

    assert len(hits) == 5
    assert {hit.file for hit in hits} <= corpus.visible_files(corpus.user("park"))
    candidates = reranker.calls[0][1]
    assert len(candidates) == len(set(candidates))  # 합집합에 중복 후보가 없다
    if retriever == "vector_rerank":
        assert len(candidates) == RERANK_CANDIDATES
    else:
        assert len(candidates) > RERANK_CANDIDATES  # BM25가 벡터에 없던 후보를 더한다


def test_reranked_search_requires_reranker(db_session: Session, corpus: Corpus) -> None:
    with pytest.raises(ValueError, match="reranker"):
        _search(db_session, corpus, "vector_rerank", None)
