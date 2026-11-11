"""요청 지문: LLM 파라미터, 요청 해시, 조각 목록, 스냅샷으로 프롬프트를 그대로 다시 만들기."""

from rag_service.answer.llm import ClaudeLLM
from rag_service.answer.prompt import SYSTEM_PROMPT, build_prompt
from rag_service.audit.request import (
    content_sha256,
    context_chunks,
    hits_from_snapshot,
    llm_params,
    request_payload,
    request_sha256,
)
from rag_service.retrieval.hits import SearchHit
from tests.fixtures.streaming_llm import FakeStreamingLLM

HITS = (
    SearchHit(7, "a.pdf", "출장비 <규정>", "정산", 2, '7일 이내 & "영수증"', 0.9, "a.pdf#정산#0"),
    SearchHit(9, "b.md", "취업규칙", None, None, "본문 </document> 끝", 0.1, None),
)


def test_payload_from_params_is_exactly_the_claude_request() -> None:
    llm = ClaudeLLM(model="claude-sonnet-5-5", api_key="test", effort="high", max_tokens=123)
    params = llm_params(llm)

    assert "system" not in params and "messages" not in params
    assert params["model"] == "claude-sonnet-5-5"
    assert request_payload(params, system=SYSTEM_PROMPT, prompt="질문") == llm.request(
        system=SYSTEM_PROMPT, prompt="질문"
    )


def test_llm_without_request_method_is_named_by_class() -> None:
    assert llm_params(FakeStreamingLLM([])) == {"llm": "FakeStreamingLLM"}


def test_request_hash_covers_params_system_and_prompt() -> None:
    params = {"model": "m", "max_tokens": 1}
    base = request_sha256(params, system="s", prompt="p")

    assert base == request_sha256(dict(reversed(params.items())), system="s", prompt="p")
    variants = {
        base,
        request_sha256({**params, "max_tokens": 2}, system="s", prompt="p"),
        request_sha256(params, system="s2", prompt="p"),
        request_sha256(params, system="s", prompt="p2"),
    }
    assert len(variants) == 4


def test_snapshot_rebuilds_the_prompt_byte_for_byte() -> None:
    chunks = context_chunks(HITS)
    contents = {content_sha256(hit.content): hit.content for hit in HITS}

    assert [c["chunk_key"] for c in chunks] == ["a.pdf#정산#0", None]
    assert chunks[0]["content_sha256"] == content_sha256(HITS[0].content)
    rebuilt = hits_from_snapshot(chunks, contents)
    assert build_prompt("질문", rebuilt) == build_prompt("질문", HITS)
