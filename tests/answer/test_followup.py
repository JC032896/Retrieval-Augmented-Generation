"""이어 묻는 질문 다시 쓰기 (answer/followup.py): 앞 질문만 넣고, 첫 질문은 LLM을 부르지 않는다."""

from collections.abc import Generator
from dataclasses import dataclass, field

from rag_service.answer.followup import (
    FOLLOWUP_SYSTEM_PROMPT,
    MAX_PREVIOUS,
    build_followup_prompt,
    rewrite_question,
)
from rag_service.answer.llm import Completion, LLMError
from tests.fixtures.streaming_llm import FakeStreamingLLM


@dataclass
class BrokenLLM:
    calls: list[str] = field(default_factory=list)

    def stream(self, *, system: str, prompt: str) -> Generator[str, None, Completion]:
        self.calls.append(prompt)
        raise LLMError("연결 실패")
        yield ""


def test_first_question_is_not_rewritten_and_costs_nothing() -> None:
    llm = FakeStreamingLLM(["쓰이면 안 됨"])

    rewrite = rewrite_question(llm, [], "재택근무는 주 몇 회야?")

    assert (rewrite.question, rewrite.rewritten, rewrite.completion) == (
        "재택근무는 주 몇 회야?",
        False,
        None,
    )
    assert llm.calls == []


def test_follow_up_is_rewritten_from_previous_questions_only() -> None:
    llm = FakeStreamingLLM(["계약직의 재택근무는 ", "주 몇 회까지 가능한가?"])

    rewrite = rewrite_question(llm, ["재택근무는 주 몇 회야?"], "그럼 계약직은?")

    assert rewrite.question == "계약직의 재택근무는 주 몇 회까지 가능한가?"
    assert rewrite.rewritten is True
    assert rewrite.completion is not None and rewrite.completion.model == "fake"
    [(system, prompt)] = llm.calls
    assert system == FOLLOWUP_SYSTEM_PROMPT
    assert prompt == (
        "앞 질문:\n1. 재택근무는 주 몇 회야?\n\n마지막 질문: 그럼 계약직은?\n\n다시 쓴 질문:"
    )


def test_only_the_most_recent_previous_questions_are_sent() -> None:
    previous = [f"질문 {n}" for n in range(1, 8)]

    prompt = build_followup_prompt(previous, "마지막")

    kept = previous[-MAX_PREVIOUS:]
    assert all(question in prompt for question in kept)
    assert "질문 1\n" not in prompt and "질문 3\n" not in prompt
    assert prompt.startswith("앞 질문:\n1. 질문 4\n")


def test_output_is_cleaned_to_one_line_without_quotes_or_label() -> None:
    llm = FakeStreamingLLM(
        ['다시 쓴 질문: "계약직의 재택근무 횟수는?"\n설명: 앞 질문을 반영했습니다.']
    )

    rewrite = rewrite_question(llm, ["재택근무는 주 몇 회야?"], "그럼 계약직은?")

    assert rewrite.question == "계약직의 재택근무 횟수는?"


def test_unchanged_or_empty_output_keeps_the_original_question() -> None:
    same = rewrite_question(
        FakeStreamingLLM(["출장비 정산 기한은?"]), ["재택근무는?"], "출장비 정산 기한은?"
    )
    empty = rewrite_question(FakeStreamingLLM(["  \n ''\n"]), ["재택근무는?"], "그럼 계약직은?")

    assert (same.question, same.rewritten) == ("출장비 정산 기한은?", False)
    assert same.completion is not None
    assert (empty.question, empty.rewritten) == ("그럼 계약직은?", False)
    assert empty.completion is not None  # 부른 비용은 남긴다


def test_llm_failure_falls_back_to_the_original_question() -> None:
    llm = BrokenLLM()

    rewrite = rewrite_question(llm, ["재택근무는?"], "그럼 계약직은?")

    assert (rewrite.question, rewrite.rewritten, rewrite.completion) == (
        "그럼 계약직은?",
        False,
        None,
    )
    assert len(llm.calls) == 1


def test_long_output_is_cut() -> None:
    rewrite = rewrite_question(FakeStreamingLLM(["가" * 1500]), ["앞"], "뒤")

    assert len(rewrite.question) == 1000
