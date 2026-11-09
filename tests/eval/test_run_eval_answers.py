"""eval/run_eval.py의 답변 평가(LLM 답변 캐시, 거절·인용 지표, 모델 비교표) 테스트."""

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import Engine

from eval.run_eval import (
    COMPARE_MODELS,
    EVAL_MODEL,
    GOLDEN,
    SAMPLES,
    AnswerCache,
    CachedEmbedder,
    CachedLLM,
    CachedReranker,
    CacheMissError,
    EmbeddingCache,
    Evidence,
    GoldenItem,
    RerankCache,
    evaluate,
    format_model_comparison,
    format_report,
    load_golden,
    score_answers,
)
from rag_service.answer.generate import Answer, Citation
from rag_service.answer.llm import Completion
from rag_service.answer.refusal import REFUSAL_MESSAGE
from rag_service.config import Settings
from rag_service.corpus import load_corpus
from tests.fixtures.db import db_engine
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.llm import FakeLLM
from tests.fixtures.rerank import OverlapReranker

__all__ = ["db_engine"]


def _item(item_id: str, kind: str, *evidence: tuple[str, str]) -> GoldenItem:
    return GoldenItem(item_id, kind, "kim", "질문", tuple(Evidence(*e) for e in evidence), ())


def _answer(*cited: tuple[str, str], refused: bool = False, invalid: int = 0) -> Answer:
    citations = tuple(
        Citation(n, n, file, "제목", section, None) for n, (file, section) in enumerate(cited, 1)
    )
    completion = Completion("답", "claude-sonnet-5-5", 1000, 100)
    if refused:
        return Answer(REFUSAL_MESSAGE, True, "not_in_documents", (), (), (), completion)
    return Answer("답", False, None, citations, (9,) * invalid, (), completion)


def test_score_answers_counts_refusals_and_citations() -> None:
    golden = [
        _item("g1", "general", ("a.md", "1조")),
        _item("g2", "general", ("a.md", "2조")),
        _item("c1", "code", ("b.md", "B")),
        _item("v1", "paraphrase", ("c.md", "C")),
        _item("u1", "unanswerable"),
        _item("p1", "permission"),
    ]
    answers = {
        "g1": _answer(("a.md", "1조"), ("z.md", "Z")),  # 적중, 정밀도 0.5
        "g2": _answer(("a.md", "1조")),  # 같은 파일 다른 조: 적중 아님
        "c1": _answer(invalid=1),  # 인용 없음
        "v1": _answer(refused=True),  # 잘못 거절
        "u1": _answer(refused=True),
        "p1": _answer(("x.md", "X")),  # 거절해야 하는데 답함
    }

    score = score_answers(golden, answers)

    assert score["refusal_recall"] == 0.5
    assert score["false_refusal_rate"] == 0.25
    assert score["citation_hit"] == pytest.approx(0.3333)  # 답한 3개 중 g1만
    assert score["citation_precision"] == pytest.approx(0.1667)  # (0.5 + 0 + 0) / 3
    assert score["invalid_citations"] == 1
    assert score["missed_refusals"] == ["p1"]
    assert score["false_refusals"] == ["v1"]
    assert score["uncited"] == ["c1"]
    assert score["citation_missed"] == ["c1", "g2"]
    assert (score["llm_calls"], score["input_tokens"], score["output_tokens"]) == (6, 6000, 600)
    assert score["cost_usd"] == pytest.approx(6 * 0.003)


def test_score_answers_cost_is_unknown_for_unpriced_model() -> None:
    golden = [_item("u1", "unanswerable")]
    unpriced = replace(_answer(refused=True), completion=Completion("답", "local", 10, 10))

    assert score_answers(golden, {"u1": unpriced})["cost_usd"] is None


def test_cached_llm_misses_without_fallback(tmp_path: Path) -> None:
    llm = CachedLLM(AnswerCache(tmp_path / "a.json"), "m", "medium")

    with pytest.raises(CacheMissError, match="update-cache"):
        llm.complete(system="s", prompt="p")


