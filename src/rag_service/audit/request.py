"""감사 재현용 요청 지문: LLM 파라미터, 요청에 넣은 조각 목록, 요청 해시.

요청 해시는 LLM에 실제로 보내는 인자(모델·파라미터 + 시스템 프롬프트 + 사용자 메시지)를 키 순서를
고정한 JSON으로 만들어 sha256을 낸 값이다. ClaudeLLM이면 ClaudeLLM.request()의 결과와 같은 내용이다
(tests/audit/test_request_fingerprint.py가 확인한다).
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from rag_service.retrieval.hits import SearchHit


class ContextChunk(TypedDict):
    """요청의 <document> 하나를 다시 만드는 데 필요한 값 (본문은 chunk_snapshots에 있다)."""

    chunk_key: str | None
    content_sha256: str
    file: str
    title: str
    section: str | None
    page: int | None


def llm_params(llm: object) -> dict[str, Any]:
    """시스템 프롬프트와 메시지를 뺀 요청 인자. request()가 없는 가짜 LLM은 클래스 이름."""
    request = getattr(llm, "request", None)
    if not callable(request):
        return {"llm": type(llm).__name__}
    params = dict(request(system="", prompt=""))
    params.pop("system")
    params.pop("messages")
    return params


def request_payload(params: Mapping[str, Any], *, system: str, prompt: str) -> dict[str, Any]:
    return {**params, "system": system, "messages": [{"role": "user", "content": prompt}]}


def request_sha256(params: Mapping[str, Any], *, system: str, prompt: str) -> str:
    payload = request_payload(params, system=system, prompt=prompt)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_sha256(text: str) -> str:
    """조각 본문 해시 (chunks.content_sha256, chunk_snapshots의 키와 같은 방식)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def context_chunks(hits: Sequence[SearchHit]) -> list[ContextChunk]:
    return [
        ContextChunk(
            chunk_key=hit.chunk_key,
            content_sha256=content_sha256(hit.content),
            file=hit.file,
            title=hit.title,
            section=hit.section,
            page=hit.page,
        )
        for hit in hits
    ]


def hits_from_snapshot(
    chunks: Sequence[Mapping[str, Any]], contents: Mapping[str, str]
) -> list[SearchHit]:
    """감사 기록의 조각 목록과 스냅샷 본문(해시 → 본문)으로 요청에 들어간 근거 조각을 다시 만든다.

    프롬프트(build_prompt)는 번호, 제목, 섹션, 페이지, 본문만 쓰므로 나머지 값은 의미가 없다.
    """
    return [
        SearchHit(
            chunk_id=0,
            file=chunk["file"],
            title=chunk["title"],
            section=chunk["section"],
            page=chunk["page"],
            content=contents[chunk["content_sha256"]],
            score=0.0,
            chunk_key=chunk["chunk_key"],
        )
        for chunk in chunks
    ]
