"""done 이벤트 내용(answer_payload) 테스트. LLM을 부르지 않은 거절에는 검증과 사용량이 없다."""

import pytest

from rag_service.answer.generate import stream_answer
from rag_service.api.ask import answer_payload
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.streaming_llm import FakeStreamingLLM


def test_score_gate_refusal_has_no_verification_or_usage() -> None:
    llm = FakeStreamingLLM(["안 쓰임"])
    stream = stream_answer("볼 수 있는 문서가 없는 사용자의 질문", [], llm=llm)
    with pytest.raises(StopIteration) as stop:  # 검색 결과가 없으면 아무것도 흘려보내지 않는다
        next(stream)

    payload = answer_payload(stop.value.value, question="q", tokenizer=KoreanTokenizer())

    assert (payload["refused"], payload["reason"]) == (True, "no_hits")
    assert (payload["verification"], payload["usage"]) == (None, None)
    assert llm.calls == []
