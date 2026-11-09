"""답변 생성 흐름 테스트 (가짜 LLM)."""

import pytest

from rag_service.answer.generate import answer_question, cited_numbers, is_refusal
from rag_service.answer.prompt import SYSTEM_PROMPT
from rag_service.answer.refusal import REFUSAL_MESSAGE
from rag_service.retrieval.hits import SearchHit
from tests.fixtures.llm import FakeLLM


def _hits(count: int, score: float = 0.9) -> list[SearchHit]:
    return [
        SearchHit(100 + i, f"{i}.md", f"문서{i}", f"섹션{i}", i or None, f"본문{i}", score)
        for i in range(count)
    ]


def test_no_hits_refuses_without_calling_llm() -> None:
    llm = FakeLLM("쓰이면 안 되는 답")

    answer = answer_question("질문", [], llm=llm)

    assert (answer.refused, answer.reason, answer.text) == (True, "no_hits", REFUSAL_MESSAGE)
    assert answer.completion is None
    assert llm.calls == []


def test_low_score_refuses_without_calling_llm_when_gate_is_on() -> None:
    llm = FakeLLM("쓰이면 안 되는 답")

    answer = answer_question("질문", _hits(3, score=0.001), llm=llm, min_score=0.01)

    assert (answer.refused, answer.reason) == (True, "low_score")
    assert llm.calls == []


def test_answer_maps_citation_numbers_to_context_hits() -> None:
    hits = _hits(6)
    llm = FakeLLM("출장비는 사전 승인이 필요합니다 [2]. 정산은 7일 이내입니다 [1][2].")

    answer = answer_question("출장비?", hits, llm=llm)

    assert answer.refused is False
    assert answer.reason is None
    assert [(c.number, c.chunk_id, c.file) for c in answer.citations] == [
        (2, 101, "1.md"),
        (1, 100, "0.md"),
    ]
    assert answer.invalid_citations == ()
    assert answer.completion is not None


def test_only_top_context_size_hits_are_sent_and_numbered() -> None:
    llm = FakeLLM("답 [1]")

    answer = answer_question("질문", _hits(8), llm=llm, context_size=3)

    system, prompt = llm.calls[0]
    assert system == SYSTEM_PROMPT
    assert [hit.chunk_id for hit in answer.context] == [100, 101, 102]
    assert 'index="3"' in prompt
    assert 'index="4"' not in prompt
    assert prompt.endswith("질문: 질문")


def test_out_of_range_citations_are_reported() -> None:
    answer = answer_question("질문", _hits(2), llm=FakeLLM("답 [1] 그리고 [5], [0]"))

    assert [c.number for c in answer.citations] == [1]
    assert answer.invalid_citations == (5, 0)


@pytest.mark.parametrize(
    "reply",
    [
        REFUSAL_MESSAGE,
        "문서에서 찾을 수 없습니다",
        "  문서에서 찾을 수 없습니다. 관련 규정이 없습니다.",
    ],
)
def test_llm_refusal_is_detected(reply: str) -> None:
    answer = answer_question("질문", _hits(2), llm=FakeLLM(reply))

    assert (answer.refused, answer.reason, answer.text) == (
        True,
        "not_in_documents",
        REFUSAL_MESSAGE,
    )
    assert answer.citations == ()
    assert answer.completion is not None
    assert len(answer.context) == 2


def test_answer_mentioning_refusal_later_is_not_a_refusal() -> None:
    # 일부만 답하고 나머지는 없다고 밝히는 답 (규칙 4)은 거절이 아니다
    assert not is_refusal("국내 출장은 3만 원입니다 [1]. 해외 출장은 문서에서 찾을 수 없습니다.")


def test_cited_numbers_keep_first_order_without_duplicates() -> None:
    assert cited_numbers("a [3] b [1, 3] c [2][1] d [x] e [ 4 ]") == [3, 1, 2]


def test_context_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="context_size"):
        answer_question("질문", _hits(1), llm=FakeLLM("답"), context_size=0)
