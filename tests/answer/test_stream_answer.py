"""스트리밍 답변 테스트: 조각을 내보내고, 거절 문구는 숨기고, 결과는 answer_question과 같다."""

from collections.abc import Generator

from rag_service.answer.generate import Answer, answer_question, stream_answer
from rag_service.retrieval.hits import SearchHit
from tests.fixtures.llm import FakeLLM
from tests.fixtures.streaming_llm import FakeStreamingLLM

HIT = SearchHit(1, "travel.md", "출장비 규정", "정산", None, "7일 이내에 정산한다.", 0.9)


def _run(stream: Generator[str, None, Answer]) -> tuple[list[str], Answer]:
    deltas: list[str] = []
    while True:
        try:
            deltas.append(next(stream))
        except StopIteration as stop:
            return deltas, stop.value


def test_streams_chunks_and_matches_answer_question() -> None:
    llm = FakeStreamingLLM(["7일 ", "이내에 ", "정산합니다 [1]"])

    deltas, answer = _run(stream_answer("정산 기한?", [HIT], llm=llm))

    expected = answer_question("정산 기한?", [HIT], llm=FakeLLM("7일 이내에 정산합니다 [1]"))
    assert deltas == ["7일 ", "이내에 ", "정산합니다 [1]"]
    assert (answer.text, answer.refused, answer.citations, answer.context) == (
        expected.text,
        expected.refused,
        expected.citations,
        expected.context,
    )


def test_refusal_text_is_not_streamed() -> None:
    llm = FakeStreamingLLM(["문서", "에서 찾을 수 ", "없습니다. 해외 출장 ", "규정이 없습니다."])

    deltas, answer = _run(stream_answer("해외 출장?", [HIT], llm=llm))

    assert deltas == []
    assert answer.refused
    assert answer.reason == "not_in_documents"


def test_text_that_only_starts_like_refusal_is_released() -> None:
    llm = FakeStreamingLLM(["문서", "에서 ", "다음을 확인했습니다 [1]", " 끝."])

    deltas, answer = _run(stream_answer("q", [HIT], llm=llm))

    assert deltas == ["문서에서 다음을 확인했습니다 [1]", " 끝."]
    assert not answer.refused


def test_short_answer_matching_refusal_start_is_released_at_end() -> None:
    deltas, answer = _run(stream_answer("q", [HIT], llm=FakeStreamingLLM(["문서"])))

    assert deltas == ["문서"]
    assert not answer.refused


def test_score_gate_refusal_does_not_call_llm() -> None:
    llm = FakeStreamingLLM(["안 쓰임"])

    deltas, answer = _run(stream_answer("q", [], llm=llm))

    assert (deltas, answer.reason, llm.calls) == ([], "no_hits", [])


def test_closing_the_stream_closes_the_llm_stream() -> None:
    llm = FakeStreamingLLM(["7일 ", "이내 [1]"])
    stream = stream_answer("q", [HIT], llm=llm)

    assert next(stream) == "7일 "
    stream.close()

    assert llm.closed
