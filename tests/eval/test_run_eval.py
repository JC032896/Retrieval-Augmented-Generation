"""eval/run_eval.py(채점 코드) 테스트. 채점이 틀리면 모든 비교표가 틀리므로 따로 검증한다."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from eval.run_eval import (
    GOLDEN,
    SAMPLES,
    CachedEmbedder,
    CacheMissError,
    EmbeddingCache,
    Evidence,
    count_leaks,
    evaluate,
    format_report,
    load_golden,
    recall_at_k,
    reciprocal_rank,
)
from rag_service.corpus import load_corpus
from tests.fixtures.db import db_engine
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine"]

A = Evidence("a.md", "가")
B = Evidence("b.md", "나")


def test_recall_counts_found_evidence_within_k() -> None:
    ranked = [("x.md", "x"), ("a.md", "가"), ("y.md", None), ("b.md", "나")]

    assert recall_at_k(ranked, [A], k=5) == 1.0
    assert recall_at_k(ranked, [A, B], k=3) == 0.5  # b는 4위라서 상위 3개 밖
    assert recall_at_k(ranked, [A, B], k=4) == 1.0


def test_reciprocal_rank_uses_first_hit_within_depth() -> None:
    ranked = [("x.md", "x"), ("b.md", "나"), ("a.md", "가")]

    assert reciprocal_rank(ranked, [A, B], depth=10) == 0.5
    assert reciprocal_rank(ranked, [A], depth=2) == 0.0
    assert reciprocal_rank([], [A], depth=10) == 0.0


def test_count_leaks_counts_invisible_files() -> None:
    assert count_leaks(["a.md", "s.md", "s.md"], visible={"a.md"}) == 2
    assert count_leaks([], visible=set()) == 0


def test_golden_file_loads_with_expected_types() -> None:
    golden = load_golden(GOLDEN)

    assert len(golden) == 95
    assert sum(item.answerable for item in golden) == 75
    assert all(item.trap_files for item in golden if item.type == "permission")
    assert all(item.evidence for item in golden if item.answerable)


def test_cache_round_trip_keeps_float32_and_drops_unused(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = EmbeddingCache(path, "model-x")
    cache.put("가", [0.1, 0.2])
    cache.put("나", [0.3, 0.4])
    cache.save()

    reloaded = EmbeddingCache(path, "model-x")
    vector = reloaded.get("가")
    assert vector is not None
    assert vector == pytest.approx([0.1, 0.2], abs=1e-7)
    assert reloaded.get("없음") is None
    reloaded.save()  # 이번 실행에서 "가"만 썼다

    assert EmbeddingCache(path, "model-x").get("나") is None


def test_cache_rejects_other_model(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    EmbeddingCache(path, "model-x").save()

    with pytest.raises(ValueError, match="model-x"):
        EmbeddingCache(path, "model-y")


def test_cached_embedder_fails_on_miss_without_fallback(tmp_path: Path) -> None:
    embedder = CachedEmbedder(EmbeddingCache(tmp_path / "c.json", "m"))

    with pytest.raises(CacheMissError, match="--update-cache"):
        embedder.embed(["처음 보는 문장"])


def test_cached_embedder_fills_cache_from_fallback_once(tmp_path: Path) -> None:
    fallback = FakeEmbedder()
    embedder = CachedEmbedder(EmbeddingCache(tmp_path / "c.json", "m"), fallback)

    first = embedder.embed(["가", "나", "가"])
    second = embedder.embed(["나"])

    assert len(first) == 3
    assert first[0] == first[2]
    assert second == [first[1]]
    assert fallback.calls == [["가", "나"]]  # 중복과 두 번째 호출은 캐시에서


def test_evaluate_reports_metrics_and_no_leaks(db_engine: Engine, tmp_path: Path) -> None:
    embedder = CachedEmbedder(EmbeddingCache(tmp_path / "c.json", "m"), FakeEmbedder())

    result = evaluate(db_engine, load_corpus(SAMPLES), load_golden(GOLDEN), embedder)

    assert result["n_questions"] == 75
    assert result["acl_leaks"] == 0
    assert 0.0 <= result["hit_at_1"] <= result["recall_at_5"] <= 1.0
    assert set(result["by_type"]) == {"general", "code", "paraphrase"}
    assert (result["embedding_cache"], result["index"]) == (True, "flat")
    assert "권한 유출: 0건" in format_report(result)
