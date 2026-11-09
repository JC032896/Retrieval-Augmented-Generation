"""eval/run_eval.py의 리랭커 점수 캐시 테스트. CI는 이 캐시만으로 리랭커 검색기를 평가한다."""

from pathlib import Path

import pytest

from eval.run_eval import CachedReranker, CacheMissError, RerankCache
from tests.fixtures.rerank import OverlapReranker


def test_rerank_cache_round_trip_and_drops_unused(tmp_path: Path) -> None:
    path = tmp_path / "rerank.json"
    cache = RerankCache(path, "model-x")
    cache.put("질문", "가", 0.75)
    cache.put("질문", "나", 0.125)
    cache.save()

    reloaded = RerankCache(path, "model-x")
    assert reloaded.get("질문", "가") == 0.75
    assert reloaded.get("다른 질문", "가") is None  # 질문이 다르면 다른 항목
    reloaded.save()  # 이번 실행에서 ("질문", "가")만 썼다

    assert RerankCache(path, "model-x").get("질문", "나") is None


def test_rerank_cache_rejects_other_model(tmp_path: Path) -> None:
    path = tmp_path / "rerank.json"
    RerankCache(path, "model-x").save()

    with pytest.raises(ValueError, match="model-x"):
        RerankCache(path, "model-y")


def test_cached_reranker_fails_on_miss_without_fallback(tmp_path: Path) -> None:
    reranker = CachedReranker(RerankCache(tmp_path / "r.json", "m"))

    with pytest.raises(CacheMissError, match="--update-cache"):
        reranker.score("질문", ["처음 보는 조각"])


def test_cached_reranker_fills_cache_from_fallback_once(tmp_path: Path) -> None:
    fallback = OverlapReranker()
    reranker = CachedReranker(RerankCache(tmp_path / "r.json", "m"), fallback)

    first = reranker.score("가나", ["가", "가나", "가"])
    second = reranker.score("가나", ["가나"])

    assert first == [1.0, 2.0, 1.0]
    assert second == [2.0]
    assert fallback.calls == [("가나", ["가", "가나"])]  # 중복과 두 번째 호출은 캐시에서