def test_cached_llm_calls_fallback_once_and_saves(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    fallback = FakeLLM("출장비는 7일 이내 [1]")
    llm = CachedLLM(AnswerCache(path), "m", "medium", fallback)

    first = llm.complete(system="s", prompt="p")
    second = llm.complete(system="s", prompt="p")
    llm.cache.save()

    assert first == second
    assert len(fallback.calls) == 1
    assert "출장비는 7일 이내" in path.read_text(encoding="utf-8")  # 한글 그대로 저장
    reloaded = CachedLLM(AnswerCache(path), "m", "medium")
    assert reloaded.complete(system="s", prompt="p") == first


@pytest.mark.parametrize(
    ("model", "effort", "system", "prompt"),
    [
        ("other", "medium", "s", "p"),
        ("m", "low", "s", "p"),
        ("m", "medium", "S", "p"),
        ("m", "medium", "s", "P"),
    ],
)
def test_answer_cache_key_covers_model_effort_and_prompts(
    model: str, effort: str, system: str, prompt: str
) -> None:
    assert AnswerCache.key(model, effort, system, prompt) != AnswerCache.key(
        "m", "medium", "s", "p"
    )


def test_answer_cache_save_keeps_only_used_entries(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    writer = CachedLLM(AnswerCache(path), "m", "medium", FakeLLM("답"))
    writer.complete(system="s", prompt="old")
    writer.complete(system="s", prompt="new")
    writer.cache.save()

    reader = CachedLLM(AnswerCache(path), "m", "medium")
    reader.complete(system="s", prompt="new")
    reader.cache.save()

    with pytest.raises(CacheMissError):
        CachedLLM(AnswerCache(path), "m", "medium").complete(system="s", prompt="old")


def test_eval_model_is_the_service_default_and_compared() -> None:
    assert Settings.model_fields["llm_model"].default == EVAL_MODEL
    assert EVAL_MODEL in COMPARE_MODELS


def _caches(tmp_path: Path) -> tuple[CachedEmbedder, CachedReranker]:
    embedder = CachedEmbedder(EmbeddingCache(tmp_path / "c.json", "m"), FakeEmbedder())
    reranker = CachedReranker(RerankCache(tmp_path / "r.json", "m"), OverlapReranker())
    return embedder, reranker


def test_evaluate_with_llm_reports_answer_metrics(db_engine: Engine, tmp_path: Path) -> None:
    embedder, reranker = _caches(tmp_path)
    fake = FakeLLM("답입니다 [1]")
    llm = CachedLLM(AnswerCache(tmp_path / "a.json"), EVAL_MODEL, "medium", fake)
    golden = load_golden(GOLDEN)

    result = evaluate(db_engine, load_corpus(SAMPLES), golden, embedder, reranker=reranker, llm=llm)

    answer = result["answer"]
    assert (answer["model"], answer["effort"]) == (EVAL_MODEL, "medium")
    assert answer["refusal_recall"] == 0.0  # 가짜 LLM은 거절하지 않는다
    assert answer["false_refusal_rate"] == 0.0
    assert answer["uncited"] == []
    assert answer["invalid_citations"] == 0
    assert 0.0 <= answer["citation_precision"] <= answer["citation_hit"] <= 1.0
    assert answer["llm_calls"] == len(fake.calls) <= len(golden)
    assert "답변: claude-sonnet-5-5" in format_report(result)


def test_evaluate_without_llm_has_no_answer_section(db_engine: Engine, tmp_path: Path) -> None:
    embedder, reranker = _caches(tmp_path)

    result = evaluate(
        db_engine, load_corpus(SAMPLES), load_golden(GOLDEN), embedder, reranker=reranker
    )

    assert "answer" not in result
    assert "답변:" not in format_report(result)


def test_refusing_llm_refuses_everything(db_engine: Engine, tmp_path: Path) -> None:
    embedder, reranker = _caches(tmp_path)
    llm = CachedLLM(AnswerCache(tmp_path / "a.json"), "m", "medium", FakeLLM(REFUSAL_MESSAGE))

    answer = evaluate(
        db_engine, load_corpus(SAMPLES), load_golden(GOLDEN), embedder, reranker=reranker, llm=llm
    )["answer"]

    assert (answer["refusal_recall"], answer["false_refusal_rate"]) == (1.0, 1.0)
    assert (answer["citation_hit"], answer["citation_precision"]) == (0.0, 0.0)


def test_model_comparison_table_has_one_row_per_model() -> None:
    row = {
        "refusal_recall": 0.95,
        "false_refusal_rate": 0.04,
        "citation_hit": 0.9,
        "citation_precision": 0.8,
        "uncited": ["g1"],
    }
    answers = [
        {**row, "model": "claude-haiku-5-5", "cost_usd": 0.095},
        {**row, "model": "local", "cost_usd": None},
    ]

    lines = format_model_comparison(answers, 95).splitlines()

    assert len(lines) == 4
    assert lines[2] == "| claude-haiku-5-5 | 0.950 | 0.040 | 0.900 | 0.800 | 1 | $0.0010 |"
    assert lines[3].endswith("| 1 | - |")
