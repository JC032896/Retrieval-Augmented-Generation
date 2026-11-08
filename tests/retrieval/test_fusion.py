import pytest

from rag_service.retrieval.fusion import reciprocal_rank_fusion


def test_document_found_by_both_retrievers_ranks_first() -> None:
    bm25 = ["a", "b", "c"]
    vector = ["b", "d", "a"]

    fused = [doc_id for doc_id, _ in reciprocal_rank_fusion([bm25, vector])]

    assert fused[0] == "b"  # 1위 + 2위가 1위 + 3위보다 높다
    assert set(fused) == {"a", "b", "c", "d"}


def test_score_follows_rrf_formula() -> None:
    fused = dict(reciprocal_rank_fusion([["a"], ["x", "a"]], k=60))

    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)


def test_ties_are_broken_by_doc_id() -> None:
    fused = reciprocal_rank_fusion([["b"], ["a"]])

    assert [doc_id for doc_id, _ in fused] == ["a", "b"]


def test_duplicate_within_one_ranking_counts_once() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "a"]]))

    assert fused["a"] == pytest.approx(1 / 61)


def test_empty_input_returns_empty() -> None:
    assert reciprocal_rank_fusion([]) == []


def test_non_positive_k_is_rejected() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
