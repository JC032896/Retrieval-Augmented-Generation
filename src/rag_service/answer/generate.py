"""답변 생성: 점수 관문 → 인용 프롬프트 → LLM → 거절 판정과 인용 추출.

인용 번호가 근거 조각 범위를 벗어나면 invalid_citations에 모아 둔다. 인용한 문장이 실제로 그 조각에
있는지는 4c(인용 검증)에서 본다.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rag_service.answer.llm import LLM, Completion
from rag_service.answer.prompt import SYSTEM_PROMPT, build_prompt
from rag_service.answer.refusal import DEFAULT_MIN_SCORE, REFUSAL_MESSAGE, score_gate
from rag_service.retrieval.hits import SearchHit

# 리랭커 상위 5개에서 정답 문서 Recall@5가 1.0이었다 (README 6절). 더 넣으면 비용만 는다
DEFAULT_CONTEXT_SIZE = 5

AnswerRefusal = Literal["no_hits", "low_score", "not_in_documents"]

# [1], [1][3], [1, 3] 모두 인용으로 본다
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class Citation:
    number: int  # 답변 속 [번호]
    chunk_id: int
    file: str
    title: str
    section: str | None
    page: int | None


@dataclass(frozen=True)
class Answer:
    text: str
    refused: bool
    reason: AnswerRefusal | None
    citations: tuple[Citation, ...]  # 답변에 처음 나온 순서
    invalid_citations: tuple[int, ...]  # 근거 조각에 없는 번호
    context: tuple[SearchHit, ...]  # LLM에 보낸 근거 조각 (번호 = 위치 + 1)
    completion: Completion | None  # 점수 관문에서 거절했으면 None (LLM을 부르지 않음)


def answer_question(
    question: str,
    hits: Sequence[SearchHit],
    *,
    llm: LLM,
    min_score: float | None = DEFAULT_MIN_SCORE,
    context_size: int = DEFAULT_CONTEXT_SIZE,
) -> Answer:
    """검색 결과(점수 내림차순)로 인용이 달린 답변을 만든다."""
    if context_size < 1:
        raise ValueError("context_size는 1 이상이어야 합니다")
    gate = score_gate(hits, min_score=min_score)
    if gate.refuse:
        return _refusal(gate.reason, context=(), completion=None)

    context = tuple(hits[:context_size])
    completion = llm.complete(system=SYSTEM_PROMPT, prompt=build_prompt(question, context))
    if is_refusal(completion.text):
        return _refusal("not_in_documents", context=context, completion=completion)

    numbers = cited_numbers(completion.text)
    return Answer(
        text=completion.text,
        refused=False,
        reason=None,
        citations=tuple(_citation(n, context[n - 1]) for n in numbers if 1 <= n <= len(context)),
        invalid_citations=tuple(n for n in numbers if not 1 <= n <= len(context)),
        context=context,
        completion=completion,
    )


def is_refusal(text: str) -> bool:
    """LLM이 거절 문구로 답을 시작했으면 거절로 본다 (뒤에 설명을 덧붙여도)."""
    return text.strip().startswith(REFUSAL_MESSAGE.rstrip("."))


def cited_numbers(text: str) -> list[int]:
    """답변에 나온 인용 번호를 처음 나온 순서대로, 중복 없이 돌려준다."""
    numbers: dict[int, None] = {}
    for match in _CITATION.finditer(text):
        for part in match.group(1).split(","):
            numbers.setdefault(int(part), None)
    return list(numbers)


def _citation(number: int, hit: SearchHit) -> Citation:
    return Citation(number, hit.chunk_id, hit.file, hit.title, hit.section, hit.page)


def _refusal(
    reason: AnswerRefusal | None, *, context: tuple[SearchHit, ...], completion: Completion | None
) -> Answer:
    return Answer(REFUSAL_MESSAGE, True, reason, (), (), context, completion)
