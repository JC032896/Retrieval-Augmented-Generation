"""eval/run_eval.py의 검색기 선택, 비교표, 줄바꿈 정규화 테스트."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from eval.run_eval import (
    DEFAULT_RETRIEVER,
    GOLDEN,
    SAMPLES,
    CachedEmbedder,
    EmbeddingCache,
    evaluate,
    file_sha256,
    format_comparison,
    load_golden,
)
from rag_service.corpus import load_corpus
from rag_service.retrieval.search import RETRIEVERS, Retriever
from tests.fixtures.db import db_engine
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine"]


def test_golden_hash_ignores_line_endings(tmp_path: Path) -> None:
    lf, crlf = tmp_path / "lf.jsonl", tmp_path / "crlf.jsonl"
    lf.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    crlf.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')

    assert file_sha256(lf) == file_sha256(crlf)


def test_default_retriever_is_the_gated_one() -> None:
    assert DEFAULT_RETRIEVER == "vector"


@pytest.mark.parametrize("retriever", RETRIEVERS)
def test_every_retriever_is_evaluated_without_leaks(
    db_engine: Engine, tmp_path: Path, retriever: Retriever
) -> None:
    embedder = CachedEmbedder(EmbeddingCache(tmp_path / "c.json", "m"), FakeEmbedder())

    result = evaluate(db_engine, load_corpus(SAMPLES), load_golden(GOLDEN), embedder, retriever)

    assert result["retriever"] == retriever
    assert result["acl_leaks"] == 0
    assert result["n_questions"] == 75


def test_comparison_table_has_one_row_per_retriever() -> None:
    row = {
        "recall_at_5": 1.0,
        "mrr": 0.9,
        "hit_at_1": 0.8,
        "acl_leaks": 0,
        "by_type": {"paraphrase": {"hit_at_1": 0.5}, "code": {"hit_at_1": 0.7}},
    }

    table = format_comparison([{**row, "retriever": name} for name in RETRIEVERS])

    lines = table.splitlines()
    assert len(lines) == 2 + len(RETRIEVERS)
    assert lines[2] == "| vector | 1.000 | 0.900 | 0.800 | 0.500 | 0.700 | 0 |"
